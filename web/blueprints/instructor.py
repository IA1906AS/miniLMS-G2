"""Blueprint giảng viên — spec mục 3.

Route: /instructor/courses, /instructor/courses/new,
       /instructor/courses/:id/edit, /instructor/courses/:id/curriculum,
       /instructor/courses/:id/students, /instructor/courses/:id/reports,
       /instructor/quizzes, /instructor/quizzes/:id/questions,
       /instructor/assignments, /instructor/grades, /instructor/certificates,
       /instructor/forum, /instructor/live
"""

from __future__ import annotations

import csv
import io
import math
from datetime import datetime
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
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, selectinload
from werkzeug.wrappers import Response

from app.auth import hash_password, verify_password
from web.audit import record as audit_record
from web.auth import current_user, instructor_required
from web.database import get_db
from web.mailer import send_notification
from web.models import (
    COURSE_DRAFT,
    COURSE_HIDDEN,
    COURSE_PUBLISHED,
    ENROLL_ACTIVE,
    ROLE_STUDENT,
    Assignment,
    Category,
    Certificate,
    Chapter,
    Course,
    DirectMessage,
    Enrollment,
    ForumPost,
    ForumTopic,
    Lesson,
    LessonProgress,
    LiveSession,
    Notification,
    Question,
    Quiz,
    QuizAttempt,
    QuizQuestion,
    Submission,
    User,
    utcnow,
)

bp = Blueprint("instructor", __name__, url_prefix="/instructor")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def my_course(sess: Session, actor: dict[str, Any], course_id: str) -> Course:
    """Spec dòng 147: GV chỉ thao tác khoá của mình."""
    course = sess.get(Course, course_id)
    if course is None:
        abort(404)
    if course.instructor_id != actor["id"]:
        abort(403)
    return course


def my_quiz(sess: Session, actor: dict[str, Any], quiz_id: int) -> Quiz:
    quiz = sess.get(Quiz, quiz_id)
    if quiz is None:
        abort(404)
    my_course(sess, actor, quiz.course_id)
    return quiz


def course_students(sess: Session, course_id: str) -> list[dict[str, Any]]:
    rows = sess.execute(
        select(Enrollment, User)
        .join(User, Enrollment.student_id == User.id)
        .where(Enrollment.course_id == course_id)
        .order_by(User.email)
    ).all()

    total = (
        sess.scalar(
            select(func.count())
            .select_from(Lesson)
            .join(Chapter, Lesson.chapter_id == Chapter.id)
            .where(Chapter.course_id == course_id)
        )
        or 0
    )
    out = []
    for enrollment, student in rows:
        done = (
            sess.scalar(
                select(func.count())
                .select_from(LessonProgress)
                .join(Lesson, LessonProgress.lesson_id == Lesson.id)
                .join(Chapter, Lesson.chapter_id == Chapter.id)
                .where(
                    Chapter.course_id == course_id,
                    LessonProgress.student_id == student.id,
                )
            )
            or 0
        )
        out.append(
            {
                "enrollment": enrollment,
                "student": student,
                "done": done,
                "total": total,
                "percent": round(done * 100 / total) if total else 0,
            }
        )
    return out


def parse_dt(value: str) -> datetime | None:
    value = (value or "").strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# Khoá học
# ---------------------------------------------------------------------------


@bp.get("/courses")
@instructor_required
def courses() -> str:
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        taught = sess.scalars(
            select(Course).where(Course.instructor_id == actor["id"]).order_by(Course.created_at.desc())
        ).all()
        rows = []
        for course in taught:
            students = (
                sess.scalar(select(func.count()).select_from(Enrollment).where(Enrollment.course_id == course.id)) or 0
            )
            lessons = (
                sess.scalar(
                    select(func.count())
                    .select_from(Lesson)
                    .join(Chapter, Lesson.chapter_id == Chapter.id)
                    .where(Chapter.course_id == course.id)
                )
                or 0
            )
            rows.append({"course": course, "students": students, "lessons": lessons})

    return render_template("instructor/courses.html", rows=rows)


def _parse_number(raw: str | None, default: float, upper: float | None = None) -> float | None:
    """Parse số hữu hạn, >= 0 (và <= upper nếu có). Không hợp lệ → None."""
    text = (raw or "").strip()
    if not text:
        return default
    try:
        # nosemgrep: python.flask.security.injection.nan-injection.nan-injection
        value = float(text)  # đã kiểm tra isfinite bên dưới
    except ValueError:
        return None
    if not math.isfinite(value) or value < 0 or (upper is not None and value > upper):
        return None
    return value


def _parse_price(raw: str | None) -> float | None:
    return _parse_number(raw, 0.0)


