"""Blueprint sinh viên — spec mục 2.

Route: /my-courses, /my-courses/:courseId/learn,
       /my-courses/:courseId/learn/:lessonId, /grades, /progress,
       /certificates, /leaderboard, /settings
"""

from __future__ import annotations

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
from web.auth import current_user, student_required
from web.database import get_db
from web.models import (
    COURSE_PUBLISHED,
    ENROLL_ACTIVE,
    ROLE_INSTRUCTOR,
    ROLE_STUDENT,
    Assignment,
    Certificate,
    Chapter,
    Course,
    DirectMessage,
    Enrollment,
    ForumPost,
    ForumTopic,
    Lesson,
    LessonProgress,
    Notification,
    Quiz,
    QuizAttempt,
    Submission,
    User,
    utcnow,
)

bp = Blueprint("student", __name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def my_enrollments(sess: Session, student_id: str) -> list[dict[str, Any]]:
    """Khoá đã ghi danh, kèm tiến độ %."""
    rows = sess.execute(
        select(Enrollment, Course)
        .join(Course, Enrollment.course_id == Course.id)
        .where(
            Enrollment.student_id == student_id,
            Enrollment.status == ENROLL_ACTIVE,
        )
        .order_by(Course.title)
    ).all()

    out: list[dict[str, Any]] = []
    for enrollment, course in rows:
        total = lesson_count(sess, course.id)
        done = completed_count(sess, student_id, course.id)
        out.append(
            {
                "enrollment": enrollment,
                "course": course,
                "instructor": sess.get(User, course.instructor_id),
                "total": total,
                "done": done,
                "percent": round(done * 100 / total) if total else 0,
            }
        )
    return out


def lesson_count(sess: Session, course_id: str) -> int:
    return (
        sess.scalar(
            select(func.count())
            .select_from(Lesson)
            .join(Chapter, Lesson.chapter_id == Chapter.id)
            .where(Chapter.course_id == course_id)
        )
        or 0
    )


def completed_count(sess: Session, student_id: str, course_id: str) -> int:
    return (
        sess.scalar(
            select(func.count())
            .select_from(LessonProgress)
            .join(Lesson, LessonProgress.lesson_id == Lesson.id)
            .join(Chapter, Lesson.chapter_id == Chapter.id)
            .where(
                Chapter.course_id == course_id,
                LessonProgress.student_id == student_id,
            )
        )
        or 0
    )


def completed_lesson_ids(sess: Session, student_id: str, course_id: str) -> set[int]:
    rows = sess.scalars(
        select(LessonProgress.lesson_id)
        .join(Lesson, LessonProgress.lesson_id == Lesson.id)
        .join(Chapter, Lesson.chapter_id == Chapter.id)
        .where(
            Chapter.course_id == course_id,
            LessonProgress.student_id == student_id,
        )
    ).all()
    return set(rows)


def require_enrollment(sess: Session, actor: dict[str, Any], course_id: str) -> Enrollment:
    """Spec dòng 148: SV chỉ vào /learn khi có enrollment active."""
    enrollment = sess.scalars(
        select(Enrollment).where(
            Enrollment.course_id == course_id,
            Enrollment.student_id == actor["id"],
            Enrollment.status == ENROLL_ACTIVE,
        )
    ).first()
    if enrollment is None:
        abort(403)
    return enrollment


def course_curriculum(sess: Session, course_id: str) -> list[dict[str, Any]]:
    chapters = sess.scalars(
        select(Chapter).where(Chapter.course_id == course_id).order_by(Chapter.position, Chapter.id)
    ).all()
    out = []
    for chapter in chapters:
        lessons = sess.scalars(
            select(Lesson)
            .options(selectinload(Lesson.attachments))
            .where(Lesson.chapter_id == chapter.id)
            .order_by(Lesson.position, Lesson.id)
        ).all()
        out.append({"chapter": chapter, "lessons": lessons})
    return out


# ---------------------------------------------------------------------------
# /my-courses
# ---------------------------------------------------------------------------


@bp.get("/my-courses")
@student_required
def my_courses() -> str:
    actor = current_user()
    assert actor is not None
    with get_db().session() as sess:
        rows = my_enrollments(sess, actor["id"])
    return render_template("student/my_courses.html", rows=rows)


@bp.post("/enroll")
@student_required
def enroll_by_code() -> Response:
    """Ghi danh bằng mã khoá học (spec mục 3)."""
    actor = current_user()
    assert actor is not None
    code = (request.form.get("code") or "").strip()

    if not code:
        flash("Vui lòng nhập mã ghi danh.", "error")
        return redirect(url_for("student.my_courses"))

    with get_db().session() as sess:
        course = sess.scalars(
            select(Course).where(
                func.upper(Course.enroll_code) == code.upper(),
                Course.status == COURSE_PUBLISHED,
            )
        ).first()
        if course is None:
            flash("Mã ghi danh không đúng hoặc khoá chưa mở.", "error")
            return redirect(url_for("student.my_courses"))

        existing = sess.scalars(
            select(Enrollment).where(
                Enrollment.course_id == course.id,
                Enrollment.student_id == actor["id"],
            )
        ).first()
        if existing is not None:
            flash("Bạn đã ghi danh khoá này rồi.", "info")
            return redirect(url_for("student.learn", course_id=course.id))

        sess.add(
            Enrollment(
                course_id=course.id,
                student_id=actor["id"],
                status=ENROLL_ACTIVE,
            )
        )
        sess.flush()
        audit_record(
            "ENROLLMENT_CODE_USED",
            f"course:{course.id}",
            actor_id=actor["id"],
            code=code,
        )
    flash(f"Ghi danh thành công khoá {course.title}.", "success")
    return redirect(url_for("student.learn", course_id=course.id))


# ---------------------------------------------------------------------------
# /my-courses/:courseId/learn
# ---------------------------------------------------------------------------


@bp.get("/my-courses/<course_id>/learn")
@student_required
def learn(course_id: str) -> str:
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        require_enrollment(sess, actor, course_id)
        course = sess.get(Course, course_id)
        if course is None:
            abort(404)
        chapters = course_curriculum(sess, course_id)
        done = completed_lesson_ids(sess, actor["id"], course_id)
        total = lesson_count(sess, course_id)
        quizzes = sess.scalars(select(Quiz).where(Quiz.course_id == course_id, Quiz.status == COURSE_PUBLISHED)).all()
        assignments = sess.scalars(select(Assignment).where(Assignment.course_id == course_id)).all()

        first_lesson = None
        for block in chapters:
            if block["lessons"]:
                first_lesson = block["lessons"][0]
                break

    return render_template(
        "student/learn.html",
        course=course,
        chapters=chapters,
        done=done,
        total=total,
        completed=len(done),
        percent=round(len(done) * 100 / total) if total else 0,
        quizzes=quizzes,
        assignments=assignments,
        first_lesson=first_lesson,
    )


@bp.get("/my-courses/<course_id>/learn/<int:lesson_id>")
@student_required
def learn_lesson(course_id: str, lesson_id: int) -> str:
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        require_enrollment(sess, actor, course_id)
        course = sess.get(Course, course_id)
        lesson = sess.get(Lesson, lesson_id)
        if course is None or lesson is None:
            abort(404)
        chapter = sess.get(Chapter, lesson.chapter_id)
        if chapter is None or chapter.course_id != course_id:
            abort(404)

        chapters = course_curriculum(sess, course_id)
        done = completed_lesson_ids(sess, actor["id"], course_id)
        total = lesson_count(sess, course_id)

        # bài trước / bài sau trong toàn khoá
        flat = [item for block in chapters for item in block["lessons"]]
        ids = [item.id for item in flat]
        index = ids.index(lesson.id)
        lesson = flat[index]  # dùng instance đã eager-load attachments
        prev_lesson = flat[index - 1] if index > 0 else None
        next_lesson = flat[index + 1] if index + 1 < len(flat) else None

    return render_template(
        "student/lesson.html",
        course=course,
        lesson=lesson,
        chapter=chapter,
        chapters=chapters,
        done=done,
        total=total,
        completed=len(done),
        percent=round(len(done) * 100 / total) if total else 0,
        prev_lesson=prev_lesson,
        next_lesson=next_lesson,
    )


@bp.post("/my-courses/<course_id>/learn/<int:lesson_id>/complete")
@student_required
def complete_lesson(course_id: str, lesson_id: int) -> Response:
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        require_enrollment(sess, actor, course_id)
        lesson = sess.get(Lesson, lesson_id)
        if lesson is None:
            abort(404)
        existing = sess.scalars(
            select(LessonProgress.id).where(
                LessonProgress.lesson_id == lesson_id,
                LessonProgress.student_id == actor["id"],
            )
        ).first()
        if existing is None:
            sess.add(LessonProgress(lesson_id=lesson_id, student_id=actor["id"]))
            flash("Đã đánh dấu hoàn thành bài học.", "success")
        else:
            flash("Bài học này đã được đánh dấu hoàn thành.", "info")

    return redirect(url_for("student.learn_lesson", course_id=course_id, lesson_id=lesson_id))


# ---------------------------------------------------------------------------
# /grades — bảng điểm cá nhân
# ---------------------------------------------------------------------------


@bp.get("/grades")
@student_required
def grades() -> str:
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        rows = my_enrollments(sess, actor["id"])
        quiz_rows = []
        for row in rows:
            attempts = sess.scalars(
                select(QuizAttempt)
                .join(Quiz, QuizAttempt.quiz_id == Quiz.id)
                .where(
                    Quiz.course_id == row["course"].id,
                    QuizAttempt.student_id == actor["id"],
                    QuizAttempt.status == "SUBMITTED",
                )
                .order_by(QuizAttempt.submitted_at.desc())
            ).all()
            best = max((a.score for a in attempts), default=None)
            quiz_rows.append(
                {
                    "course": row["course"],
                    "attempts": attempts,
                    "best": best,
                    "passed": any(a.passed for a in attempts),
                }
            )

        submission_rows = sess.execute(
            select(Submission, Assignment)
            .join(Assignment, Submission.assignment_id == Assignment.id)
            .where(Submission.student_id == actor["id"])
            .order_by(Submission.submitted_at.desc())
        ).all()

    return render_template(
        "student/grades.html",
        quiz_rows=quiz_rows,
        submission_rows=[{"submission": s, "assignment": a} for s, a in submission_rows],
    )


# ---------------------------------------------------------------------------
# /progress — biểu đồ tiến độ
# ---------------------------------------------------------------------------


@bp.get("/progress")
@student_required
def progress() -> str:
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        rows = my_enrollments(sess, actor["id"])
        overall_total = sum(row["total"] for row in rows)
        overall_done = sum(row["done"] for row in rows)
        overall_percent = round(overall_done * 100 / overall_total) if overall_total else 0
        study_minutes = (
            sess.scalar(
                select(func.coalesce(func.sum(Lesson.duration_min), 0))
                .select_from(LessonProgress)
                .join(Lesson, LessonProgress.lesson_id == Lesson.id)
                .where(LessonProgress.student_id == actor["id"])
            )
            or 0
        )

    return render_template(
        "student/progress.html",
        rows=rows,
        overall_total=overall_total,
        overall_done=overall_done,
        overall_percent=overall_percent,
        study_minutes=study_minutes,
    )


# ---------------------------------------------------------------------------
# /certificates
# ---------------------------------------------------------------------------


@bp.get("/certificates")
@student_required
def certificates() -> str:
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        rows = sess.execute(
            select(Certificate, Course)
            .join(Course, Certificate.course_id == Course.id)
            .where(Certificate.user_id == actor["id"])
            .order_by(Certificate.issued_at.desc())
        ).all()

    return render_template(
        "student/certificates.html",
        rows=[{"certificate": c, "course": course} for c, course in rows],
    )


@bp.get("/certificates/<code>")
@student_required
def certificate_detail(code: str) -> str:
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        certificate = sess.scalars(select(Certificate).where(Certificate.code == code)).first()
        if certificate is None:
            abort(404)
        if certificate.user_id != actor["id"]:
            abort(403)
        course = sess.get(Course, certificate.course_id)
        holder = sess.get(User, certificate.user_id)
        instructor = sess.get(User, course.instructor_id) if course else None

    return render_template(
        "student/certificate_detail.html",
        certificate=certificate,
        course=course,
        holder=holder,
        instructor=instructor,
    )


# ---------------------------------------------------------------------------
# /leaderboard — spec dòng 46: "nếu công khai"
# ---------------------------------------------------------------------------


@bp.get("/leaderboard")
def leaderboard() -> str:
    actor = current_user()

    with get_db().session() as sess:
        if actor is not None and actor["role"] == ROLE_STUDENT:
            rows = my_enrollments(sess, actor["id"])
            courses = [row["course"] for row in rows]
        else:
            courses = list(
                sess.scalars(
                    select(Course).where(
                        Course.status == COURSE_PUBLISHED,
                        Course.leaderboard_public.is_(True),
                    )
                ).all()
            )

        boards = []
        for course in courses:
            if actor is None and not course.leaderboard_public:
                continue
            student_ids = sess.scalars(
                select(Enrollment.student_id).where(
                    Enrollment.course_id == course.id,
                    Enrollment.status == ENROLL_ACTIVE,
                )
            ).all()
            entries: list[dict[str, Any]] = []
            for student_id in student_ids:
                student = sess.get(User, student_id)
                if student is None:
                    continue
                total = lesson_count(sess, course.id)
                done = completed_count(sess, student_id, course.id)
                entries.append(
                    {
                        "student": student,
                        "done": done,
                        "total": total,
                        "percent": round(done * 100 / total) if total else 0,
                    }
                )
            entries.sort(key=lambda e: (-e["percent"], e["student"].email))
            boards.append({"course": course, "entries": entries[:20]})

    return render_template("student/leaderboard.html", boards=boards)


# ---------------------------------------------------------------------------
# /settings
# ---------------------------------------------------------------------------


@bp.route("/settings", methods=["GET", "POST"])
@student_required
def settings() -> str | Response:
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        user = sess.get(User, actor["id"])
        if user is None:
            abort(404)

        if request.method == "POST":
            user.email_notifications = request.form.get("email_notifications") == "1"
            sess.flush()
            flash("Đã lưu cài đặt.", "success")
            return redirect(url_for("student.settings"))

        enabled = user.email_notifications

    return render_template("student/settings.html", enabled=enabled)


# ---------------------------------------------------------------------------
# FORUM - Spec: /forum (diễn đàn theo khóa đã đăng ký)
# ---------------------------------------------------------------------------


@bp.get("/forum")
@student_required
def forum_index() -> str:
    """Danh sách diễn đàn các khóa đã đăng ký."""
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        enrollments = sess.scalars(select(Enrollment).where(Enrollment.student_id == actor["id"])).all()
        course_ids = [e.course_id for e in enrollments]

        forum_data = []
        for course_id in course_ids:
            course = sess.get(Course, course_id)
            if not course:
                continue
            instructor = sess.get(User, course.instructor_id)
            topics = sess.scalars(
                select(ForumTopic)
                .where(ForumTopic.course_id == course_id)
                .order_by(ForumTopic.pinned.desc(), ForumTopic.created_at.desc())
            ).all()
            topic_list = []
            for topic in topics:
                author = sess.get(User, topic.author_id)
                replies = (
                    sess.scalar(select(func.count()).select_from(ForumPost).where(ForumPost.topic_id == topic.id)) or 0
                )
                topic_list.append(
                    {
                        "topic": topic,
                        "author": author,
                        "replies": replies,
                    }
                )
            forum_data.append(
                {
                    "course": course,
                    "instructor": instructor,
                    "topics": topic_list,
                }
            )

    return render_template("student/forum_index.html", forum_data=forum_data)


@bp.get("/forum/<course_id>")
@student_required
def forum_course(course_id: str) -> str:
    """Diễn đàn một khóa học cụ thể."""
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        require_enrollment(sess, actor, course_id)
        course = sess.get(Course, course_id)
        if not course:
            abort(404)

        topics = sess.scalars(
            select(ForumTopic)
            .where(ForumTopic.course_id == course_id)
            .order_by(ForumTopic.pinned.desc(), ForumTopic.created_at.desc())
        ).all()

        topic_list = []
        for topic in topics:
            author = sess.get(User, topic.author_id)
            replies = (
                sess.scalar(select(func.count()).select_from(ForumPost).where(ForumPost.topic_id == topic.id)) or 0
            )
            topic_list.append(
                {
                    "topic": topic,
                    "author": author,
                    "replies": replies,
                }
            )

    return render_template("student/forum_course.html", course=course, topics=topic_list)


@bp.get("/forum/<course_id>/topic/<int:topic_id>")
@student_required
def forum_topic(course_id: str, topic_id: int) -> str:
    """Xem chi tiết chủ đề + các bài trả lời."""
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        require_enrollment(sess, actor, course_id)
        topic = sess.get(ForumTopic, topic_id)
        if not topic or topic.course_id != course_id:
            abort(404)
        course = sess.get(Course, course_id)

        posts = sess.scalars(
            select(ForumPost).where(ForumPost.topic_id == topic_id).order_by(ForumPost.created_at)
        ).all()

        post_list = []
        for post in posts:
            author = sess.get(User, post.author_id)
            post_list.append({"post": post, "author": author})

    return render_template(
        "student/forum_topic.html",
        course=course,
        course_id=course_id,
        topic=topic,
        posts=post_list,
    )


@bp.post("/forum/<course_id>/topic/new")
@student_required
def forum_topic_create(course_id: str) -> Response:
    """Tạo chủ đề mới."""
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        require_enrollment(sess, actor, course_id)
        title = (request.form.get("title") or "").strip()
        content_text = (request.form.get("content") or "").strip()
        if not title or not content_text:
            flash("Tiêu đề và nội dung là bắt buộc.", "error")
        else:
            topic = ForumTopic(
                course_id=course_id,
                author_id=actor["id"],
                title=title,
                body=content_text,
            )
            sess.add(topic)
            sess.flush()
            post = ForumPost(
                topic_id=topic.id,
                author_id=actor["id"],
                body=content_text,
            )
            sess.add(post)
            flash("Đã tạo chủ đề mới.", "success")
            return redirect(url_for("student.forum_topic", course_id=course_id, topic_id=topic.id))

    return redirect(url_for("student.forum_course", course_id=course_id))


@bp.post("/forum/<course_id>/topic/<int:topic_id>/reply")
@student_required
def forum_reply(course_id: str, topic_id: int) -> Response:
    """Trả lời chủ đề."""
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        require_enrollment(sess, actor, course_id)
        topic = sess.get(ForumTopic, topic_id)
        if not topic or topic.course_id != course_id:
            abort(404)
        if topic.locked:
            flash("Chủ đề đã bị khoá.", "error")
        else:
            content_text = (request.form.get("content") or "").strip()
            if content_text:
                post = ForumPost(
                    topic_id=topic_id,
                    author_id=actor["id"],
                    body=content_text,
                )
                sess.add(post)
                flash("Đã gửi phản hồi.", "success")
            else:
                flash("Nội dung không được rỗng.", "error")

    return redirect(url_for("student.forum_topic", course_id=course_id, topic_id=topic_id))


@bp.post("/forum/<course_id>/topic/<int:topic_id>/edit")
@student_required
def forum_topic_edit(course_id: str, topic_id: int) -> Response:
    """SV chỉ sửa chủ đề của chính mình (spec mục 6)."""
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        require_enrollment(sess, actor, course_id)
        topic = sess.get(ForumTopic, topic_id)
        if not topic or topic.course_id != course_id:
            abort(404)
        if topic.author_id != actor["id"]:
            abort(403)
        title = (request.form.get("title") or "").strip()
        body = (request.form.get("content") or "").strip()
        if not title or not body:
            flash("Tiêu đề và nội dung là bắt buộc.", "error")
        else:
            topic.title = title
            topic.body = body
            sess.flush()
            audit_record(
                "FORUM_TOPIC_EDITED",
                f"topic:{topic_id}",
                actor_id=actor["id"],
            )
            flash("Đã cập nhật chủ đề.", "success")

    return redirect(url_for("student.forum_topic", course_id=course_id, topic_id=topic_id))


@bp.post("/forum/<course_id>/topic/<int:topic_id>/delete")
@student_required
def forum_topic_delete(course_id: str, topic_id: int) -> Response:
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        require_enrollment(sess, actor, course_id)
        topic = sess.get(ForumTopic, topic_id)
        if not topic or topic.course_id != course_id:
            abort(404)
        if topic.author_id != actor["id"]:
            abort(403)
        for post in sess.scalars(select(ForumPost).where(ForumPost.topic_id == topic_id)).all():
            sess.delete(post)
        sess.delete(topic)
        sess.flush()
        audit_record("FORUM_TOPIC_DELETED", f"topic:{topic_id}", actor_id=actor["id"])
        flash("Đã xoá chủ đề.", "success")

    return redirect(url_for("student.forum_course", course_id=course_id))


@bp.post("/forum/<course_id>/post/<int:post_id>/edit")
@student_required
def forum_post_edit(course_id: str, post_id: int) -> Response:
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        require_enrollment(sess, actor, course_id)
        post = sess.get(ForumPost, post_id)
        if not post:
            abort(404)
        topic = sess.get(ForumTopic, post.topic_id)
        if not topic or topic.course_id != course_id:
            abort(404)
        if post.author_id != actor["id"]:
            abort(403)
        body = (request.form.get("content") or "").strip()
        if not body:
            flash("Nội dung không được rỗng.", "error")
        else:
            post.body = body
            sess.flush()
            audit_record("FORUM_POST_EDITED", f"post:{post_id}", actor_id=actor["id"])
            flash("Đã cập nhật bình luận.", "success")
        topic_id = topic.id

    return redirect(url_for("student.forum_topic", course_id=course_id, topic_id=topic_id))


@bp.post("/forum/<course_id>/post/<int:post_id>/delete")
@student_required
def forum_post_delete(course_id: str, post_id: int) -> Response:
    actor = current_user()
    assert actor is not None

    topic_id = 0
    with get_db().session() as sess:
        require_enrollment(sess, actor, course_id)
        post = sess.get(ForumPost, post_id)
        if not post:
            abort(404)
        topic = sess.get(ForumTopic, post.topic_id)
        if not topic or topic.course_id != course_id:
            abort(404)
        if post.author_id != actor["id"]:
            abort(403)
        topic_id = topic.id
        sess.delete(post)
        sess.flush()
        audit_record("FORUM_POST_DELETED", f"post:{post_id}", actor_id=actor["id"])
        flash("Đã xoá bình luận.", "success")

    return redirect(url_for("student.forum_topic", course_id=course_id, topic_id=topic_id))


@bp.get("/messages")
@student_required
def messages_index() -> str:
    """Danh sách hội thoại với GV của các khóa đã đăng ký."""
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        enrollments = sess.scalars(select(Enrollment).where(Enrollment.student_id == actor["id"])).all()

        conversations = []
        for enrollment in enrollments:
            course = sess.get(Course, enrollment.course_id)
            if not course:
                continue
            instructor = sess.get(User, course.instructor_id)
            if not instructor:
                continue

            # Lấy tin nhắn cuối
            last_msg = sess.execute(
                select(DirectMessage, User)
                .join(User, DirectMessage.sender_id == User.id)
                .where(
                    or_(
                        and_(
                            DirectMessage.sender_id == actor["id"],
                            DirectMessage.recipient_id == instructor.id,
                        ),
                        and_(
                            DirectMessage.sender_id == instructor.id,
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
                        DirectMessage.sender_id == instructor.id,
                        DirectMessage.read_at.is_(None),
                    )
                )
                or 0
            )

            conversations.append(
                {
                    "course": course,
                    "instructor": instructor,
                    "last_message": last_msg,
                    "unread": unread,
                }
            )

    return render_template("student/messages_index.html", conversations=conversations)


@bp.get("/messages/<instructor_id>")
@student_required
def messages_conversation(instructor_id: str) -> str:
    """Hội thoại với một GV cụ thể."""
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        instructor = sess.get(User, instructor_id)
        if not instructor or instructor.role != ROLE_INSTRUCTOR:
            abort(404)

        # Check enrollment in at least one common course
        common = sess.scalars(
            select(Enrollment).where(
                Enrollment.student_id == actor["id"],
                Enrollment.course_id.in_(select(Course.id).where(Course.instructor_id == instructor_id)),
            )
        ).first()
        if not common:
            abort(403)

        # Mark as read
        unread_msgs = sess.scalars(
            select(DirectMessage).where(
                DirectMessage.sender_id == instructor_id,
                DirectMessage.recipient_id == actor["id"],
                DirectMessage.read_at.is_(None),
            )
        ).all()
        for msg in unread_msgs:
            msg.read_at = utcnow()

        # Get messages with sender info
        messages = sess.execute(
            select(DirectMessage, User)
            .join(User, DirectMessage.sender_id == User.id)
            .where(
                or_(
                    and_(
                        DirectMessage.sender_id == actor["id"],
                        DirectMessage.recipient_id == instructor_id,
                    ),
                    and_(
                        DirectMessage.sender_id == instructor_id,
                        DirectMessage.recipient_id == actor["id"],
                    ),
                )
            )
            .order_by(DirectMessage.created_at)
        ).all()

    return render_template("student/messages_conversation.html", instructor=instructor, messages=messages)


@bp.post("/messages/<instructor_id>/send")
@student_required
def messages_send(instructor_id: str) -> Response:
    """Gửi tin nhắn."""
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        instructor = sess.get(User, instructor_id)
        if not instructor or instructor.role != ROLE_INSTRUCTOR:
            abort(404)

        content_text = (request.form.get("content") or "").strip()
        if content_text:
            msg = DirectMessage(
                sender_id=actor["id"],
                recipient_id=instructor_id,
                body=content_text,
            )
            sess.add(msg)
            flash("Đã gửi.", "success")
        else:
            flash("Nội dung không được rỗng.", "error")

    return redirect(url_for("student.messages_conversation", instructor_id=instructor_id))


# ---------------------------------------------------------------------------
# NOTIFICATIONS - Spec: /notifications
# ---------------------------------------------------------------------------


@bp.get("/notifications")
@student_required
def notifications() -> str:
    """Danh sách thông báo."""
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        notes = sess.scalars(
            select(Notification)
            .where(Notification.user_id == actor["id"])
            .order_by(Notification.created_at.desc())
            .limit(50)
        ).all()

    return render_template("student/notifications.html", notifications=notes)


@bp.post("/notifications/<int:notification_id>/read")
@student_required
def notification_read(notification_id: int) -> Response:
    """Đánh dấu đã đọc."""
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        note = sess.get(Notification, notification_id)
        if note and note.user_id == actor["id"]:
            note.read_at = utcnow()
            flash("Đã đánh dấu đã đọc.", "success")

    return redirect(url_for("student.notifications"))


# ---------------------------------------------------------------------------
# PROFILE - Spec: /profile (hồ sơ cá nhân)
# ---------------------------------------------------------------------------


@bp.get("/profile")
@student_required
def profile() -> str:
    """Xem hồ sơ."""
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        user = sess.get(User, actor["id"])

    return render_template("student/profile.html", user=user)


@bp.route("/profile/edit", methods=["GET", "POST"])
@student_required
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
            return redirect(url_for("student.profile"))

    return render_template("student/profile_edit.html", user=user)


@bp.route("/profile/password", methods=["GET", "POST"])
@student_required
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
                return redirect(url_for("student.profile"))

    return render_template("student/profile_password.html", user=user)
