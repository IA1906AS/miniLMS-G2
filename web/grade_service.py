"""Nghiệp vụ sửa điểm — nơi duy nhất chứa logic chống 3 lỗi V01-V03.

Kiến trúc: route (quiz.py/admin.py) chỉ kiểm tra quyền rồi gọi service này.
Mọi entry point sửa điểm đều đi qua đây để không route nào quên kiểm tra.

V01 — Lost update (Optimistic Locking):
    Client gửi kèm ``version`` đã đọc. Service phát một câu
    ``UPDATE ... WHERE id = ? AND version = ?`` (compare-and-set).
    Nếu version đã bị người khác đổi, câu UPDATE khớp 0 dòng
    (``rowcount == 0``) và service ném ``GradeConflict`` để route trả 409.
    Không đọc-rồi-ghi bằng Python vì vẫn có khe hở giữa đọc và ghi.

V02 — 500 khi sửa điểm quiz:
    Model ``QuizAttempt`` chỉ có ``quiz_id``, không có relationship ``quiz``.
    Service truy vấn ``Quiz`` theo khoá ngoại rồi mới tính ``passed``.

V03 — Dữ liệu điểm không hợp lệ / mất nhận xét:
    ``parse_score`` chặn NaN, Infinity, giá trị ngoài [0, max_score] và
    chấp nhận dấu phẩy thập phân. ``feedback`` chỉ bị ghi khi client thực
    sự gửi trường này (khác ``None``).

Luồng một lần sửa điểm:
    route kiểm tra quyền
    -> parse_version / parse_score (validate, chưa chạm DB)
    -> UPDATE có điều kiện version (nguyên tử ở DB)
    -> tăng version + ghi audit
    -> route trả 302 (thành công) hoặc 409 (xung đột) / flash lỗi (validate).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from sqlalchemy import update
from sqlalchemy.orm import Session

from web.audit import record as audit_record
from web.models import Assignment, Quiz, QuizAttempt, Submission, utcnow

QUIZ_MAX_SCORE = 10.0


class GradeError(Exception):
    """Lỗi nghiệp vụ khi sửa điểm."""


class GradeValidationError(GradeError):
    """Dữ liệu đầu vào không hợp lệ."""


class GradeNotFound(GradeError):
    """Không tìm thấy bản ghi điểm."""


class GradeConflict(GradeError):
    """Version lệch: bản ghi đã bị sửa bởi người khác."""

    def __init__(self, current_score: float | None, current_version: int) -> None:
        super().__init__("Điểm đã được người khác cập nhật. Vui lòng tải lại trang.")
        self.current_score = current_score
        self.current_version = current_version


@dataclass(frozen=True)
class GradeResult:
    old_score: float | None
    new_score: float
    version: int


def parse_version(raw: Any) -> int:
    """V01: đọc ``version`` client gửi lên — bắt buộc và phải là số nguyên >= 1.

    Thiếu version nghĩa là client không chứng minh được mình đã đọc bản ghi
    nào, nên từ chối luôn thay vì mặc định version = 1 (nếu mặc định sẽ vô
    tình bỏ qua Optimistic Locking).
    """
    if raw is None or str(raw).strip() == "":
        raise GradeValidationError("Thiếu phiên bản bản ghi (version). Hãy tải lại trang rồi thử lại.")
    try:
        version = int(str(raw).strip())
    except (TypeError, ValueError) as exc:
        raise GradeValidationError("Phiên bản bản ghi không hợp lệ.") from exc
    if version < 1:
        raise GradeValidationError("Phiên bản bản ghi không hợp lệ.")
    return version


def parse_score(raw: Any, max_score: float) -> float:
    """V03: chuẩn hoá và kiểm tra điểm trước khi ghi DB.

    Thứ tự kiểm tra cố ý:
    1. rỗng -> lỗi;
    2. đổi dấu phẩy thành dấu chấm (người Việt nhập 7,5);
    3. ép float, bắt ValueError;
    4. ``math.isfinite`` chặn NaN/Infinity (NaN không bị các phép so sánh
       ``< 0`` hay ``> max`` chặn vì mọi so sánh với NaN đều False);
    5. chặn ngoài [0, max_score];
    6. làm tròn 2 chữ số thập phân.
    """
    if raw is None or str(raw).strip() == "":
        raise GradeValidationError("Điểm là bắt buộc.")
    text = str(raw).strip().replace(",", ".")
    try:
        value = float(text)
    except (TypeError, ValueError) as exc:
        raise GradeValidationError("Điểm phải là một số.") from exc
    if not math.isfinite(value):
        raise GradeValidationError("Điểm phải là số hữu hạn.")
    if value < 0 or value > float(max_score):
        raise GradeValidationError(f"Điểm phải nằm trong khoảng 0–{max_score}.")
    return round(value, 2)


def update_quiz_grade(
    sess: Session,
    actor: dict[str, Any],
    attempt_id: int,
    score_raw: Any,
    expected_version_raw: Any,
) -> GradeResult:
    """Sửa điểm quiz: V02 (lấy Quiz theo FK) + V01 (version) + V03 (miền điểm)."""
    attempt = sess.get(QuizAttempt, attempt_id)
    if attempt is None:
        raise GradeNotFound("Không tìm thấy lượt làm bài.")

    # V02: QuizAttempt chỉ có quiz_id, KHÔNG có relationship "quiz".
    # Truy vấn thẳng bảng quizzes theo khoá ngoại thay vì attempt.quiz.
    quiz = sess.get(Quiz, attempt.quiz_id)
    if quiz is None:
        raise GradeNotFound("Không tìm thấy bài kiểm tra.")

    # V01: version client gửi phải khớp version đang có.
    expected = parse_version(expected_version_raw)
    if attempt.version != expected:
        # Kiểm tra sớm để trả lỗi nhanh; UPDATE bên dưới mới là chốt chặn nguyên tử.
        audit_record(
            "GRADE_CONFLICT",
            f"quiz_attempt:{attempt_id}",
            actor_id=actor["id"],
            expected_version=expected,
            current_version=attempt.version,
            current_score=attempt.score,
        )
        raise GradeConflict(attempt.score, attempt.version)

    # V03: validate trước khi UPDATE; NaN/ngoài miền không bao giờ chạm DB.
    new_score = parse_score(score_raw, QUIZ_MAX_SCORE)
    old_score = attempt.score

    # V01: compare-and-set nguyên tử.
    # Chỉ UPDATE nếu version vẫn đúng; DB tự đảm bảo hai request đồng thời
    # không cùng ghi đè (một request sẽ khớp 0 dòng).
    result = sess.execute(
        update(QuizAttempt)
        .where(
            QuizAttempt.id == attempt_id,
            QuizAttempt.version == expected,
        )
        .values(
            score=new_score,
            passed=new_score >= float(quiz.pass_score),
            version=expected + 1,
        )
        .execution_options(synchronize_session=False)
    )

    # rowcount == 0: version đã bị người khác đổi giữa lúc đọc và lúc ghi.
    if result.rowcount == 0:  # type: ignore[attr-defined]
        sess.expire_all()
        current = sess.get(QuizAttempt, attempt_id)
        if current is None:
            raise GradeNotFound("Không tìm thấy lượt làm bài.")
        audit_record(
            "GRADE_CONFLICT",
            f"quiz_attempt:{attempt_id}",
            actor_id=actor["id"],
            expected_version=expected,
            current_version=current.version,
            current_score=current.score,
        )
        raise GradeConflict(current.score, current.version)

    # Bulk UPDATE không cập nhật object ORM đang giữ; expire để lần đọc sau lấy dữ liệu mới.
    sess.expire(attempt)
    audit_record(
        "GRADE_UPDATE",
        f"quiz_attempt:{attempt_id}",
        actor_id=actor["id"],
        old_score=old_score,
        new_score=new_score,
        version=expected + 1,
    )
    return GradeResult(old_score=old_score, new_score=new_score, version=expected + 1)


def update_submission_grade(
    sess: Session,
    actor: dict[str, Any],
    submission_id: int,
    score_raw: Any,
    feedback_raw: Any,
    expected_version_raw: Any,
) -> GradeResult:
    """Sửa điểm bài nộp: V01 (version) + V03 (miền điểm, giữ nhận xét)."""
    submission = sess.get(Submission, submission_id)
    if submission is None:
        raise GradeNotFound("Không tìm thấy bài nộp.")

    # Lấy bài tập để biết max_score thật (mỗi bài có thang điểm riêng).
    assignment = sess.get(Assignment, submission.assignment_id)
    if assignment is None:
        raise GradeNotFound("Không tìm thấy bài tập.")

    # V01: version client gửi phải khớp version đang có.
    expected = parse_version(expected_version_raw)
    if submission.version != expected:
        # Fast-fail; UPDATE bên dưới vẫn là chốt chặn nguyên tử.
        audit_record(
            "GRADE_CONFLICT",
            f"submission:{submission_id}",
            actor_id=actor["id"],
            expected_version=expected,
            current_version=submission.version,
            current_score=submission.score,
        )
        raise GradeConflict(submission.score, submission.version)

    # V03: validate trước UPDATE; 99/-1/NaN/Infinity bị chặn tại đây.
    new_score = parse_score(score_raw, assignment.max_score)
    old_score = submission.score

    values: dict[str, Any] = {
        "score": new_score,
        "graded_at": utcnow(),
        "version": expected + 1,  # V01: mỗi lần ghi thành công tăng version
    }
    # V03: chỉ ghi feedback khi client thực sự gửi trường này.
    # - feedback_raw is None  -> không gửi => giữ nguyên nhận xét cũ
    # - feedback_raw == ""    -> người dùng chủ động xoá nhận xét
    if feedback_raw is not None:
        text = str(feedback_raw).strip()
        values["feedback"] = text or None

    # V01: compare-and-set nguyên tử.
    # Câu UPDATE chỉ khớp khi id và version cùng đúng; nếu người khác đã
    # sửa trước, rowcount = 0 và không có dữ liệu nào bị ghi đè.
    result = sess.execute(
        update(Submission)
        .where(
            Submission.id == submission_id,
            Submission.version == expected,
        )
        .values(**values)
        .execution_options(synchronize_session=False)
    )

    # rowcount == 0: version đã bị đổi giữa lúc đọc và lúc ghi.
    if result.rowcount == 0:  # type: ignore[attr-defined]
        sess.expire_all()
        current = sess.get(Submission, submission_id)
        if current is None:
            raise GradeNotFound("Không tìm thấy bài nộp.")
        audit_record(
            "GRADE_CONFLICT",
            f"submission:{submission_id}",
            actor_id=actor["id"],
            expected_version=expected,
            current_version=current.version,
            current_score=current.score,
        )
        raise GradeConflict(current.score, current.version)

    # Bulk UPDATE không đồng bộ object ORM; expire để lần đọc sau lấy dữ liệu mới.
    sess.expire(submission)
    audit_record(
        "GRADE_UPDATE",
        f"submission:{submission_id}",
        actor_id=actor["id"],
        old_score=old_score,
        new_score=new_score,
        version=expected + 1,
    )
    return GradeResult(old_score=old_score, new_score=new_score, version=expected + 1)