@bp.route("/courses/new", methods=["GET", "POST"])
@instructor_required
def course_new() -> str | Response:
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        categories = list(sess.scalars(select(Category).order_by(Category.name)).all())

        if request.method == "POST":
            title = (request.form.get("title") or "").strip()
            price = _parse_price(request.form.get("price"))
            if not title:
                flash("Tên khoá học là bắt buộc.", "error")
            elif price is None:
                flash("Học phí phải là số không âm.", "error")
            else:
                ids = sess.scalars(select(Course.id)).all()
                nums = [int(i[1:]) for i in ids if i[0] == "c" and i[1:].isdigit()]
                course = Course(
                    id=f"c{max(nums, default=0) + 1}",
                    title=title,
                    instructor_id=actor["id"],
                    slug=None,
                    description=(request.form.get("description") or "").strip() or None,
                    category_id=request.form.get("category_id", type=int),
                    price=price,
                    status=(
                        request.form.get("status")
                        if request.form.get("status") in {COURSE_DRAFT, COURSE_PUBLISHED, COURSE_HIDDEN}
                        else COURSE_DRAFT
                    ),
                )
                course.slug = course.id
                sess.add(course)
                sess.flush()
                flash("Đã tạo khoá học.", "success")
                return redirect(url_for("instructor.course_edit", course_id=course.id))

    return render_template("instructor/course_form.html", course=None, categories=categories)


@bp.route("/courses/<course_id>/edit", methods=["GET", "POST"])
@instructor_required
def course_edit(course_id: str) -> str | Response:
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        course = my_course(sess, actor, course_id)
        categories = list(sess.scalars(select(Category).order_by(Category.name)).all())

        if request.method == "POST":
            title = (request.form.get("title") or "").strip()
            raw_price = (request.form.get("price") or "0").strip()
            try:
                # nosemgrep: python.flask.security.injection.nan-injection.nan-injection
                price = float(raw_price)  # đã kiểm tra isfinite và >= 0 bên dưới
            except ValueError:
                price = -1.0
            if not math.isfinite(price) or price < 0:
                flash("Học phí phải là số không âm.", "error")
                return redirect(url_for("instructor.course_edit", course_id=course.id))
            if not title:
                flash("Tên khoá học là bắt buộc.", "error")
            else:
                course.title = title
                course.description = (request.form.get("description") or "").strip() or None
                course.category_id = request.form.get("category_id", type=int)
                course.price = price
                status = request.form.get("status")
                if status in {COURSE_DRAFT, COURSE_PUBLISHED, COURSE_HIDDEN}:
                    course.status = status
                course.leaderboard_public = request.form.get("leaderboard_public") == "1"
                sess.flush()
                flash("Đã lưu thay đổi.", "success")
                return redirect(url_for("instructor.course_edit", course_id=course.id))

    return render_template("instructor/course_form.html", course=course, categories=categories)


@bp.get("/courses/<course_id>/curriculum")
@instructor_required
def course_curriculum(course_id: str) -> str:
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        course = my_course(sess, actor, course_id)
        chapters = sess.scalars(
            select(Chapter).where(Chapter.course_id == course_id).order_by(Chapter.position, Chapter.id)
        ).all()
        blocks = []
        for chapter in chapters:
            lessons = sess.scalars(
                select(Lesson)
                .options(selectinload(Lesson.attachments))
                .where(Lesson.chapter_id == chapter.id)
                .order_by(Lesson.position, Lesson.id)
            ).all()
            blocks.append({"chapter": chapter, "lessons": lessons})

    return render_template("instructor/curriculum.html", course=course, blocks=blocks)


@bp.post("/courses/<course_id>/chapters")
@instructor_required
def chapter_create(course_id: str) -> Response:
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        my_course(sess, actor, course_id)
        title = (request.form.get("title") or "").strip()
        if not title:
            flash("Tên chương là bắt buộc.", "error")
        else:
            position = (
                sess.scalar(select(func.count()).select_from(Chapter).where(Chapter.course_id == course_id)) or 0
            ) + 1
            sess.add(Chapter(course_id=course_id, title=title, position=position))
            flash("Đã thêm chương.", "success")

    return redirect(url_for("instructor.course_curriculum", course_id=course_id))


@bp.post("/chapters/<int:chapter_id>/lessons")
@instructor_required
def lesson_create(chapter_id: int) -> Response:
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        chapter = sess.get(Chapter, chapter_id)
        if chapter is None:
            abort(404)
        my_course(sess, actor, chapter.course_id)

        title = (request.form.get("title") or "").strip()
        if not title:
            flash("Tên bài học là bắt buộc.", "error")
        else:
            position = (
                sess.scalar(select(func.count()).select_from(Lesson).where(Lesson.chapter_id == chapter_id)) or 0
            ) + 1
            sess.add(
                Lesson(
                    chapter_id=chapter_id,
                    title=title,
                    kind=request.form.get("kind") or "text",
                    content=(request.form.get("content") or "").strip() or None,
                    media_url=(request.form.get("media_url") or "").strip() or None,
                    duration_min=request.form.get("duration_min", type=int) or 0,
                    position=position,
                    is_free_preview=request.form.get("is_free_preview") == "1",
                )
            )
            flash("Đã thêm bài học.", "success")
            course_id = chapter.course_id
            return redirect(url_for("instructor.course_curriculum", course_id=course_id))

        course_id = chapter.course_id

    return redirect(url_for("instructor.course_curriculum", course_id=course_id))


