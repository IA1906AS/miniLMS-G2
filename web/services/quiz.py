"""Ngân hàng câu hỏi, quiz tự chấm, bài tập nộp file và chấm thủ công."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from web.models import (
    Assignment,
    CourseSection,
    Question,
    Quiz,
    QuizAnswer,
    QuizAttempt,
    QuizQuestion,
    Submission,
    User,
    utcnow,
)
from web.services import activity
from web.services.content import can_manage_section


class QuizError(Exception):
    """Vi phạm quy tắc nghiệp vụ của quiz/bài tập."""


QUESTION_KINDS = {"MCQ", "TRUE_FALSE", "SHORT"}


# ---------------------------------------------------------------------------
# Ngân hàng câu hỏi
# ---------------------------------------------------------------------------


def create_question(
    sess: Session,
    actor: dict[str, Any],
    *,
    prompt: str,
    kind: str = "MCQ",
    options: list[str] | None = None,
    answer: dict[str, Any] | None = None,
    points: float = 1.0,
    course_id: str | None = None,
    tags: str = "",
) -> Question:
    if not prompt.strip():
        raise QuizError("Nội dung câu hỏi là bắt buộc.")
    if kind not in QUESTION_KINDS:
        raise QuizError("Loại câu hỏi không hợp lệ.")
    if kind == "MCQ":
        opts = [o for o in (options or []) if o.strip()]
        if len(opts) < 2:
            raise QuizError("Câu hỏi trắc nghiệm cần ít nhất 2 lựa chọn.")
        index = int((answer or {}).get("index", -1))
        if not 0 <= index < len(opts):
            raise QuizError("Đáp án đúng phải nằm trong danh sách lựa chọn.")
        options = opts
        answer = {"index": index}
    elif kind == "TRUE_FALSE":
        options = ["Đúng", "Sai"]
        answer = {"value": bool((answer or {}).get("value", True))}
    else:
        options = []
        answer = {"text": str((answer or {}).get("text", "")).strip().lower()}

    question = Question(
        course_id=course_id,
        created_by=actor["id"],
        kind=kind,
        prompt=prompt.strip(),
        options=options,
        answer=answer,
        points=float(points),
        tags=tags.strip() or None,
    )
    sess.add(question)
    sess.flush()
    return question


def question_bank(
    sess: Session, *, course_id: str | None = None, q: str | None = None
) -> list[Question]:
    stmt = select(Question).order_by(Question.id.desc())
    if course_id:
        stmt = stmt.where(Question.course_id == course_id)
    if q:
        stmt = stmt.where(func.lower(Question.prompt).like(f"%{q.strip().lower()}%"))
    return list(sess.scalars(stmt).all())


def public_question_payload(question: Question) -> dict[str, Any]:
    """Payload gửi xuống trình duyệt — tuyệt đối không kèm đáp án."""
    return {
        "id": question.id,
        "kind": question.kind,
        "prompt": question.prompt,
        "options": question.options or [],
        "points": question.points,
    }


# ---------------------------------------------------------------------------
# Quiz
# ---------------------------------------------------------------------------


def create_quiz(
    sess: Session,
    actor: dict[str, Any],
    *,
    title: str,
    section_id: int | None = None,
    lesson_id: int | None = None,
    time_limit_min: int = 0,
    pass_score: float = 5.0,
    max_attempts: int = 0,
) -> Quiz:
    if section_id is not None and not can_manage_section(sess, actor, section_id):
        raise QuizError("Bạn không có quyền tạo quiz cho lớp này.")
    if not title.strip():
        raise QuizError("Tên quiz là bắt buộc.")
    quiz = Quiz(
        section_id=section_id,
        lesson_id=lesson_id,
        title=title.strip(),
        time_limit_min=max(0, int(time_limit_min)),
        pass_score=max(0.0, min(10.0, float(pass_score))),
        max_attempts=max(0, int(max_attempts)),
    )
    sess.add(quiz)
    sess.flush()
    return quiz


def attach_questions(
    sess: Session, actor: dict[str, Any], quiz: Quiz, question_ids: list[int]
) -> int:
    if quiz.section_id is not None and not can_manage_section(
        sess, actor, quiz.section_id
    ):
        raise QuizError("Bạn không có quyền sửa quiz này.")
    added = 0
    for position, question_id in enumerate(question_ids, start=1):
        question = sess.get(Question, question_id)
        if question is None:
            continue
        exists = sess.scalars(
            select(QuizQuestion.id).where(
                QuizQuestion.quiz_id == quiz.id,
                QuizQuestion.question_id == question_id,
            )
        ).first()
        if exists:
            continue
        sess.add(
            QuizQuestion(quiz_id=quiz.id, question_id=question_id, position=position)
        )
        added += 1
    sess.flush()
    return added


def quiz_questions(sess: Session, quiz_id: int) -> list[Question]:
    return list(
        sess.scalars(
            select(Question)
            .join(QuizQuestion, QuizQuestion.question_id == Question.id)
            .where(QuizQuestion.quiz_id == quiz_id)
            .order_by(QuizQuestion.position, Question.id)
        ).all()
    )


def max_score(sess: Session, quiz_id: int) -> float:
    total = sess.scalar(
        select(func.coalesce(func.sum(Question.points), 0.0))
        .join(QuizQuestion, QuizQuestion.question_id == Question.id)
        .where(QuizQuestion.quiz_id == quiz_id)
    )
    return float(total or 0.0)


def start_attempt(sess: Session, student_id: str, quiz: Quiz) -> QuizAttempt:
    if quiz.max_attempts:
        used = sess.scalar(
            select(func.count())
            .select_from(QuizAttempt)
            .where(
                QuizAttempt.quiz_id == quiz.id,
                QuizAttempt.student_id == student_id,
                QuizAttempt.status == "SUBMITTED",
            )
        )
        if (used or 0) >= quiz.max_attempts:
            raise QuizError("Bạn đã dùng hết số lần làm bài.")

    existing = sess.scalars(
        select(QuizAttempt)
        .where(
            QuizAttempt.quiz_id == quiz.id,
            QuizAttempt.student_id == student_id,
            QuizAttempt.status == "IN_PROGRESS",
        )
        .order_by(QuizAttempt.id.desc())
    ).first()
    if existing is not None:
        return existing

    attempt = QuizAttempt(quiz_id=quiz.id, student_id=student_id, started_at=utcnow())
    sess.add(attempt)
    sess.flush()
    return attempt


def attempt_expired(quiz: Quiz, attempt: QuizAttempt) -> bool:
    if not quiz.time_limit_min:
        return False
    elapsed = (utcnow() - attempt.started_at).total_seconds()
    return elapsed > quiz.time_limit_min * 60


def _is_correct(question: Question, response: Any) -> bool:
    answer = dict(question.answer or {})
    if question.kind == "MCQ":
        return isinstance(response, dict) and response.get("index") == answer.get(
            "index"
        )
    if question.kind == "TRUE_FALSE":
        return isinstance(response, dict) and bool(response.get("value")) == bool(
            answer.get("value")
        )
    if question.kind == "SHORT":
        given = str((response or {}).get("text", "")).strip().lower()
        expected = str(answer.get("text", "")).strip().lower()
        return bool(expected) and given == expected
    return False


def submit_attempt(
    sess: Session,
    student_id: str,
    quiz: Quiz,
    attempt: QuizAttempt,
    responses: dict[str, Any],
) -> dict[str, Any]:
    """Chấm tự động. Idempotent: attempt đã nộp thì trả kết quả cũ."""
    if attempt.status == "SUBMITTED":
        return {
            "attempt": attempt,
            "score": attempt.score,
            "passed": attempt.passed,
            "already": True,
        }

    total = 0.0
    earned = 0.0
    for question in quiz_questions(sess, quiz.id):
        response = responses.get(str(question.id), {})
        ok = _is_correct(question, response)
        points = float(question.points) if ok else 0.0
        total += float(question.points)
        earned += points
        sess.add(
            QuizAnswer(
                attempt_id=attempt.id,
                question_id=question.id,
                response=response if isinstance(response, dict) else {},
                is_correct=ok,
                points=points,
            )
        )

    score = round(earned * 10.0 / total, 2) if total else 0.0
    attempt.submitted_at = utcnow()
    attempt.score = score
    attempt.passed = score >= quiz.pass_score
    attempt.status = "SUBMITTED"
    sess.flush()

    activity.log_event(
        sess,
        student_id,
        activity.VERB_QUIZ_SUBMITTED,
        section_id=quiz.section_id,
        object_type="quiz",
        object_id=str(quiz.id),
        payload={"score": score, "passed": attempt.passed},
    )
    if attempt.passed:
        activity.award_points(
            sess,
            student_id,
            activity.POINTS_QUIZ_PASS,
            "quiz_passed",
            ref_type="quiz",
            ref_id=str(quiz.id),
        )
    activity.evaluate_badges(sess, student_id)
    return {
        "attempt": attempt,
        "score": score,
        "passed": attempt.passed,
        "already": False,
    }


def attempts_of(sess: Session, quiz_id: int, student_id: str) -> list[QuizAttempt]:
    return list(
        sess.scalars(
            select(QuizAttempt)
            .where(
                QuizAttempt.quiz_id == quiz_id,
                QuizAttempt.student_id == student_id,
            )
            .order_by(QuizAttempt.id.desc())
        ).all()
    )


def quiz_results(sess: Session, quiz_id: int) -> list[dict[str, Any]]:
    rows = sess.execute(
        select(QuizAttempt, User.email)
        .join(User, QuizAttempt.student_id == User.id)
        .where(QuizAttempt.quiz_id == quiz_id, QuizAttempt.status == "SUBMITTED")
        .order_by(QuizAttempt.score.desc(), QuizAttempt.submitted_at)
    ).all()
    return [{"attempt": attempt, "email": email} for attempt, email in rows]


def quizzes_of_section(sess: Session, section_id: int) -> list[Quiz]:
    return list(sess.scalars(select(Quiz).where(Quiz.section_id == section_id)).all())


# ---------------------------------------------------------------------------
# Bài tập & chấm thủ công
# ---------------------------------------------------------------------------


def create_assignment(
    sess: Session,
    actor: dict[str, Any],
    *,
    section_id: int,
    title: str,
    description: str = "",
    due_at: datetime | None = None,
    max_score: float = 10.0,
    allow_file: bool = True,
) -> Assignment:
    if not can_manage_section(sess, actor, section_id):
        raise QuizError("Bạn không có quyền giao bài tập cho lớp này.")
    if not title.strip():
        raise QuizError("Tên bài tập là bắt buộc.")
    row = Assignment(
        section_id=section_id,
        title=title.strip(),
        description=description.strip() or None,
        due_at=due_at,
        max_score=max(0.0, float(max_score)),
        allow_file=allow_file,
    )
    sess.add(row)
    sess.flush()
    return row


def assignments_of_section(sess: Session, section_id: int) -> list[Assignment]:
    return list(
        sess.scalars(
            select(Assignment)
            .where(Assignment.section_id == section_id)
            .order_by(Assignment.id.desc())
        ).all()
    )


def submit_assignment(
    sess: Session,
    student_id: str,
    assignment: Assignment,
    *,
    text: str = "",
    file_path: str | None = None,
) -> Submission:
    if not text.strip() and not file_path:
        raise QuizError("Cần nhập nội dung hoặc đính kèm tệp.")
    if file_path and not assignment.allow_file:
        raise QuizError("Bài tập này không cho phép nộp tệp.")

    row = sess.scalars(
        select(Submission).where(
            Submission.assignment_id == assignment.id,
            Submission.student_id == student_id,
        )
    ).first()
    if row is None:
        row = Submission(assignment_id=assignment.id, student_id=student_id)
        sess.add(row)
    row.text = text.strip() or None
    row.file_path = file_path
    row.submitted_at = utcnow()
    row.status = "SUBMITTED"
    sess.flush()

    activity.log_event(
        sess,
        student_id,
        "assignment_submitted",
        object_type="assignment",
        object_id=str(assignment.id),
    )
    return row


def submissions_of(sess: Session, assignment_id: int) -> list[dict[str, Any]]:
    rows = sess.execute(
        select(Submission, User.email)
        .join(User, Submission.student_id == User.id)
        .where(Submission.assignment_id == assignment_id)
        .order_by(Submission.submitted_at)
    ).all()
    return [{"submission": sub, "email": email} for sub, email in rows]


def grade_submission(
    sess: Session,
    actor: dict[str, Any],
    submission: Submission,
    *,
    score: float,
    feedback: str = "",
) -> Submission:
    assignment = sess.get(Assignment, submission.assignment_id)
    if assignment is None:
        raise QuizError("Bài tập không tồn tại.")
    if not can_manage_section(sess, actor, assignment.section_id):
        raise QuizError("Bạn không có quyền chấm bài này.")
    if not 0 <= score <= assignment.max_score:
        raise QuizError("Điểm không nằm trong thang điểm của bài tập.")

    submission.score = float(score)
    submission.feedback = feedback.strip() or None
    submission.graded_by = actor["id"]
    submission.graded_at = utcnow()
    submission.status = "GRADED"
    sess.flush()
    return submission


def student_submissions(sess: Session, student_id: str) -> list[dict[str, Any]]:
    rows = sess.execute(
        select(Submission, Assignment, CourseSection)
        .join(Assignment, Submission.assignment_id == Assignment.id)
        .join(CourseSection, Assignment.section_id == CourseSection.id)
        .where(Submission.student_id == student_id)
        .order_by(Submission.submitted_at.desc())
    ).all()
    return [
        {"submission": sub, "assignment": assignment, "section": section}
        for sub, assignment, section in rows
    ]
