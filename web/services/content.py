"""Module, bài học, phiên bản nội dung, tài nguyên, bình luận bài học."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from web.models import (
    ROLE_ADMIN,
    Attachment,
    Course,
    CourseSection,
    Lesson,
    LessonComment,
    LessonVersion,
    Module,
    User,
)
from web.services.catalog import can_manage_course


class ContentError(Exception):
    """Vi phạm quy tắc nghiệp vụ của nội dung."""


def _course_of_section(sess: Session, section_id: int) -> Course | None:
    section = sess.get(CourseSection, section_id)
    return sess.get(Course, section.course_id) if section else None


def can_manage_section(
    sess: Session, actor: dict[str, Any] | None, section_id: int
) -> bool:
    if actor is None:
        return False
    if actor["role"] == ROLE_ADMIN:
        return True
    course = _course_of_section(sess, section_id)
    return course is not None and can_manage_course(actor, course)


def modules_of_section(sess: Session, section_id: int) -> list[Module]:
    return list(
        sess.scalars(
            select(Module)
            .where(Module.section_id == section_id)
            .order_by(Module.position, Module.id)
        ).all()
    )


def lessons_of_module(sess: Session, module_id: int) -> list[Lesson]:
    return list(
        sess.scalars(
            select(Lesson)
            .where(Lesson.module_id == module_id)
            .order_by(Lesson.position, Lesson.id)
        ).all()
    )


def outline(sess: Session, section_id: int) -> list[dict[str, Any]]:
    """Mục lục: danh sách module kèm bài học."""
    return [
        {"module": module, "lessons": lessons_of_module(sess, module.id)}
        for module in modules_of_section(sess, section_id)
    ]


def create_module(
    sess: Session, actor: dict[str, Any], section_id: int, title: str
) -> Module:
    if not can_manage_section(sess, actor, section_id):
        raise ContentError("Bạn không có quyền thêm chương cho lớp này.")
    if not title.strip():
        raise ContentError("Tên chương là bắt buộc.")
    position = (
        sess.scalar(
            select(func.coalesce(func.max(Module.position), 0)).where(
                Module.section_id == section_id
            )
        )
        or 0
    ) + 1
    module = Module(section_id=section_id, title=title.strip(), position=position)
    sess.add(module)
    sess.flush()
    return module


def _allowed_kinds() -> set[str]:
    return {"video", "pdf", "text", "link", "slide"}


def create_lesson(
    sess: Session,
    actor: dict[str, Any],
    module: Module,
    *,
    title: str,
    kind: str = "text",
    content: str = "",
    media_url: str = "",
    duration_min: int = 0,
    is_preview: bool = False,
) -> Lesson:
    if not can_manage_section(sess, actor, module.section_id):
        raise ContentError("Bạn không có quyền thêm bài học.")
    if not title.strip():
        raise ContentError("Tên bài học là bắt buộc.")
    if kind not in _allowed_kinds():
        raise ContentError("Loại bài học không hợp lệ.")
    position = (
        sess.scalar(
            select(func.coalesce(func.max(Lesson.position), 0)).where(
                Lesson.module_id == module.id
            )
        )
        or 0
    ) + 1
    lesson = Lesson(
        module_id=module.id,
        title=title.strip(),
        kind=kind,
        content=content.strip() or None,
        media_url=media_url.strip() or None,
        duration_min=max(0, int(duration_min)),
        is_preview=is_preview,
        position=position,
    )
    sess.add(lesson)
    sess.flush()
    return lesson


def update_lesson(
    sess: Session, actor: dict[str, Any], lesson: Lesson, **fields: Any
) -> Lesson:
    module = sess.get(Module, lesson.module_id)
    if module is None or not can_manage_section(sess, actor, module.section_id):
        raise ContentError("Bạn không có quyền sửa bài học này.")

    # Lưu phiên bản trước khi ghi đè nội dung.
    sess.add(
        LessonVersion(
            lesson_id=lesson.id,
            editor_id=actor["id"],
            title=lesson.title,
            content=lesson.content,
            media_url=lesson.media_url,
        )
    )
    if "title" in fields and str(fields["title"]).strip():
        lesson.title = str(fields["title"]).strip()
    if "content" in fields:
        lesson.content = str(fields["content"]).strip() or None
    if "media_url" in fields:
        lesson.media_url = str(fields["media_url"]).strip() or None
    if "kind" in fields and fields["kind"] in _allowed_kinds():
        lesson.kind = str(fields["kind"])
    if "duration_min" in fields:
        lesson.duration_min = max(0, int(fields["duration_min"]))
    if "is_preview" in fields:
        lesson.is_preview = bool(fields["is_preview"])
    sess.flush()
    return lesson


def versions_of(sess: Session, lesson_id: int) -> list[dict[str, Any]]:
    rows = sess.execute(
        select(LessonVersion, User.email)
        .join(User, LessonVersion.editor_id == User.id)
        .where(LessonVersion.lesson_id == lesson_id)
        .order_by(LessonVersion.created_at.desc())
    ).all()
    return [{"version": version, "editor": email} for version, email in rows]


def restore_version(
    sess: Session, actor: dict[str, Any], lesson: Lesson, version: LessonVersion
) -> Lesson:
    return update_lesson(
        sess,
        actor,
        lesson,
        title=version.title,
        content=version.content or "",
        media_url=version.media_url or "",
    )


def add_attachment(
    sess: Session,
    actor: dict[str, Any],
    *,
    title: str,
    stored_name: str,
    mime: str,
    size_bytes: int,
    lesson_id: int | None = None,
) -> Attachment:
    row = Attachment(
        owner_id=actor["id"],
        lesson_id=lesson_id,
        title=title,
        stored_name=stored_name,
        mime=mime,
        size_bytes=size_bytes,
    )
    sess.add(row)
    sess.flush()
    return row


def asset_library(sess: Session, owner_id: str | None = None) -> list[dict[str, Any]]:
    stmt = (
        select(Attachment, User.email)
        .join(User, Attachment.owner_id == User.id)
        .order_by(Attachment.created_at.desc())
    )
    if owner_id:
        stmt = stmt.where(Attachment.owner_id == owner_id)
    return [
        {"asset": asset, "owner": email} for asset, email in sess.execute(stmt).all()
    ]


def attachments_of_lesson(sess: Session, lesson_id: int) -> list[Attachment]:
    return list(
        sess.scalars(
            select(Attachment)
            .where(Attachment.lesson_id == lesson_id)
            .order_by(Attachment.id)
        ).all()
    )


def add_comment(
    sess: Session, actor: dict[str, Any], lesson_id: int, body: str
) -> LessonComment:
    if not body.strip():
        raise ContentError("Nội dung bình luận không được để trống.")
    comment = LessonComment(
        lesson_id=lesson_id, author_id=actor["id"], body=body.strip()[:5000]
    )
    sess.add(comment)
    sess.flush()
    return comment


def comments_of_lesson(sess: Session, lesson_id: int) -> list[dict[str, Any]]:
    rows = sess.execute(
        select(LessonComment, User.email, User.full_name)
        .join(User, LessonComment.author_id == User.id)
        .where(LessonComment.lesson_id == lesson_id)
        .order_by(LessonComment.created_at)
    ).all()
    return [
        {"comment": comment, "email": email, "name": name}
        for comment, email, name in rows
    ]