@bp.post("/lessons/<int:lesson_id>/delete")
@instructor_required
def lesson_delete(lesson_id: int) -> Response:
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        lesson = sess.get(Lesson, lesson_id)
        if lesson is None:
            abort(404)
        chapter = sess.get(Chapter, lesson.chapter_id)
        if chapter is None:
            abort(404)
        my_course(sess, actor, chapter.course_id)
        course_id = chapter.course_id
        sess.delete(lesson)
        flash("Đã xoá bài học.", "success")

    return redirect(url_for("instructor.course_curriculum", course_id=course_id))


@bp.get("/courses/<course_id>/students")
@instructor_required
def course_students_view(course_id: str) -> str:
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        course = my_course(sess, actor, course_id)
        rows = course_students(sess, course_id)

    return render_template("instructor/students.html", course=course, rows=rows)


@bp.get("/courses/<course_id>/reports")
@instructor_required
def course_reports(course_id: str) -> str:
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        course = my_course(sess, actor, course_id)
        rows = course_students(sess, course_id)
        total = len(rows)
        completed = sum(1 for row in rows if row["total"] and row["percent"] == 100)
        avg_percent = round(sum(row["percent"] for row in rows) / total) if total else 0

        quiz_scores = []
        for quiz in sess.scalars(select(Quiz).where(Quiz.course_id == course_id)).all():
            attempts = sess.scalars(
                select(QuizAttempt).where(
                    QuizAttempt.quiz_id == quiz.id,
                    QuizAttempt.status == "SUBMITTED",
                )
            ).all()
            if attempts:
                quiz_scores.append(
                    {
                        "quiz": quiz,
                        "attempts": len(attempts),
                        "average": round(sum(a.score for a in attempts) / len(attempts), 2),
                        "pass_rate": round(sum(1 for a in attempts if a.passed) * 100 / len(attempts)),
                    }
                )

    return render_template(
        "instructor/reports.html",
        course=course,
        rows=rows,
        total=total,
        completed=completed,
        avg_percent=avg_percent,
        quiz_scores=quiz_scores,
    )


# ---------------------------------------------------------------------------
# Quiz
# ---------------------------------------------------------------------------


@bp.get("/quizzes")
@instructor_required
def quizzes() -> str:
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        course_ids = list(sess.scalars(select(Course.id).where(Course.instructor_id == actor["id"])).all())
        rows = []
        if course_ids:
            for quiz in sess.scalars(select(Quiz).where(Quiz.course_id.in_(course_ids)).order_by(Quiz.id)).all():
                count = (
                    sess.scalar(select(func.count()).select_from(QuizQuestion).where(QuizQuestion.quiz_id == quiz.id))
                    or 0
                )
                attempts = (
                    sess.scalar(
                        select(func.count())
                        .select_from(QuizAttempt)
                        .where(
                            QuizAttempt.quiz_id == quiz.id,
                            QuizAttempt.status == "SUBMITTED",
                        )
                    )
                    or 0
                )
                rows.append(
                    {
                        "quiz": quiz,
                        "course": sess.get(Course, quiz.course_id),
                        "questions": count,
                        "attempts": attempts,
                    }
                )

    return render_template("instructor/quizzes.html", rows=rows)


@bp.route("/courses/<course_id>/quizzes/new", methods=["GET", "POST"])
@instructor_required
def quiz_new(course_id: str) -> str | Response:
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        course = my_course(sess, actor, course_id)

        if request.method == "POST":
            title = (request.form.get("title") or "").strip()
            if not title:
                flash("Tên bài kiểm tra là bắt buộc.", "error")
            else:
                quiz = Quiz(
                    course_id=course_id,
                    title=title,
                    description=(request.form.get("description") or "").strip() or None,
                    time_limit_min=request.form.get("time_limit_min", type=int) or 0,
                    pass_score=float(request.form.get("pass_score") or 5),
                    max_attempts=request.form.get("max_attempts", type=int) or 0,
                    show_answers=request.form.get("show_answers") == "1",
                    status=COURSE_PUBLISHED,
                )
                sess.add(quiz)
                sess.flush()
                flash("Đã tạo bài kiểm tra.", "success")
                return redirect(url_for("instructor.quiz_questions", quiz_id=quiz.id))

    return render_template("instructor/quiz_form.html", course=course, quiz=None)


