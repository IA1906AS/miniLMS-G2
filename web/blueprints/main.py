"""Blueprint trang công khai + dashboard dùng chung.

Spec mục 1 (Khách): /, /courses, /courses/:id, /instructors.
Spec mục 2 & 3: /dashboard (SV và GV đều dùng).
"""

from __future__ import annotations

from typing import Any

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session
from werkzeug.wrappers import Response

from web.auth import current_user, login_required
from web.database import get_db
from web.models import (
    COURSE_PUBLISHED,
    ROLE_ADMIN,
    ROLE_INSTRUCTOR,
    ROLE_STUDENT,
    Category,
    Chapter,
    Course,
    CourseTag,
    Enrollment,
    Lesson,
    LessonProgress,
    Quiz,
    Tag,
    User,
)

bp = Blueprint("main", __name__)


def published_courses(
    sess: Session,
    *,
    q: str | None = None,
    category_id: int | None = None,
    tag: str | None = None,
    instructor_id: str | None = None,
) -> list[Course]:
    stmt = select(Course).where(Course.status == COURSE_PUBLISHED)
    if category_id:
        stmt = stmt.where(Course.category_id == category_id)
    if instructor_id:
        stmt = stmt.where(Course.instructor_id == instructor_id)
    if q:
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Course.title).like(like),
                func.lower(func.coalesce(Course.description, "")).like(like),
            )
        )
    if tag:
        stmt = (
            stmt.join(CourseTag, CourseTag.course_id == Course.id)
            .join(Tag, Tag.id == CourseTag.tag_id)
            .where(Tag.name == tag.strip().lower())
        )
    return list(sess.scalars(stmt.order_by(Course.title)).all())


