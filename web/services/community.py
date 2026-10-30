"""Diễn đàn, thông báo, announcement, live session."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from web.models import (
    Announcement,
    CourseSection,
    ForumPost,
    ForumTopic,
    LiveSession,
    Notification,
    User,
    utcnow,
)
from web.services import activity
from web.services.content import can_manage_section


class ForumError(Exception):
    """Vi phạm quy tắc nghiệp vụ của diễn đàn."""


def create_topic(
    sess: Session, actor: dict[str, Any], section_id: int, title: str, body: str
) -> ForumTopic:
    if not title.strip() or not body.strip():
        raise ForumError("Tiêu đề và nội dung là bắt buộc.")
    topic = ForumTopic(
        section_id=section_id,
        author_id=actor["id"],
        title=title.strip()[:200],
        body=body.strip()[:20000],
    )
    sess.add(topic)
    sess.flush()
    activity.log_event(
        sess,
        actor["id"],
        activity.VERB_FORUM_POSTED,
        section_id=section_id,
        object_type="topic",
        object_id=str(topic.id),
        payload={"title": topic.title},
    )
    return topic


def topics_of_section(sess: Session, section_id: int) -> list[dict[str, Any]]:
    rows = sess.execute(
        select(ForumTopic, User.email, func.count(ForumPost.id))
        .join(User, ForumTopic.author_id == User.id)
        .outerjoin(ForumPost, ForumPost.topic_id == ForumTopic.id)
        .where(ForumTopic.section_id == section_id)
        .group_by(ForumTopic.id, User.email)
        .order_by(ForumTopic.pinned.desc(), ForumTopic.created_at.desc())
    ).all()
    return [
        {"topic": topic, "author": email, "replies": replies}
        for topic, email, replies in rows
    ]


def get_topic(sess: Session, topic_id: int) -> dict[str, Any] | None:
    topic = sess.get(ForumTopic, topic_id)
    if topic is None:
        return None
    author = sess.get(User, topic.author_id)
    posts = sess.execute(
        select(ForumPost, User.email)
        .join(User, ForumPost.author_id == User.id)
        .where(ForumPost.topic_id == topic.id)
        .order_by(ForumPost.created_at)
    ).all()
    return {
        "topic": topic,
        "author": author,
        "posts": [{"post": post, "email": email} for post, email in posts],
    }


def reply(
    sess: Session, actor: dict[str, Any], topic: ForumTopic, body: str
) -> ForumPost:
    if topic.locked:
        raise ForumError("Chủ đề đã bị khoá.")
    if not body.strip():
        raise ForumError("Nội dung trả lời không được để trống.")
    post = ForumPost(
        topic_id=topic.id, author_id=actor["id"], body=body.strip()[:20000]
    )
    sess.add(post)
    sess.flush()
    activity.log_event(
        sess,
        actor["id"],
        activity.VERB_FORUM_POSTED,
        section_id=topic.section_id,
        object_type="post",
        object_id=str(post.id),
    )
    return post


def moderate_topic(
    sess: Session,
    actor: dict[str, Any],
    topic: ForumTopic,
    *,
    lock: bool | None = None,
    pin: bool | None = None,
) -> ForumTopic:
    if not can_manage_section(sess, actor, topic.section_id):
        raise ForumError("Bạn không có quyền điều hành chủ đề này.")
    if lock is not None:
        topic.locked = lock
    if pin is not None:
        topic.pinned = pin
    sess.flush()
    return topic


# ---------------------------------------------------------------------------
# Thông báo
# ---------------------------------------------------------------------------


def notify(
    sess: Session,
    user_id: str,
    *,
    title: str,
    body: str = "",
    kind: str = "INFO",
    link: str | None = None,
) -> Notification:
    row = Notification(
        user_id=user_id, kind=kind, title=title[:200], body=body or None, link=link
    )
    sess.add(row)
    sess.flush()
    return row


def notify_section(
    sess: Session,
    section_id: int,
    *,
    title: str,
    body: str = "",
    kind: str = "INFO",
    link: str | None = None,
) -> int:
    from web.models import Enrollment

    students = sess.scalars(
        select(Enrollment.student_id).where(
            Enrollment.section_id == section_id, Enrollment.status == "APPROVED"
        )
    ).all()
    for student_id in students:
        notify(sess, student_id, title=title, body=body, kind=kind, link=link)
    return len(students)


def notifications_of(
    sess: Session, user_id: str, *, limit: int = 50
) -> list[Notification]:
    return list(
        sess.scalars(
            select(Notification)
            .where(Notification.user_id == user_id)
            .order_by(Notification.created_at.desc(), Notification.id.desc())
            .limit(limit)
        ).all()
    )


def unread_count(sess: Session, user_id: str) -> int:
    return (
        sess.scalar(
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == user_id, Notification.read_at.is_(None))
        )
        or 0
    )


def mark_all_read(sess: Session, user_id: str) -> int:
    rows = sess.scalars(
        select(Notification).where(
            Notification.user_id == user_id, Notification.read_at.is_(None)
        )
    ).all()
    for row in rows:
        row.read_at = utcnow()
    if rows:
        sess.flush()
    return len(rows)


# ---------------------------------------------------------------------------
# Announcement & live session
# ---------------------------------------------------------------------------


def create_announcement(
    sess: Session, actor: dict[str, Any], section_id: int, title: str, body: str
) -> Announcement:
    if not can_manage_section(sess, actor, section_id):
        raise ForumError("Bạn không có quyền đăng thông báo cho lớp này.")
    row = Announcement(
        section_id=section_id,
        author_id=actor["id"],
        title=title.strip()[:200],
        body=body.strip()[:20000],
    )
    sess.add(row)
    sess.flush()
    notify_section(
        sess, section_id, title=title.strip(), body=body.strip(), kind="ANNOUNCEMENT"
    )
    return row


def announcements_of(sess: Session, section_id: int) -> list[Announcement]:
    return list(
        sess.scalars(
            select(Announcement)
            .where(Announcement.section_id == section_id)
            .order_by(Announcement.created_at.desc())
        ).all()
    )


def create_live_session(
    sess: Session,
    actor: dict[str, Any],
    section_id: int,
    *,
    title: str,
    meeting_url: str,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
) -> LiveSession:
    if not can_manage_section(sess, actor, section_id):
        raise ForumError("Bạn không có quyền tạo buổi học trực tuyến.")
    if not title.strip() or not meeting_url.strip():
        raise ForumError("Tiêu đề và link phòng học là bắt buộc.")
    row = LiveSession(
        section_id=section_id,
        title=title.strip()[:200],
        meeting_url=meeting_url.strip()[:500],
        start_at=start_at,
        end_at=end_at,
        created_by=actor["id"],
    )
    sess.add(row)
    sess.flush()
    return row


def live_sessions_of(sess: Session, section_id: int) -> list[LiveSession]:
    return list(
        sess.scalars(
            select(LiveSession)
            .where(LiveSession.section_id == section_id)
            .order_by(LiveSession.start_at)
        ).all()
    )


def section_brief(sess: Session, section_id: int) -> CourseSection | None:
    return sess.get(CourseSection, section_id)