@bp.route("/quizzes/<int:quiz_id>/questions", methods=["GET", "POST"])
@instructor_required
def quiz_questions(quiz_id: int) -> str | Response:
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        quiz = my_quiz(sess, actor, quiz_id)
        course = sess.get(Course, quiz.course_id)

        if request.method == "POST":
            prompt = (request.form.get("prompt") or "").strip()
            options = [(request.form.get(f"option_{i}") or "").strip() for i in range(4)]
            options = [opt for opt in options if opt]
            correct = request.form.get("correct", type=int) or 0
            if not prompt or len(options) < 2:
                flash("Cần nội dung câu hỏi và ít nhất 2 lựa chọn.", "error")
            else:
                question = Question(
                    course_id=quiz.course_id,
                    created_by=actor["id"],
                    kind="MCQ",
                    prompt=prompt,
                    options=options,
                    answer={"index": min(correct, len(options) - 1)},
                    points=float(request.form.get("points") or 1),
                )
                sess.add(question)
                sess.flush()
                position = (
                    sess.scalar(select(func.count()).select_from(QuizQuestion).where(QuizQuestion.quiz_id == quiz_id))
                    or 0
                ) + 1
                sess.add(
                    QuizQuestion(
                        quiz_id=quiz_id,
                        question_id=question.id,
                        position=position,
                    )
                )
                flash("Đã thêm câu hỏi.", "success")
                return redirect(url_for("instructor.quiz_questions", quiz_id=quiz_id))

        questions = sess.scalars(
            select(Question)
            .join(QuizQuestion, QuizQuestion.question_id == Question.id)
            .where(QuizQuestion.quiz_id == quiz_id)
            .order_by(QuizQuestion.position, Question.id)
        ).all()

    return render_template(
        "instructor/quiz_questions.html",
        quiz=quiz,
        course=course,
        questions=questions,
    )


@bp.post("/questions/<int:question_id>/delete")
@instructor_required
def question_delete(question_id: int) -> Response:
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        question = sess.get(Question, question_id)
        if question is None:
            abort(404)
        links = sess.scalars(select(QuizQuestion).where(QuizQuestion.question_id == question_id)).all()
        quiz_ids = [link.quiz_id for link in links]
        for link in links:
            sess.delete(link)
        sess.flush()
        sess.delete(question)
        flash("Đã xoá câu hỏi.", "success")

    target = quiz_ids[0] if quiz_ids else None
    if target:
        return redirect(url_for("instructor.quiz_questions", quiz_id=target))
    return redirect(url_for("instructor.quizzes"))


# ---------------------------------------------------------------------------
# Bài tập
# ---------------------------------------------------------------------------


@bp.get("/assignments")
@instructor_required
def assignments() -> str:
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        course_ids = list(sess.scalars(select(Course.id).where(Course.instructor_id == actor["id"])).all())
        rows = []
        if course_ids:
            for assignment in sess.scalars(
                select(Assignment).where(Assignment.course_id.in_(course_ids)).order_by(Assignment.id)
            ).all():
                submitted = (
                    sess.scalar(
                        select(func.count()).select_from(Submission).where(Submission.assignment_id == assignment.id)
                    )
                    or 0
                )
                rows.append(
                    {
                        "assignment": assignment,
                        "course": sess.get(Course, assignment.course_id),
                        "submitted": submitted,
                    }
                )

    return render_template("instructor/assignments.html", rows=rows)


@bp.post("/courses/<course_id>/assignments")
@instructor_required
def assignment_create(course_id: str) -> Response:
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        my_course(sess, actor, course_id)
        title = (request.form.get("title") or "").strip()
        if not title:
            flash("Tên bài tập là bắt buộc.", "error")
        else:
            sess.add(
                Assignment(
                    course_id=course_id,
                    title=title,
                    description=(request.form.get("description") or "").strip() or None,
                    due_at=parse_dt(request.form.get("due_at", "")),
                    max_score=float(request.form.get("max_score") or 10),
                )
            )
            flash("Đã tạo bài tập.", "success")

    return redirect(url_for("instructor.assignments"))


# ---------------------------------------------------------------------------
# Bảng điểm
# ---------------------------------------------------------------------------


@bp.get("/grades")
@instructor_required
def grades() -> str:
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        taught = sess.scalars(select(Course).where(Course.instructor_id == actor["id"])).all()
        rows = []
        for course in taught:
            students = course_students(sess, course.id)
            quiz_data = []
            for quiz in sess.scalars(select(Quiz).where(Quiz.course_id == course.id)).all():
                attempts = sess.scalars(
                    select(QuizAttempt).where(
                        QuizAttempt.quiz_id == quiz.id,
                        QuizAttempt.status == "SUBMITTED",
                    )
                ).all()
                if attempts:
                    quiz_data.append(
                        {
                            "quiz": quiz,
                            "average": round(sum(a.score for a in attempts) / len(attempts), 2),
                        }
                    )
            rows.append({"course": course, "students": students, "quizzes": quiz_data})

    return render_template("instructor/grades.html", rows=rows)


# ---------------------------------------------------------------------------
# Chứng chỉ
# ---------------------------------------------------------------------------


@bp.get("/certificates")
@instructor_required
def certificates() -> str:
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        taught = sess.scalars(select(Course).where(Course.instructor_id == actor["id"])).all()
        rows = []
        for course in taught:
            issued = sess.execute(
                select(Certificate, User)
                .join(User, Certificate.user_id == User.id)
                .where(Certificate.course_id == course.id)
                .order_by(Certificate.issued_at.desc())
            ).all()
            students = course_students(sess, course.id)
            rows.append(
                {
                    "course": course,
                    "issued": [{"certificate": c, "student": u} for c, u in issued],
                    "students": students,
                }
            )

    return render_template("instructor/certificates.html", rows=rows)