def course_card_data(sess: Session, courses: list[Course]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for course in courses:
        instructor = sess.get(User, course.instructor_id)
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
        rows.append(
            {
                "course": course,
                "instructor": instructor,
                "students": students,
                "lessons": lessons,
            }
        )
    return rows


def curriculum(sess: Session, course_id: str) -> list[dict[str, Any]]:
    chapters = sess.scalars(
        select(Chapter).where(Chapter.course_id == course_id).order_by(Chapter.position, Chapter.id)
    ).all()
    out: list[dict[str, Any]] = []
    for chapter in chapters:
        lessons = sess.scalars(
            select(Lesson).where(Lesson.chapter_id == chapter.id).order_by(Lesson.position, Lesson.id)
        ).all()
        out.append({"chapter": chapter, "lessons": lessons})
    return out


@bp.get("/")
def home() -> str:
    with get_db().session() as sess:
        courses = published_courses(sess)
        cards = course_card_data(sess, courses[:6])
        stats = {
            "courses": sess.scalar(select(func.count()).select_from(Course)) or 0,
            "students": sess.scalar(select(func.count()).select_from(User).where(User.role == ROLE_STUDENT)) or 0,
            "instructors": sess.scalar(select(func.count()).select_from(User).where(User.role == ROLE_INSTRUCTOR)) or 0,
            "enrollments": sess.scalar(select(func.count()).select_from(Enrollment)) or 0,
        }
    return render_template("main/home.html", cards=cards, stats=stats)


@bp.get("/courses")
def courses() -> str:
    q = request.args.get("q", "").strip()
    category_id = request.args.get("category", type=int)
    tag = request.args.get("tag", "").strip() or None
    instructor_id = request.args.get("instructor", "").strip() or None

    with get_db().session() as sess:
        found = published_courses(
            sess,
            q=q or None,
            category_id=category_id,
            tag=tag,
            instructor_id=instructor_id,
        )
        cards = course_card_data(sess, found)
        categories = list(sess.scalars(select(Category).order_by(Category.name)).all())
        tags = list(sess.scalars(select(Tag).order_by(Tag.name)).all())
        instructors = list(
            sess.scalars(select(User).where(User.role == ROLE_INSTRUCTOR).order_by(User.full_name)).all()
        )

    return render_template(
        "main/courses.html",
        cards=cards,
        categories=categories,
        tags=tags,
        instructors=instructors,
        q=q,
        category_id=category_id or 0,
        tag=tag or "",
        instructor_id=instructor_id or "",
    )


@bp.route("/courses/<course_id>", methods=["GET", "POST"])
def course_detail(course_id: str) -> str | Response:
    actor = current_user()

    if request.method == "POST":
        if actor is None:
            flash("Vui lòng đăng nhập để đăng ký khoá học.", "error")
            return redirect(
                url_for(
                    "auth.login",
                    next=url_for("main.course_detail", course_id=course_id),
                )
            )
        if actor["role"] != ROLE_STUDENT:
            flash("Chỉ sinh viên mới đăng ký được khoá học.", "error")
            return redirect(url_for("main.course_detail", course_id=course_id))

        with get_db().session() as sess:
            existing = sess.scalars(
                select(Enrollment).where(
                    Enrollment.course_id == course_id,
                    Enrollment.student_id == actor["id"],
                )
            ).first()
            if existing is None:
                sess.add(
                    Enrollment(
                        course_id=course_id,
                        student_id=actor["id"],
                        status="ACTIVE",
                    )
                )
                flash("Đăng ký khoá học thành công!", "success")
            else:
                flash("Bạn đã đăng ký khoá học này từ trước.", "info")

        return redirect(url_for("student.learn", course_id=course_id))

    with get_db().session() as sess:
        course = sess.get(Course, course_id)
        if course is None:
            abort(404)

        is_staff = actor is not None and (actor["role"] == ROLE_ADMIN or course.instructor_id == actor["id"])
        if course.status != COURSE_PUBLISHED and not is_staff:
            abort(404)

        instructor = sess.get(User, course.instructor_id)
        chapters = curriculum(sess, course_id)
        enrolled = False
        if actor is not None and actor["role"] == ROLE_STUDENT:
            enrolled = (
                sess.scalars(
                    select(Enrollment.id).where(
                        Enrollment.course_id == course_id,
                        Enrollment.student_id == actor["id"],
                    )
                ).first()
                is not None
            )
        students = (
            sess.scalar(select(func.count()).select_from(Enrollment).where(Enrollment.course_id == course_id)) or 0
        )
        quiz_count = sess.scalar(select(func.count()).select_from(Quiz).where(Quiz.course_id == course_id)) or 0

        quizzes = list(sess.scalars(select(Quiz).where(Quiz.course_id == course_id)).all())

    return render_template(
        "main/course_detail.html",
        course=course,
        instructor=instructor,
        chapters=chapters,
        enrolled=enrolled,
        is_staff=is_staff,
        students=students,
        quiz_count=quiz_count,
        quizzes=quizzes,
    )


@bp.get("/courses/<course_id>/preview/<int:lesson_id>")
def course_preview(course_id: str, lesson_id: int) -> str | Response:
    """Cho phép Khách / Sinh viên chưa đăng ký xem học thử bài học có is_free_preview = True."""
    actor = current_user()

    with get_db().session() as sess:
        course = sess.get(Course, course_id)
        lesson = sess.get(Lesson, lesson_id)
        if course is None or lesson is None:
            abort(404)

        chapter = sess.get(Chapter, lesson.chapter_id)
        if chapter is None or chapter.course_id != course_id:
            abort(404)

        is_staff = actor is not None and (actor["role"] == ROLE_ADMIN or course.instructor_id == actor["id"])
        enrolled = False
        if actor is not None and actor["role"] == ROLE_STUDENT:
            enrolled = (
                sess.scalars(
                    select(Enrollment.id).where(
                        Enrollment.course_id == course_id,
                        Enrollment.student_id == actor["id"],
                    )
                ).first()
                is not None
            )

        if not lesson.is_free_preview and not is_staff and not enrolled:
            flash("Bài học này không hỗ trợ học thử. Vui lòng đăng ký khoá học.", "error")
            return redirect(url_for("main.course_detail", course_id=course_id))

        chapters = curriculum(sess, course_id)

    return render_template(
        "student/lesson.html",
        course=course,
        lesson=lesson,
        chapter=chapter,
        chapters=chapters,
        done=set(),
        total=0,
        completed=0,
        percent=0,
        prev_lesson=None,
        next_lesson=None,
        is_preview=True,
    )


@bp.get("/instructors")
def instructors() -> str:
    with get_db().session() as sess:
        people = sess.scalars(
            select(User).where(User.role == ROLE_INSTRUCTOR).order_by(User.full_name, User.email)
        ).all()
        rows = []
        for person in people:
            taught = sess.scalars(
                select(Course).where(
                    Course.instructor_id == person.id,
                    Course.status == COURSE_PUBLISHED,
                )
            ).all()
            rows.append({"user": person, "courses": taught})
    return render_template("main/instructors.html", rows=rows)


# ---------------------------------------------------------------------------
# Dashboard — SV & GV
# ---------------------------------------------------------------------------


def _student_dashboard(sess: Session, actor: dict[str, Any]) -> dict[str, Any]:
    enrollments = sess.scalars(select(Enrollment).where(Enrollment.student_id == actor["id"])).all()
    items = []
    for enrollment in enrollments:
        course = sess.get(Course, enrollment.course_id)
        if course is None:
            continue
        total = (
            sess.scalar(
                select(func.count())
                .select_from(Lesson)
                .join(Chapter, Lesson.chapter_id == Chapter.id)
                .where(Chapter.course_id == course.id)
            )
            or 0
        )
        done = (
            sess.scalar(
                select(func.count())
                .select_from(LessonProgress)
                .join(Lesson, LessonProgress.lesson_id == Lesson.id)
                .join(Chapter, Lesson.chapter_id == Chapter.id)
                .where(
                    Chapter.course_id == course.id,
                    LessonProgress.student_id == actor["id"],
                )
            )
            or 0
        )
        percent = round(done * 100 / total) if total else 0
        items.append(
            {
                "course": course,
                "total": total,
                "done": done,
                "percent": percent,
            }
        )
    return {"items": items}


def _instructor_dashboard(sess: Session, actor: dict[str, Any]) -> dict[str, Any]:
    taught = sess.scalars(select(Course).where(Course.instructor_id == actor["id"]).order_by(Course.title)).all()
    items = []
    for course in taught:
        students = (
            sess.scalar(select(func.count()).select_from(Enrollment).where(Enrollment.course_id == course.id)) or 0
        )
        items.append({"course": course, "students": students})
    return {"items": items}


def _admin_dashboard(sess: Session, actor: dict[str, Any]) -> dict[str, Any]:
    """Tổng quan hệ thống — spec mục 4 (/admin/dashboard)."""
    totals = {
        "users": sess.scalar(select(func.count()).select_from(User)) or 0,
        "courses": sess.scalar(select(func.count()).select_from(Course)) or 0,
        "enrollments": sess.scalar(select(func.count()).select_from(Enrollment)) or 0,
        "published": sess.scalar(select(func.count()).select_from(Course).where(Course.status == COURSE_PUBLISHED))
        or 0,
    }
    role_counts = [
        {
            "role": role,
            "count": sess.scalar(select(func.count()).select_from(User).where(User.role == role)) or 0,
        }
        for role in (ROLE_ADMIN, ROLE_INSTRUCTOR, ROLE_STUDENT)
    ]
    recent = list(sess.scalars(select(Course).order_by(Course.created_at.desc()).limit(8)).all())
    return {"totals": totals, "role_counts": role_counts, "recent": recent}


@bp.get("/dashboard")
@login_required
def dashboard() -> str:
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        if actor["role"] == ROLE_ADMIN:
            data = _admin_dashboard(sess, actor)
        elif actor["role"] == ROLE_INSTRUCTOR:
            data = _instructor_dashboard(sess, actor)
        else:
            data = _student_dashboard(sess, actor)

    return render_template("main/dashboard.html", role=actor["role"], **data)


@bp.get("/members/<user_id>")
@login_required
def member_profile(user_id: str) -> str:
    """Xem hồ sơ công khai của thành viên (spec mục 2)."""
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        member = sess.get(User, user_id)
        if member is None:
            abort(404)

        taught: list[Course] = []
        studying: list[Course] = []
        if member.role == ROLE_INSTRUCTOR:
            taught = list(
                sess.scalars(
                    select(Course)
                    .where(
                        Course.instructor_id == member.id,
                        Course.status == COURSE_PUBLISHED,
                    )
                    .order_by(Course.title)
                ).all()
            )
        elif member.role == ROLE_STUDENT:
            studying = list(
                sess.scalars(
                    select(Course)
                    .join(Enrollment, Enrollment.course_id == Course.id)
                    .where(
                        Enrollment.student_id == member.id,
                        Course.status == COURSE_PUBLISHED,
                    )
                    .order_by(Course.title)
                ).all()
            )

        shared = []
        if actor["id"] != member.id and actor["role"] == ROLE_STUDENT:
            mine = set(sess.scalars(select(Enrollment.course_id).where(Enrollment.student_id == actor["id"])).all())
            theirs = set(sess.scalars(select(Enrollment.course_id).where(Enrollment.student_id == member.id)).all())
            common = mine & theirs
            if common:
                shared = list(sess.scalars(select(Course).where(Course.id.in_(common))).all())

    return render_template(
        "main/member_profile.html",
        member=member,
        taught=taught,
        studying=studying,
        shared=shared,
    )
