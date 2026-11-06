"""Nghiệp vụ sửa điểm với Optimistic Locking (defensive pattern #3).

Mọi thay đổi điểm đều phải gửi kèm ``version`` mà client đã đọc. Nếu bản ghi
đã bị người khác sửa (version lệch) thì từ chối bằng ``GradeConflict`` — không
ghi đè âm thầm. Đồng thời chuẩn hoá & kiểm tra miền điểm ở phía server.
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
    """Đọc version client gửi lên; bắt buộc phải có."""
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
    """Chuẩn hoá và kiểm tra điểm trong [0, max_score]."""
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
    attempt = sess.get(QuizAttempt, attempt_id)
    if attempt is None:
        raise GradeNotFound("Không tìm thấy lượt làm bài.")
    quiz = sess.get(Quiz, attempt.quiz_id)
    if quiz is None:
        raise GradeNotFound("Không tìm thấy bài kiểm tra.")

    expected = parse_version(expected_version_raw)
    if attempt.version != expected:
        audit_record(
            "GRADE_CONFLICT",
            f"quiz_attempt:{attempt_id}",
            actor_id=actor["id"],
            expected_version=expected,
            current_version=attempt.version,
            current_score=attempt.score,
        )
        raise GradeConflict(attempt.score, attempt.version)

    new_score = parse_score(score_raw, QUIZ_MAX_SCORE)
    old_score = attempt.score

    # Compare-and-set nguyên tử: chỉ ghi khi version vẫn đúng.
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
    submission = sess.get(Submission, submission_id)
    if submission is None:
        raise GradeNotFound("Không tìm thấy bài nộp.")
    assignment = sess.get(Assignment, submission.assignment_id)
    if assignment is None:
        raise GradeNotFound("Không tìm thấy bài tập.")

    expected = parse_version(expected_version_raw)
    if submission.version != expected:
        audit_record(
            "GRADE_CONFLICT",
            f"submission:{submission_id}",
            actor_id=actor["id"],
            expected_version=expected,
            current_version=submission.version,
            current_score=submission.score,
        )
        raise GradeConflict(submission.score, submission.version)

    new_score = parse_score(score_raw, assignment.max_score)
    old_score = submission.score
    values: dict[str, Any] = {
        "score": new_score,
        "graded_at": utcnow(),
        "version": expected + 1,
    }
    # Chỉ cập nhật nhận xét khi client thực sự gửi trường này.
    if feedback_raw is not None:
        text = str(feedback_raw).strip()
        values["feedback"] = text or None

    # Compare-and-set nguyên tử: chỉ ghi khi version vẫn đúng.
    result = sess.execute(
        update(Submission)
        .where(
            Submission.id == submission_id,
            Submission.version == expected,
        )
        .values(**values)
        .execution_options(synchronize_session=False)
    )
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