@bp.post("/certificates/<int:certificate_id>/revoke")
@instructor_required
def certificate_revoke(certificate_id: int) -> Response:
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        certificate = sess.get(Certificate, certificate_id)
        if certificate is None:
            abort(404)
        my_course(sess, actor, certificate.course_id)
        sess.delete(certificate)
        flash("Đã thu hồi chứng chỉ.", "success")

    return redirect(url_for("instructor.certificates"))


@bp.post("/courses/<course_id>/certificates/issue")
@instructor_required
def certificate_issue(course_id: str) -> Response:
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        course = my_course(sess, actor, course_id)
        student_id = (request.form.get("student_id") or "").strip()
        student = sess.get(User, student_id)
        final_score = _parse_number(request.form.get("final_score"), 8.0, upper=10.0)
        enrolled = (
            sess.scalars(
                select(Enrollment.id).where(
                    Enrollment.course_id == course_id,
                    Enrollment.student_id == student_id,
                    Enrollment.status == "ACTIVE",
                )
            ).first()
            if student is not None
            else None
        )
        if student is None or enrolled is None:
            flash("Không tìm thấy học viên đã ghi danh khoá này.", "error")
        elif final_score is None:
            flash("Điểm tổng kết phải nằm trong khoảng 0–10.", "error")
        else:
            existing = sess.scalars(
                select(Certificate).where(
                    Certificate.course_id == course_id,
                    Certificate.user_id == student_id,
                )
            ).first()
            if existing is not None:
                flash("Học viên đã có chứng chỉ khoá này.", "error")
            else:
                sess.add(
                    Certificate(
                        code=f"CERT-{course.id.upper()}-{student_id.upper()}-{int(utcnow().timestamp())}",
                        user_id=student_id,
                        course_id=course_id,
                        final_score=final_score,
                    )
                )
                flash("Đã cấp chứng chỉ.", "success")

    return redirect(url_for("instructor.certificates"))


# ---------------------------------------------------------------------------
# Diễn đàn
# ---------------------------------------------------------------------------


@bp.get("/forum")
@instructor_required
def forum() -> str:
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        taught = sess.scalars(select(Course).where(Course.instructor_id == actor["id"])).all()
        rows = []
        for course in taught:
            topics = sess.execute(
                select(ForumTopic, User.email, func.count(ForumPost.id))
                .join(User, ForumTopic.author_id == User.id)
                .outerjoin(ForumPost, ForumPost.topic_id == ForumTopic.id)
                .where(ForumTopic.course_id == course.id)
                .group_by(ForumTopic.id, User.email)
                .order_by(ForumTopic.pinned.desc(), ForumTopic.created_at.desc())
            ).all()
            rows.append(
                {
                    "course": course,
                    "topics": [{"topic": t, "author": email, "replies": count} for t, email, count in topics],
                }
            )

    return render_template("instructor/forum.html", rows=rows)


@bp.post("/forum/<int:topic_id>/moderate")
@instructor_required
def forum_moderate(topic_id: int) -> Response:
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        topic = sess.get(ForumTopic, topic_id)
        if topic is None:
            abort(404)
        my_course(sess, actor, topic.course_id)
        action = request.form.get("action", "")
        if action == "pin":
            topic.pinned = not topic.pinned
        elif action == "lock":
            topic.locked = not topic.locked
        elif action == "delete":
            for post in sess.scalars(select(ForumPost).where(ForumPost.topic_id == topic_id)).all():
                sess.delete(post)
            sess.flush()
            sess.delete(topic)
            flash("Đã xoá chủ đề.", "success")
            return redirect(url_for("instructor.forum"))
        sess.flush()
        flash("Đã cập nhật chủ đề.", "success")

    return redirect(url_for("instructor.forum"))


# ---------------------------------------------------------------------------
# Live session
# ---------------------------------------------------------------------------


@bp.get("/live")
@instructor_required
def live() -> str:
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        taught = sess.scalars(select(Course).where(Course.instructor_id == actor["id"])).all()
        rows = []
        for course in taught:
            sessions = sess.scalars(
                select(LiveSession).where(LiveSession.course_id == course.id).order_by(LiveSession.start_at)
            ).all()
            rows.append({"course": course, "sessions": sessions})

    return render_template("instructor/live.html", rows=rows)


@bp.post("/courses/<course_id>/live")
@instructor_required
def live_create(course_id: str) -> Response:
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        my_course(sess, actor, course_id)
        title = (request.form.get("title") or "").strip()
        url = (request.form.get("meeting_url") or "").strip()
        if not title or not url:
            flash("Tiêu đề và link phòng học là bắt buộc.", "error")
        else:
            sess.add(
                LiveSession(
                    course_id=course_id,
                    title=title,
                    meeting_url=url,
                    start_at=parse_dt(request.form.get("start_at", "")),
                    created_by=actor["id"],
                )
            )
            flash("Đã tạo buổi học trực tuyến.", "success")

    return redirect(url_for("instructor.live"))


@bp.post("/live/<int:session_id>/delete")
@instructor_required
def live_delete(session_id: int) -> Response:
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        row = sess.get(LiveSession, session_id)
        if row is None:
            abort(404)
        my_course(sess, actor, row.course_id)
        sess.delete(row)
        flash("Đã xoá buổi học.", "success")

    return redirect(url_for("instructor.live"))


