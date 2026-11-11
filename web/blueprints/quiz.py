"""Blueprint quiz + bài tập — spec mục 2 (SV) và 3 (GV).

SV:  /quizzes/:quizId, /quizzes/:quizId/attempts/:id, /assignments/:id
GV:  /instructor/quizzes, /instructor/assignments (xem instructor.py)
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from werkzeug.wrappers import Response

from web.audit import record as audit_record
from web.auth import current_user, login_required, role_required
from web.database import get_db
from web.grade_service import (
    GradeConflict,
    GradeNotFound,
    GradeValidationError,
    update_submission_grade,
)
from web.idempotency import (
    begin_idempotent_request,
    complete_idempotent_request,
    compute_request_hash,
    fail_idempotent_request,
)
from web.models import (
    ROLE_ADMIN,
    ROLE_INSTRUCTOR,
    ROLE_STUDENT,
    Assignment,
    Course,
    Enrollment,
    Question,
    Quiz,
    QuizAnswer,
    QuizAttempt,
    QuizQuestion,
    Submission,
    User,
    utcnow,
)
from web.storage import CODE_EXT, MAX_DOC_BYTES, delete_file, save_upload

bp = Blueprint("quiz", __name__)


def is_enrolled(sess: Session, student_id: str, course_id: str) -> bool:
    return bool(
        sess.scalars(
            select(Enrollment.id).where(
                Enrollment.course_id == course_id,
                Enrollment.student_id == student_id,
                Enrollment.status == "ACTIVE",
            )
        ).first()
    )


def can_manage(sess: Session, actor: dict[str, Any], course_id: str) -> bool:
    if actor["role"] == ROLE_ADMIN:
        return True
    if actor["role"] != ROLE_INSTRUCTOR:
        return False
    course = sess.get(Course, course_id)
    return course is not None and course.instructor_id == actor["id"]


def quiz_questions(sess: Session, quiz_id: int) -> list[Question]:
    return list(
        sess.scalars(
            select(Question)
            .join(QuizQuestion, QuizQuestion.question_id == Question.id)
            .where(QuizQuestion.quiz_id == quiz_id)
            .order_by(QuizQuestion.position, Question.id)
        ).all()
    )


def grade_attempt(
    sess: Session, quiz: Quiz, questions: list[Question], responses: dict[int, str]
) -> tuple[float, list[tuple[Question, bool, str]]]:
    """Chấm tự động. Trả (điểm thang 10, chi tiết từng câu)."""
    total_points = sum(q.points for q in questions) or 1.0
    earned = 0.0
    detail: list[tuple[Question, bool, str]] = []
    for question in questions:
        answer = dict(question.answer or {})
        correct_index = answer.get("index")
        options = list(question.options or [])
        correct_text = (
            options[correct_index] if isinstance(correct_index, int) and 0 <= correct_index < len(options) else ""
        )
        chosen = responses.get(question.id, "")
        is_correct = bool(correct_text) and chosen.strip() == correct_text.strip()
        if is_correct:
            earned += question.points
        detail.append((question, is_correct, correct_text))
    score = round(earned * 10 / total_points, 2) if total_points else 0.0
    return score, detail


# ---------------------------------------------------------------------------
# Làm bài kiểm tra
# ---------------------------------------------------------------------------


@bp.get("/quizzes/<int:quiz_id>")
@login_required
def intro(quiz_id: int) -> str | Response:
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        quiz = sess.get(Quiz, quiz_id)
        if quiz is None:
            abort(404)
        course = sess.get(Course, quiz.course_id)
        questions = quiz_questions(sess, quiz_id)

        staff = can_manage(sess, actor, quiz.course_id)
        enrolled = actor["role"] == ROLE_STUDENT and is_enrolled(sess, actor["id"], quiz.course_id)
        if not staff and not enrolled:
            abort(403)

        attempts: list[QuizAttempt] = []
        in_progress = None
        used = 0
        if actor["role"] == ROLE_STUDENT:
            attempts = list(
                sess.scalars(
                    select(QuizAttempt)
                    .where(
                        QuizAttempt.quiz_id == quiz_id,
                        QuizAttempt.student_id == actor["id"],
                    )
                    .order_by(QuizAttempt.started_at.desc())
                ).all()
            )
            used = len(attempts)
            in_progress = next((a for a in attempts if a.status == "IN_PROGRESS"), None)

        over_limit = bool(quiz.max_attempts) and used >= quiz.max_attempts

    return render_template(
        "quiz/intro.html",
        quiz=quiz,
        course=course,
        question_count=len(questions),
        total_points=sum(q.points for q in questions),
        staff=staff,
        enrolled=enrolled,
        attempts=attempts,
        in_progress=in_progress,
        used=used,
        over_limit=over_limit,
    )


@bp.post("/quizzes/<int:quiz_id>/start")
@role_required(ROLE_STUDENT)
def start(quiz_id: int) -> Response:
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        quiz = sess.get(Quiz, quiz_id)
        if quiz is None:
            abort(404)
        if not is_enrolled(sess, actor["id"], quiz.course_id):
            abort(403)

        attempt = sess.scalars(
            select(QuizAttempt).where(
                QuizAttempt.quiz_id == quiz_id,
                QuizAttempt.student_id == actor["id"],
                QuizAttempt.status == "IN_PROGRESS",
            )
        ).first()
        if attempt is None:
            used = (
                sess.scalar(
                    select(func.count())
                    .select_from(QuizAttempt)
                    .where(
                        QuizAttempt.quiz_id == quiz_id,
                        QuizAttempt.student_id == actor["id"],
                    )
                )
                or 0
            )
            if quiz.max_attempts and used >= quiz.max_attempts:
                flash("Bạn đã dùng hết số lượt làm bài.", "error")
                return redirect(url_for("quiz.intro", quiz_id=quiz_id))
            attempt = QuizAttempt(quiz_id=quiz_id, student_id=actor["id"])
            sess.add(attempt)
            sess.flush()
        attempt_id = attempt.id

    return redirect(url_for("quiz.take", quiz_id=quiz_id, attempt_id=attempt_id))


@bp.get("/quizzes/<int:quiz_id>/attempts/<int:attempt_id>")
@role_required(ROLE_STUDENT)
def take(quiz_id: int, attempt_id: int) -> str | Response:
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        quiz = sess.get(Quiz, quiz_id)
        attempt = sess.get(QuizAttempt, attempt_id)
        if quiz is None or attempt is None:
            abort(404)
        if attempt.student_id != actor["id"] or attempt.quiz_id != quiz_id:
            abort(403)
        if attempt.status != "IN_PROGRESS":
            return redirect(url_for("quiz.result", quiz_id=quiz_id, attempt_id=attempt_id))

        # Spec mục 5: làm bài trong thời lượng quy định.
        deadline = None
        remaining_seconds = None
        if quiz.time_limit_min and attempt.started_at:
            deadline = attempt.started_at + timedelta(minutes=quiz.time_limit_min)
            now = utcnow()
            if now > deadline:
                attempt.status = "EXPIRED"
                attempt.submitted_at = now
                attempt.score = 0.0
                attempt.passed = False
                sess.flush()
                flash("Đã hết thời gian làm bài.", "error")
                return redirect(url_for("quiz.result", quiz_id=quiz_id, attempt_id=attempt_id))
            remaining_seconds = int((deadline - now).total_seconds())

        questions = quiz_questions(sess, quiz_id)

    return render_template(
        "quiz/take.html",
        quiz=quiz,
        attempt=attempt,
        questions=questions,
        remaining_seconds=remaining_seconds,
    )


@bp.post("/quizzes/<int:quiz_id>/attempts/<int:attempt_id>/submit")
@role_required(ROLE_STUDENT)
def submit(quiz_id: int, attempt_id: int) -> Response:
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        quiz = sess.get(Quiz, quiz_id)
        attempt = sess.get(QuizAttempt, attempt_id)
        if quiz is None or attempt is None:
            abort(404)
        if attempt.student_id != actor["id"] or attempt.quiz_id != quiz_id:
            abort(403)
        if attempt.status != "IN_PROGRESS":
            flash("Bài này đã được nộp.", "error")
            return redirect(url_for("quiz.result", quiz_id=quiz_id, attempt_id=attempt_id))

        # Cưỡng chế thời lượng: quá giờ thì không chấm, đánh dấu hết hạn.
        if quiz.time_limit_min and attempt.started_at:
            deadline = attempt.started_at + timedelta(minutes=quiz.time_limit_min)
            now = utcnow()
            if now > deadline + timedelta(seconds=30):
                attempt.status = "EXPIRED"
                attempt.submitted_at = now
                attempt.score = 0.0
                attempt.passed = False
                sess.flush()
                flash("Đã quá thời gian làm bài, bài không được chấp nhận.", "error")
                return redirect(url_for("quiz.result", quiz_id=quiz_id, attempt_id=attempt_id))

        questions = quiz_questions(sess, quiz_id)
        responses = {q.id: (request.form.get(f"q_{q.id}") or "") for q in questions}
        score, detail = grade_attempt(sess, quiz, questions, responses)

        for question, is_correct, _ in detail:
            sess.add(
                QuizAnswer(
                    attempt_id=attempt.id,
                    question_id=question.id,
                    response={"value": responses.get(question.id, "")},
                    is_correct=is_correct,
                    points=question.points if is_correct else 0.0,
                )
            )

        attempt.score = score
        attempt.passed = score >= quiz.pass_score
        attempt.submitted_at = utcnow()
        attempt.status = "SUBMITTED"
        sess.flush()
        flash(f"Đã nộp bài. Điểm: {score}/10.", "success")

    return redirect(url_for("quiz.result", quiz_id=quiz_id, attempt_id=attempt_id))


@bp.get("/quizzes/<int:quiz_id>/attempts/<int:attempt_id>/result")
@login_required
def result(quiz_id: int, attempt_id: int) -> str | Response:
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        quiz = sess.get(Quiz, quiz_id)
        attempt = sess.get(QuizAttempt, attempt_id)
        if quiz is None or attempt is None:
            abort(404)
        staff = can_manage(sess, actor, quiz.course_id)
        if not staff and attempt.student_id != actor["id"]:
            abort(403)
        if attempt.status != "SUBMITTED":
            return redirect(url_for("quiz.take", quiz_id=quiz_id, attempt_id=attempt_id))

        questions = quiz_questions(sess, quiz_id)
        answers = {
            a.question_id: a for a in sess.scalars(select(QuizAnswer).where(QuizAnswer.attempt_id == attempt_id)).all()
        }
        detail = []
        for question in questions:
            answer = dict(question.answer or {})
            options = list(question.options or [])
            idx = answer.get("index")
            correct_text = options[idx] if isinstance(idx, int) and 0 <= idx < len(options) else ""
            given = answers.get(question.id)
            chosen = dict(given.response or {}).get("value", "") if given else ""
            detail.append(
                {
                    "question": question,
                    "chosen": chosen,
                    "correct": correct_text,
                    "is_correct": bool(given and given.is_correct),
                }
            )
        student = sess.get(User, attempt.student_id)
        # Spec dòng 41: chỉ hiện đáp án nếu GV cho phép.
        show_answers = quiz.show_answers or staff

    return render_template(
        "quiz/result.html",
        quiz=quiz,
        attempt=attempt,
        detail=detail,
        staff=staff,
        student=student,
        show_answers=show_answers,
    )


# ---------------------------------------------------------------------------
# Bài tập
# ---------------------------------------------------------------------------


@bp.get("/assignments/<int:assignment_id>")
@login_required
def assignment_detail(assignment_id: int) -> str:
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        context = _assignment_context(sess, actor, assignment_id)

    return render_template("quiz/assignment_detail.html", **context)


def _assignment_context(sess: Session, actor: dict[str, Any], assignment_id: int) -> dict[str, Any]:
    assignment = sess.get(Assignment, assignment_id)
    if assignment is None:
        abort(404)
    course = sess.get(Course, assignment.course_id)
    staff = can_manage(sess, actor, assignment.course_id)
    enrolled = actor["role"] == ROLE_STUDENT and is_enrolled(sess, actor["id"], assignment.course_id)
    if not staff and not enrolled:
        abort(403)

    submission = None
    if actor["role"] == ROLE_STUDENT:
        submission = sess.scalars(
            select(Submission).where(
                Submission.assignment_id == assignment_id,
                Submission.student_id == actor["id"],
            )
        ).first()
    else:
        submission = sess.scalars(
            select(Submission).where(Submission.assignment_id == assignment_id).order_by(Submission.submitted_at.desc())
        ).first()

    submissions = []
    if staff:
        rows = sess.execute(
            select(Submission, User)
            .join(User, Submission.student_id == User.id)
            .where(Submission.assignment_id == assignment_id)
            .order_by(Submission.submitted_at.desc())
        ).all()
        submissions = [{"submission": s, "student": u} for s, u in rows]

    return {
        "assignment": assignment,
        "course": course,
        "staff": staff,
        "enrolled": enrolled,
        "submission": submission,
        "submissions": submissions,
    }


@bp.post("/assignments/<int:assignment_id>/submit")
@role_required(ROLE_STUDENT)
def assignment_submit(assignment_id: int) -> Response:
    """Nộp hoặc cập nhật bài tập — được bảo vệ bởi Idempotency Key.

    Luồng Idempotency Key (Defensive Pattern #2):
      1. Client gửi trường ẩn ``idempotency_key`` (UUID v4, sinh bởi JS).
      2. Server tính SHA-256 của payload và cố INSERT bản ghi PENDING.
      3. Tuỳ trạng thái trả về:
         - NEW      → xử lý nghiệp vụ bình thường rồi đánh dấu COMPLETED.
         - PENDING  → 409 Conflict (đang có request song song cùng key).  [I02]
         - REPLAY   → replay redirect cũ, không lưu file mới.             [I01]
         - MISMATCH → 409 (cùng key nhưng payload khác).
         - FAILED   → cho phép retry (lỗi hệ thống trước đó).
    """
    actor = current_user()
    assert actor is not None

    redirect_target = url_for("quiz.assignment_detail", assignment_id=assignment_id)

    # --- Lấy Idempotency-Key từ form hoặc HTTP header ---
    idem_key = (request.form.get("idempotency_key") or "").strip() or request.headers.get("Idempotency-Key", "").strip()

    with get_db().session() as sess:
        assignment = sess.get(Assignment, assignment_id)
        if assignment is None:
            abort(404)
        if not is_enrolled(sess, actor["id"], assignment.course_id):
            abort(403)

        # Spec mục 4: chỉ nhận bài trong thời hạn quy định.
        if assignment.due_at is not None and utcnow() > assignment.due_at:
            flash("Đã quá hạn nộp bài, không thể nộp.", "error")
            return redirect(redirect_target)

        text = (request.form.get("text") or "").strip()
        file = request.files.get("file")
        has_file = file is not None and file.filename is not None and file.filename != ""
        if not text and not has_file:
            flash("Cần nhập nội dung hoặc đính kèm tệp bài làm.", "error")
            return redirect(redirect_target)

        # -------------------------------------------------------------------
        # Idempotency Key guard
        # Chỉ áp dụng khi client gửi kèm key (form web + Burp Repeater + API).
        # Nếu không có key: fallback về hành vi cũ (backward-compat).
        # -------------------------------------------------------------------
        if idem_key and len(idem_key) > 128:
            flash("Idempotency Key không hợp lệ (vượt quá 128 ký tự).", "error")
            return redirect(redirect_target)

        if idem_key:
            # Tính hash payload TRƯỚC khi lưu file (stream chưa bị đọc).
            req_hash = compute_request_hash(text, file if has_file else None)
            resource = f"assignment:{assignment_id}:submit"

            status, idem_record = begin_idempotent_request(
                sess,
                idem_key=idem_key,
                student_id=actor["id"],
                resource=resource,
                request_hash=req_hash,
            )

            if status == "PENDING":
                # [I02 FIX] Request song song cùng key đang được xử lý → 409
                flash(
                    "Yêu cầu nộp bài đang được xử lý, vui lòng chờ trong giây lát.",
                    "error",
                )
                return redirect(redirect_target), 409  # type: ignore[return-value]

            if status == "REPLAY":
                # [I01 FIX] Request lặp lại với cùng key & payload →
                # replay redirect cũ, KHÔNG lưu file mới, KHÔNG đổi submitted_at.
                replay_loc = idem_record.response_location if idem_record else redirect_target
                flash("Bài nộp đã được ghi nhận trước đó (yêu cầu lặp lại).", "info")
                resp = redirect(replay_loc or redirect_target)
                resp.headers["X-Idempotent-Replay"] = "true"
                return resp

            if status == "MISMATCH":
                # Cùng key nhưng payload khác → từ chối
                flash(
                    "Idempotency Key đã được dùng cho một yêu cầu khác. Vui lòng tải lại trang và nộp lại.",
                    "error",
                )
                return redirect(redirect_target), 409  # type: ignore[return-value]

            # status == "NEW" hoặc "FAILED" → tiến hành xử lý nghiệp vụ
            # idem_record đã ở trạng thái PENDING trong DB
        else:
            idem_record = None

        # -------------------------------------------------------------------
        # Nghiệp vụ nộp bài — chỉ chạy khi là request hợp lệ / mới
        # -------------------------------------------------------------------
        submission = sess.scalars(
            select(Submission).where(
                Submission.assignment_id == assignment_id,
                Submission.student_id == actor["id"],
            )
        ).first()
        old_file = submission.file_path if submission is not None else None

        new_rel: str | None = None
        if has_file:
            try:
                # save_upload gọi SAU khi đã xác nhận đây là request mới (không lặp)
                new_rel = save_upload(
                    file,
                    "submissions",
                    allowed=CODE_EXT,
                    max_bytes=MAX_DOC_BYTES,
                )
            except ValueError as exc:
                if idem_record is not None:
                    fail_idempotent_request(sess, idem_record)
                flash(str(exc), "error")
                return redirect(redirect_target)

        if submission is None:
            sess.add(
                Submission(
                    assignment_id=assignment_id,
                    student_id=actor["id"],
                    text=text or None,
                    file_path=new_rel,
                )
            )
            flash("Đã nộp bài tập.", "success")
        else:
            submission.text = text or None
            if new_rel is not None:
                submission.file_path = new_rel
            # [I01 FIX] Chỉ cập nhật submitted_at khi đây là request MỚI hợp lệ,
            # không phải request lặp — request lặp đã bị chặn ở khối REPLAY trên.
            submission.submitted_at = utcnow()
            flash("Đã cập nhật bài nộp.", "success")
        sess.flush()

        # Đánh dấu COMPLETED + lưu redirect target để replay sau này
        if idem_record is not None:
            complete_idempotent_request(sess, idem_record, redirect_target)

    if new_rel is not None and old_file:
        delete_file(old_file)
    audit_record(
        "ASSIGNMENT_SUBMITTED",
        f"assignment:{assignment_id}",
        actor_id=actor["id"],
        file=new_rel,
    )

    return redirect(redirect_target)


@bp.post("/assignments/<int:assignment_id>/submissions/<int:submission_id>/grade")
@role_required(ROLE_ADMIN, ROLE_INSTRUCTOR)
def assignment_grade(assignment_id: int, submission_id: int) -> Response | tuple[str, int]:
    """Giảng viên/admin chấm điểm một bài nộp.

    V01: form gửi kèm ``version``; service UPDATE có điều kiện version,
         lệch version -> GradeConflict -> HTTP 409.
    V03: service validate điểm theo ``assignment.max_score`` và chỉ ghi
         feedback khi client thực sự gửi trường này.
    """
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        assignment = sess.get(Assignment, assignment_id)
        submission = sess.get(Submission, submission_id)
        if assignment is None or submission is None:
            abort(404)
        # Quyền được kiểm tra theo khoá học của assignment trên URL.
        if not can_manage(sess, actor, assignment.course_id):
            abort(403)

        try:
            # Dùng chung service với route admin để mọi entry point có cùng
            # logic V01 (version) và V03 (validate + giữ feedback).
            update_submission_grade(
                sess,
                actor,
                submission_id,
                request.form.get("score"),
                request.form.get("feedback"),
                request.form.get("version"),
            )
        except GradeValidationError as exc:
            # V03: dữ liệu sai -> không ghi DB, quay lại trang bài nộp.
            flash(str(exc), "error")
            return redirect(url_for("quiz.assignment_detail", assignment_id=assignment_id))
        except GradeNotFound:
            abort(404)
        except GradeConflict as exc:
            # V01: người khác đã sửa -> render lại trang với 409.
            context = _assignment_context(sess, actor, assignment_id)
            context["conflict"] = str(exc)
            return (
                render_template("quiz/assignment_detail.html", **context),
                409,
            )

        flash("Đã chấm điểm và gửi nhận xét.", "success")

    return redirect(url_for("quiz.assignment_detail", assignment_id=assignment_id))
