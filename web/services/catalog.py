"""Môn học, lớp (section), danh mục, tag, lộ trình, ghi danh."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from web.models import (
    COURSE_DRAFT,
    COURSE_PUBLISHED,
    ROLE_ADMIN,
    ROLE_STUDENT,
    ROLE_TEACHER,
    Category,
    Course,
    CourseSection,
    CourseTag,
    Enrollment,
    LearningPath,
    LearningPathItem,
    Tag,
    Term,
    User,
)


class CatalogError(Exception):
    """Vi phạm quy tắc nghiệp vụ của catalog."""


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(text: str) -> str:
    lowered = text.strip().lower()
    slug = _SLUG_RE.sub("-", lowered).strip("-")
    return slug or "course"


def _unique_slug(sess: Session, base: str, course_id: str | None = None) -> str:
    candidate = base
    counter = 1
    while True:
        existing = sess.scalars(
            select(Course.id).where(Course.slug == candidate)
        ).first()
        if existing is None or existing == course_id:
            return candidate
        counter += 1
        candidate = f"{base}-{counter}"


def can_manage_course(actor: dict[str, Any] | None, course: Course) -> bool:
    if actor is None:
        return False
    if actor["role"] == ROLE_ADMIN:
        return True
    return bool(actor["role"] == ROLE_TEACHER and course.instructor_id == actor["id"])


def list_courses(
    sess: Session,
    *,
    q: str | None = None,
    category_id: int | None = None,
    tag: str | None = None,
    only_published: bool = True,
    page: int = 1,
    per_page: int = 12,
) -> dict[str, Any]:
    stmt = select(Course)
    if only_published:
        stmt = stmt.where(Course.status == COURSE_PUBLISHED)
    if category_id:
        stmt = stmt.where(Course.category_id == category_id)
    if q:
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(
            or_(func.lower(Course.title).like(like), func.lower(Course.slug).like(like))
        )
    if tag:
        stmt = stmt.join(CourseTag, CourseTag.course_id == Course.id).join(
            Tag, Tag.id == CourseTag.tag_id
        )
        stmt = stmt.where(Tag.name == tag.strip().lower())

    total = sess.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    page = max(1, page)
    rows = sess.scalars(
        stmt.order_by(Course.title).offset((page - 1) * per_page).limit(per_page)
    ).all()
    return {
        "items": rows,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": max(1, (total + per_page - 1) // per_page),
    }


def course_detail(sess: Session, course_id: str) -> dict[str, Any] | None:
    course = sess.get(Course, course_id)
    if course is None:
        return None

    sections = list(
        sess.scalars(
            select(CourseSection)
            .where(CourseSection.course_id == course_id)
            .order_by(CourseSection.id)
        ).all()
    )
    instructor = sess.get(User, course.instructor_id)
    student_count = (
        sess.scalar(
            select(func.count())
            .select_from(Enrollment)
            .where(Enrollment.course_id == course_id)
        )
        or 0
    )
    avg_score = sess.scalar(
        select(func.avg(Enrollment.score)).where(Enrollment.course_id == course_id)
    )
    tags = list(
        sess.scalars(
            select(Tag.name)
            .join(CourseTag, CourseTag.tag_id == Tag.id)
            .where(CourseTag.course_id == course_id)
        ).all()
    )
    return {
        "course": course,
        "sections": sections,
        "instructor": instructor,
        "student_count": student_count,
        "avg_score": round(avg_score, 2) if avg_score is not None else None,
        "tags": tags,
    }


def create_course(
    sess: Session,
    actor: dict[str, Any],
    *,
    title: str,
    description: str = "",
    price: float = 0.0,
    category_id: int | None = None,
    status: str = COURSE_DRAFT,
    instructor_id: str | None = None,
) -> Course:
    if actor["role"] not in {ROLE_ADMIN, ROLE_TEACHER}:
        raise CatalogError("Bạn không có quyền tạo khoá học.")
    if not title.strip():
        raise CatalogError("Tên khoá học là bắt buộc.")
    if price < 0:
        raise CatalogError("Học phí không được âm.")

    owner = instructor_id or actor["id"]
    if actor["role"] == ROLE_TEACHER and owner != actor["id"]:
        raise CatalogError("Giảng viên chỉ tạo được khoá của mình.")

    ids = sess.scalars(select(Course.id)).all()
    nums = [int(i[1:]) for i in ids if i.startswith("c") and i[1:].isdigit()]
    course = Course(
        id=f"c{max(nums, default=0) + 1}",
        title=title.strip(),
        instructor_id=owner,
        slug=_unique_slug(sess, slugify(title)),
        description=description.strip() or None,
        category_id=category_id,
        price=float(price),
        status=status if status in {COURSE_DRAFT, COURSE_PUBLISHED} else COURSE_DRAFT,
    )
    sess.add(course)
    sess.flush()
    return course


def update_course(
    sess: Session,
    actor: dict[str, Any],
    course: Course,
    **fields: Any,
) -> Course:
    if not can_manage_course(actor, course):
        raise CatalogError("Bạn không có quyền sửa khoá học này.")

    if "title" in fields and str(fields["title"]).strip():
        course.title = str(fields["title"]).strip()
        course.slug = _unique_slug(sess, slugify(course.title), course.id)
    if "description" in fields:
        course.description = str(fields["description"]).strip() or None
    if "price" in fields:
        price = float(fields["price"])
        if price < 0:
            raise CatalogError("Học phí không được âm.")
        course.price = price
    if "category_id" in fields:
        course.category_id = fields["category_id"]
    if "status" in fields and fields["status"] in {COURSE_DRAFT, COURSE_PUBLISHED}:
        course.status = str(fields["status"])
    sess.flush()
    return course


def set_tags(sess: Session, course: Course, raw_tags: str) -> None:
    wanted = {t.strip().lower() for t in raw_tags.split(",") if t.strip()}
    current = {
        row.tag_id
        for row in sess.scalars(
            select(CourseTag).where(CourseTag.course_id == course.id)
        ).all()
    }
    for name in wanted:
        tag = sess.scalars(select(Tag).where(Tag.name == name)).first()
        if tag is None:
            tag = Tag(name=name)
            sess.add(tag)
            sess.flush()
        if tag.id not in current:
            sess.add(CourseTag(course_id=course.id, tag_id=tag.id))
    sess.flush()


def ensure_section(sess: Session, course: Course) -> CourseSection:
    existing = sess.scalars(
        select(CourseSection).where(CourseSection.course_id == course.id)
    ).first()
    if existing is not None:
        return existing
    section = CourseSection(course_id=course.id, code="01", capacity=40)
    sess.add(section)
    sess.flush()
    return section


def enroll(
    sess: Session,
    actor: dict[str, Any],
    course: Course,
    section: CourseSection | None,
) -> Enrollment:
    if actor["role"] != ROLE_STUDENT:
        raise CatalogError("Chỉ học viên mới ghi danh được.")
    existing = sess.scalars(
        select(Enrollment).where(
            Enrollment.course_id == course.id,
            Enrollment.student_id == actor["id"],
        )
    ).first()
    if existing is not None:
        return existing

    status = "PENDING" if course.price > 0 else "APPROVED"
    row = Enrollment(
        course_id=course.id,
        section_id=section.id if section else None,
        student_id=actor["id"],
        status=status,
    )
    sess.add(row)
    sess.flush()
    return row


def set_enrollment_status(
    sess: Session, actor: dict[str, Any], enrollment: Enrollment, status: str
) -> Enrollment:
    course = sess.get(Course, enrollment.course_id)
    if course is None or not can_manage_course(actor, course):
        raise CatalogError("Bạn không có quyền duyệt ghi danh.")
    if status not in {"APPROVED", "PENDING", "REJECTED"}:
        raise CatalogError("Trạng thái không hợp lệ.")
    enrollment.status = status
    sess.flush()
    return enrollment


def is_enrolled(sess: Session, user_id: str, course_id: str) -> bool:
    return bool(
        sess.scalars(
            select(Enrollment.id).where(
                Enrollment.course_id == course_id,
                Enrollment.student_id == user_id,
                Enrollment.status == "APPROVED",
            )
        ).first()
    )


def sections_of_teacher(sess: Session, teacher_id: str) -> list[dict[str, Any]]:
    rows = sess.execute(
        select(CourseSection, Course)
        .join(Course, CourseSection.course_id == Course.id)
        .where(Course.instructor_id == teacher_id)
        .order_by(Course.id, CourseSection.code)
    ).all()
    result: list[dict[str, Any]] = []
    for section, course in rows:
        students = (
            sess.scalar(
                select(func.count())
                .select_from(Enrollment)
                .where(Enrollment.section_id == section.id)
            )
            or 0
        )
        result.append({"section": section, "course": course, "students": students})
    return result


def categories(sess: Session) -> list[Category]:
    return list(sess.scalars(select(Category).order_by(Category.name)).all())


def terms(sess: Session) -> list[Term]:
    return list(sess.scalars(select(Term).order_by(Term.name)).all())


def learning_paths(sess: Session) -> list[dict[str, Any]]:
    paths = sess.scalars(select(LearningPath).order_by(LearningPath.id)).all()
    result = []
    for path in paths:
        items = sess.execute(
            select(LearningPathItem, Course)
            .join(Course, LearningPathItem.course_id == Course.id)
            .where(LearningPathItem.path_id == path.id)
            .order_by(LearningPathItem.position)
        ).all()
        result.append({"path": path, "items": items})
    return result