# ---------------------------------------------------------------------------
# Messages - Hộp thư nhắn tin với SV
# ---------------------------------------------------------------------------


@bp.get("/messages")
@instructor_required
def messages_index() -> str:
    """Danh sách hội thoại với SV trong các khóa của GV."""
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        taught = sess.scalars(select(Course).where(Course.instructor_id == actor["id"])).all()

        conversations = []
        for course in taught:
            students = sess.execute(
                select(Enrollment, User)
                .join(User, Enrollment.student_id == User.id)
                .where(Enrollment.course_id == course.id)
            ).all()

            for _enrollment, student in students:
                last_msg = sess.scalars(
                    select(DirectMessage)
                    .where(
                        or_(
                            and_(
                                DirectMessage.sender_id == actor["id"],
                                DirectMessage.recipient_id == student.id,
                            ),
                            and_(
                                DirectMessage.sender_id == student.id,
                                DirectMessage.recipient_id == actor["id"],
                            ),
                        )
                    )
                    .order_by(DirectMessage.created_at.desc())
                ).first()

                unread = (
                    sess.scalar(
                        select(func.count())
                        .select_from(DirectMessage)
                        .where(
                            DirectMessage.recipient_id == actor["id"],
                            DirectMessage.sender_id == student.id,
                            DirectMessage.read_at.is_(None),
                        )
                    )
                    or 0
                )

                conversations.append(
                    {
                        "course": course,
                        "student": student,
                        "last_message": last_msg,
                        "unread": unread,
                    }
                )

    return render_template("instructor/messages_index.html", conversations=conversations)


@bp.get("/messages/<student_id>")
@instructor_required
def messages_conversation(student_id: str) -> str:
    """Hội thoại với một SV cụ thể."""
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        student = sess.get(User, student_id)
        if not student or student.role != ROLE_STUDENT:
            abort(404)

        # Check if student enrolled in at least one of instructor's courses
        common = sess.scalars(
            select(Enrollment).where(
                Enrollment.student_id == student_id,
                Enrollment.course_id.in_(select(Course.id).where(Course.instructor_id == actor["id"])),
            )
        ).first()
        if not common:
            abort(403)

        # Mark as read
        unread_msgs = sess.scalars(
            select(DirectMessage).where(
                DirectMessage.sender_id == student_id,
                DirectMessage.recipient_id == actor["id"],
                DirectMessage.read_at.is_(None),
            )
        ).all()
        for msg in unread_msgs:
            msg.read_at = utcnow()

        messages = sess.execute(
            select(DirectMessage, User)
            .join(User, DirectMessage.sender_id == User.id)
            .where(
                or_(
                    and_(
                        DirectMessage.sender_id == actor["id"],
                        DirectMessage.recipient_id == student_id,
                    ),
                    and_(
                        DirectMessage.sender_id == student_id,
                        DirectMessage.recipient_id == actor["id"],
                    ),
                )
            )
            .order_by(DirectMessage.created_at)
        ).all()

    return render_template("instructor/messages_conversation.html", student=student, messages=messages)


@bp.post("/messages/<student_id>/send")
@instructor_required
def messages_send(student_id: str) -> Response:
    """Gửi tin nhắn cho SV."""
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        student = sess.get(User, student_id)
        if not student or student.role != ROLE_STUDENT:
            abort(404)

        common = sess.scalars(
            select(Enrollment).where(
                Enrollment.student_id == student_id,
                Enrollment.course_id.in_(select(Course.id).where(Course.instructor_id == actor["id"])),
            )
        ).first()
        if not common:
            abort(403)

        content_text = (request.form.get("content") or "").strip()
        if content_text:
            msg = DirectMessage(
                sender_id=actor["id"],
                recipient_id=student_id,
                body=content_text,
            )
            sess.add(msg)
            flash("Đã gửi.", "success")
        else:
            flash("Nội dung không được rỗng.", "error")

    return redirect(url_for("instructor.messages_conversation", student_id=student_id))


# ---------------------------------------------------------------------------
# Profile - Hồ sơ giảng viên
# ---------------------------------------------------------------------------


@bp.get("/profile")
@instructor_required
def profile() -> str:
    """Xem hồ sơ giảng viên."""
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        user = sess.get(User, actor["id"])
        taught = sess.execute(
            select(Course, func.count(Enrollment.id))
            .outerjoin(Enrollment, Enrollment.course_id == Course.id)
            .where(Course.instructor_id == actor["id"])
            .group_by(Course.id)
        ).all()

    return render_template("instructor/profile.html", user=user, taught=taught)


@bp.route("/profile/edit", methods=["GET", "POST"])
@instructor_required
def profile_edit() -> str | Response:
    """Chỉnh sửa hồ sơ."""
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        user = sess.get(User, actor["id"])
        if not user:
            abort(404)

        if request.method == "POST":
            full_name = (request.form.get("full_name") or "").strip()
            bio = (request.form.get("bio") or "").strip()
            if full_name:
                user.full_name = full_name
            user.bio = bio
            sess.flush()
            flash("Đã cập nhật hồ sơ.", "success")
            return redirect(url_for("instructor.profile"))

    return render_template("instructor/profile_edit.html", user=user)


@bp.route("/profile/password", methods=["GET", "POST"])
@instructor_required
def profile_password() -> str | Response:
    """Đổi mật khẩu."""
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        user = sess.get(User, actor["id"])
        if not user:
            abort(404)

        if request.method == "POST":
            old_pw = request.form.get("old_password") or ""
            new_pw = request.form.get("new_password") or ""
            confirm_pw = request.form.get("confirm_password") or ""

            if not verify_password(old_pw, user.password_hash):
                flash("Mật khẩu cũ không đúng.", "error")
            elif new_pw != confirm_pw:
                flash("Mật khẩu mới không khớp.", "error")
            elif len(new_pw) < 8:
                flash("Mật khẩu tối thiểu 8 ký tự.", "error")
            else:
                user.password_hash = hash_password(new_pw)
                flash("Đã đổi mật khẩu.", "success")
                return redirect(url_for("instructor.profile"))

    return render_template("instructor/profile_password.html", user=user)


# ---------------------------------------------------------------------------
# Reports Export
# ---------------------------------------------------------------------------


@bp.get("/courses/<course_id>/reports/export")
@instructor_required
def course_reports_export(course_id: str) -> Response:
    """Export báo cáo khóa học CSV."""
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        my_course(sess, actor, course_id)
        course = sess.get(Course, course_id)
        if not course:
            abort(404)

        enrollments = sess.execute(
            select(Enrollment, User)
            .join(User, Enrollment.student_id == User.id)
            .where(Enrollment.course_id == course_id)
        ).all()

        # Get lesson progress for each student
        total_lessons = (
            sess.scalar(
                select(func.count())
                .select_from(Lesson)
                .join(Chapter, Lesson.chapter_id == Chapter.id)
                .where(Chapter.course_id == course_id)
            )
            or 0
        )

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "Học viên",
                "Email",
                "Tiến độ (%)",
                "Bài hoàn thành",
                "Tổng bài",
                "Trạng thái",
                "Điểm TB Quiz",
                "Chứng chỉ",
            ]
        )

        for enrollment, student in enrollments:
            done = (
                sess.scalar(
                    select(func.count())
                    .select_from(LessonProgress)
                    .join(Lesson, LessonProgress.lesson_id == Lesson.id)
                    .join(Chapter, Lesson.chapter_id == Chapter.id)
                    .where(
                        Chapter.course_id == course_id,
                        LessonProgress.student_id == student.id,
                    )
                )
                or 0
            )

            percent = round(done * 100 / total_lessons) if total_lessons else 0

            # Quiz average
            quiz_avg = sess.scalar(
                select(func.avg(QuizAttempt.score))
                .join(Quiz, QuizAttempt.quiz_id == Quiz.id)
                .where(
                    Quiz.course_id == course_id,
                    QuizAttempt.student_id == student.id,
                    QuizAttempt.status == "SUBMITTED",
                )
            )

            cert = sess.scalar(
                select(Certificate).where(
                    Certificate.course_id == course_id,
                    Certificate.user_id == student.id,
                )
            )

            writer.writerow(
                [
                    student.display_name,
                    student.email,
                    f"{percent}%",
                    done,
                    total_lessons,
                    enrollment.status,
                    f"{quiz_avg:.1f}" if quiz_avg else "—",
                    "Có" if cert else "Không",
                ]
            )

        output.seek(0)
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment; filename=report_{course_id}.csv"},
        )


@bp.get("/reports/export")
@instructor_required
def reports_export() -> Response:
    """Export báo cáo tổng hợp CSV."""
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        taught = sess.scalars(select(Course).where(Course.instructor_id == actor["id"])).all()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "Khóa học",
                "Học viên",
                "Email",
                "Tiến độ (%)",
                "Bài hoàn thành",
                "Tổng bài",
                "Trạng thái",
                "Điểm TB Quiz",
            ]
        )

        for course in taught:
            enrollments = sess.execute(
                select(Enrollment, User)
                .join(User, Enrollment.student_id == User.id)
                .where(Enrollment.course_id == course.id)
            ).all()

            total_lessons = (
                sess.scalar(
                    select(func.count())
                    .select_from(Lesson)
                    .join(Chapter, Lesson.chapter_id == Chapter.id)
                    .where(Chapter.course_id == course.id)
                )
                or 0
            )

            for enrollment, student in enrollments:
                done = (
                    sess.scalar(
                        select(func.count())
                        .select_from(LessonProgress)
                        .join(Lesson, LessonProgress.lesson_id == Lesson.id)
                        .join(Chapter, Lesson.chapter_id == Chapter.id)
                        .where(
                            Chapter.course_id == course.id,
                            LessonProgress.student_id == student.id,
                        )
                    )
                    or 0
                )

                percent = round(done * 100 / total_lessons) if total_lessons else 0

                quiz_avg = sess.scalar(
                    select(func.avg(QuizAttempt.score))
                    .join(Quiz, QuizAttempt.quiz_id == Quiz.id)
                    .where(
                        Quiz.course_id == course.id,
                        QuizAttempt.student_id == student.id,
                        QuizAttempt.status == "SUBMITTED",
                    )
                )

                writer.writerow(
                    [
                        course.title,
                        student.display_name,
                        student.email,
                        f"{percent}%",
                        done,
                        total_lessons,
                        enrollment.status,
                        f"{quiz_avg:.1f}" if quiz_avg else "—",
                    ]
                )

        output.seek(0)
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=instructor_report.csv"},
        )


# ---------------------------------------------------------------------------
# Thông báo lớp học (spec mục 6 — GV phát thông báo tới toàn bộ lớp)
# ---------------------------------------------------------------------------


@bp.get("/notifications")
@instructor_required
def notifications() -> str:
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        taught = sess.scalars(select(Course).where(Course.instructor_id == actor["id"]).order_by(Course.title)).all()
        recent = sess.execute(
            select(Notification, User)
            .join(User, Notification.user_id == User.id)
            .where(Notification.sender_id == actor["id"])
            .order_by(Notification.created_at.desc())
            .limit(50)
        ).all()

    return render_template("instructor/notifications.html", taught=taught, recent=recent)


@bp.post("/notifications")
@instructor_required
def notification_send() -> Response:
    actor = current_user()
    assert actor is not None

    course_id = (request.form.get("course_id") or "").strip()
    title = (request.form.get("title") or "").strip()
    body = (request.form.get("body") or "").strip()
    if not course_id or not title or not body:
        flash("Cần chọn khoá học, tiêu đề và nội dung.", "error")
        return redirect(url_for("instructor.notifications"))

    with get_db().session() as sess:
        course = my_course(sess, actor, course_id)
        recipients = (
            sess.execute(
                select(User)
                .join(Enrollment, Enrollment.student_id == User.id)
                .where(
                    Enrollment.course_id == course.id,
                    Enrollment.status == ENROLL_ACTIVE,
                )
            )
            .scalars()
            .all()
        )
        if not recipients:
            flash("Khoá học chưa có sinh viên đang học.", "error")
            return redirect(url_for("instructor.notifications"))

        link = url_for("student.notifications")
        for student in recipients:
            sess.add(
                Notification(
                    user_id=student.id,
                    sender_id=actor["id"],
                    course_id=course.id,
                    kind="COURSE",
                    title=title[:200],
                    body=body,
                    link=link,
                )
            )
        sess.flush()
        emails = [(s.email, s.display_name) for s in recipients]

    for email, _name in emails:
        send_notification(email, title, body, link)
    audit_record(
        "NOTIFICATION_SENT",
        f"course:{course_id}",
        actor_id=actor["id"],
        recipients=len(emails),
    )
    flash(f"Đã gửi thông báo tới {len(emails)} sinh viên (kèm email).", "success")
    return redirect(url_for("instructor.notifications"))


# ---------------------------------------------------------------------------
# Quản lý danh sách lớp (spec mục 3 — GV bổ sung SV)
# ---------------------------------------------------------------------------


@bp.post("/courses/<course_id>/students/add")
@instructor_required
def student_add(course_id: str) -> Response:
    actor = current_user()
    assert actor is not None
    email = (request.form.get("email") or "").strip().lower()

    with get_db().session() as sess:
        course = my_course(sess, actor, course_id)
        student = sess.scalars(select(User).where(func.lower(User.email) == email)).first()
        if student is None:
            flash("Không tìm thấy tài khoản với email này.", "error")
        elif student.role != ROLE_STUDENT:
            flash("Tài khoản này không phải sinh viên.", "error")
        else:
            existing = sess.scalars(
                select(Enrollment).where(
                    Enrollment.course_id == course.id,
                    Enrollment.student_id == student.id,
                )
            ).first()
            if existing is not None:
                flash("Sinh viên đã có trong lớp.", "info")
            else:
                sess.add(
                    Enrollment(
                        course_id=course.id,
                        student_id=student.id,
                        status=ENROLL_ACTIVE,
                    )
                )
                sess.flush()
                audit_record(
                    "ENROLLMENT_ADDED",
                    f"course:{course.id}/student:{student.id}",
                    actor_id=actor["id"],
                )
                flash(f"Đã thêm {student.display_name} vào lớp.", "success")

    return redirect(url_for("instructor.students", course_id=course_id))


@bp.post("/courses/<course_id>/students/<student_id>/remove")
@instructor_required
def student_remove(course_id: str, student_id: str) -> Response:
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        my_course(sess, actor, course_id)
        enrollment = sess.scalars(
            select(Enrollment).where(
                Enrollment.course_id == course_id,
                Enrollment.student_id == student_id,
            )
        ).first()
        if enrollment is None:
            flash("Sinh viên không có trong lớp.", "error")
        else:
            sess.delete(enrollment)
            sess.flush()
            audit_record(
                "ENROLLMENT_REMOVED",
                f"course:{course_id}/student:{student_id}",
                actor_id=actor["id"],
            )
            flash("Đã xoá sinh viên khỏi lớp.", "success")

    return redirect(url_for("instructor.students", course_id=course_id))
