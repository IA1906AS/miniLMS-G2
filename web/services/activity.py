"""Hoạt động, tiến độ, điểm thành tích, huy hiệu, streak, leaderboard.

Bốn tính năng (tiến độ, báo cáo, gamification, thông báo) đều đọc từ
``activity_events`` — viết một bảng, dùng cho bốn chỗ.
"""

from __future__ import annotations

import itertools
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from web.models import (
    ActivityEvent,
    Badge,
    CourseSection,
    Enrollment,
    Lesson,
    LessonCompletion,
    Module,
    PointsLedger,
    QuizAttempt,
    User,
    UserBadge,
    utcnow,
)

VERB_LESSON_COMPLETED = "lesson_completed"
VERB_QUIZ_SUBMITTED = "quiz_submitted"
VERB_FORUM_POSTED = "forum_posted"
VERB_LOGIN = "login"
VERB_ENROLLED = "enrolled"

POINTS_LESSON = 5
POINTS_QUIZ_PASS = 20


def log_event(
    sess: Session,
    user_id: str,
    verb: str,
    *,
    section_id: int | None = None,
    object_type: str | None = None,
    object_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> ActivityEvent:
    event = ActivityEvent(
        user_id=user_id,
        verb=verb,
        section_id=section_id,
        object_type=object_type,
        object_id=object_id,
        payload=payload or {},
    )
    sess.add(event)
    sess.flush()
    return event


# ---------------------------------------------------------------------------
# Điểm thành tích
# ---------------------------------------------------------------------------


def award_points(
    sess: Session,
    user_id: str,
    points: int,
    reason: str,
    *,
    ref_type: str | None = None,
    ref_id: str | None = None,
) -> int:
    """Cộng điểm một lần cho mỗi (reason, ref) — tránh cày điểm khi F5."""
    exists = sess.scalar(
        select(func.count())
        .select_from(PointsLedger)
        .where(
            PointsLedger.user_id == user_id,
            PointsLedger.reason == reason,
            PointsLedger.ref_id == ref_id,
        )
    )
    if not exists:
        sess.add(
            PointsLedger(
                user_id=user_id,
                points=points,
                reason=reason,
                ref_type=ref_type,
                ref_id=ref_id,
            )
        )
        sess.flush()
    return user_points(sess, user_id)


def user_points(sess: Session, user_id: str) -> int:
    return (
        sess.scalar(
            select(func.coalesce(func.sum(PointsLedger.points), 0)).where(
                PointsLedger.user_id == user_id
            )
        )
        or 0
    )


# ---------------------------------------------------------------------------
# Tiến độ
# ---------------------------------------------------------------------------


def section_lessons(sess: Session, section_id: int) -> list[Lesson]:
    return list(
        sess.scalars(
            select(Lesson)
            .join(Module, Lesson.module_id == Module.id)
            .where(Module.section_id == section_id)
            .order_by(Module.position, Lesson.position, Lesson.id)
        ).all()
    )


def is_lesson_completed(sess: Session, user_id: str, lesson_id: int) -> bool:
    return bool(
        sess.scalar(
            select(func.count())
            .select_from(LessonCompletion)
            .where(
                LessonCompletion.student_id == user_id,
                LessonCompletion.lesson_id == lesson_id,
            )
        )
    )


def complete_lesson(
    sess: Session, user_id: str, lesson: Lesson, section_id: int | None
) -> bool:
    """Đánh dấu hoàn thành (idempotent). Trả True nếu đây là lần đầu."""
    if is_lesson_completed(sess, user_id, lesson.id):
        return False

    sess.add(LessonCompletion(lesson_id=lesson.id, student_id=user_id))
    sess.flush()
    log_event(
        sess,
        user_id,
        VERB_LESSON_COMPLETED,
        section_id=section_id,
        object_type="lesson",
        object_id=str(lesson.id),
        payload={"title": lesson.title},
    )
    award_points(
        sess,
        user_id,
        POINTS_LESSON,
        "lesson_completed",
        ref_type="lesson",
        ref_id=str(lesson.id),
    )
    evaluate_badges(sess, user_id)
    return True


def completed_lesson_ids(sess: Session, user_id: str, section_id: int) -> set[int]:
    rows = sess.scalars(
        select(LessonCompletion.lesson_id)
        .join(Lesson, LessonCompletion.lesson_id == Lesson.id)
        .join(Module, Lesson.module_id == Module.id)
        .where(
            LessonCompletion.student_id == user_id,
            Module.section_id == section_id,
        )
    ).all()
    return set(rows)


def section_progress(sess: Session, user_id: str, section_id: int) -> dict[str, Any]:
    lessons = section_lessons(sess, section_id)
    done = completed_lesson_ids(sess, user_id, section_id)
    total = len(lessons)
    completed = sum(1 for lesson in lessons if lesson.id in done)
    percent = round(completed * 100 / total) if total else 0
    return {
        "total": total,
        "completed": completed,
        "percent": percent,
        "done_ids": done,
    }


def recent_activity(
    sess: Session, *, section_id: int | None = None, limit: int = 20
) -> list[dict[str, Any]]:
    stmt = (
        select(ActivityEvent, User.email)
        .join(User, ActivityEvent.user_id == User.id)
        .order_by(ActivityEvent.ts.desc(), ActivityEvent.id.desc())
        .limit(limit)
    )
    if section_id is not None:
        stmt = stmt.where(ActivityEvent.section_id == section_id)

    return [
        {
            "ts": event.ts,
            "email": email,
            "verb": event.verb,
            "object_id": event.object_id,
            "payload": event.payload,
        }
        for event, email in sess.execute(stmt).all()
    ]


# ---------------------------------------------------------------------------
# Streak
# ---------------------------------------------------------------------------


def activity_streak(sess: Session, user_id: str) -> int:
    """Số ngày liên tiếp có hoạt động, tính tới hôm nay (hoặc hôm qua)."""
    stamps = sess.scalars(
        select(ActivityEvent.ts).where(ActivityEvent.user_id == user_id)
    ).all()
    if not stamps:
        return 0

    days = sorted({stamp.date() for stamp in stamps}, reverse=True)
    today = utcnow().date()
    if days[0] not in {today, today - timedelta(days=1)}:
        return 0

    streak = 1
    for current, previous in itertools.pairwise(days):
        if current - previous == timedelta(days=1):
            streak += 1
        else:
            break
    return streak


# ---------------------------------------------------------------------------
# Huy hiệu
# ---------------------------------------------------------------------------


def _badge_earned(sess: Session, user_id: str, rule: dict[str, Any]) -> bool:
    kind = str(rule.get("type", ""))
    count = int(rule.get("count", 1) or 1)

    if kind == "LESSON_COMPLETED":
        total = sess.scalar(
            select(func.count())
            .select_from(LessonCompletion)
            .where(LessonCompletion.student_id == user_id)
        )
        return (total or 0) >= count
    if kind == "QUIZ_PASSED":
        total = sess.scalar(
            select(func.count())
            .select_from(QuizAttempt)
            .where(QuizAttempt.student_id == user_id, QuizAttempt.passed.is_(True))
        )
        return (total or 0) >= count
    if kind == "STREAK":
        return activity_streak(sess, user_id) >= count
    return False


def evaluate_badges(sess: Session, user_id: str) -> list[Badge]:
    """Xét toàn bộ huy hiệu; trả về những huy hiệu vừa được cấp."""
    owned = set(
        sess.scalars(
            select(UserBadge.badge_id).where(UserBadge.user_id == user_id)
        ).all()
    )
    awarded: list[Badge] = []
    for badge in sess.scalars(select(Badge)).all():
        if badge.id in owned:
            continue
        if _badge_earned(sess, user_id, dict(badge.rule or {})):
            sess.add(UserBadge(user_id=user_id, badge_id=badge.id))
            awarded.append(badge)
    if awarded:
        sess.flush()
    return awarded


def user_badges(sess: Session, user_id: str) -> list[dict[str, Any]]:
    rows = sess.execute(
        select(Badge, UserBadge.awarded_at)
        .join(UserBadge, UserBadge.badge_id == Badge.id)
        .where(UserBadge.user_id == user_id)
        .order_by(UserBadge.awarded_at.desc())
    ).all()
    return [
        {
            "code": badge.code,
            "name": badge.name,
            "icon": badge.icon,
            "description": badge.description,
            "awarded_at": awarded_at,
        }
        for badge, awarded_at in rows
    ]


# ---------------------------------------------------------------------------
# Leaderboard
# ---------------------------------------------------------------------------


def leaderboard(
    sess: Session, section_id: int, limit: int = 10
) -> list[dict[str, Any]]:
    student_ids = sess.scalars(
        select(Enrollment.student_id).where(Enrollment.section_id == section_id)
    ).all()
    if not student_ids:
        return []

    rows: list[dict[str, Any]] = []
    for student_id in student_ids:
        student = sess.get(User, student_id)
        if student is None:
            continue
        progress = section_progress(sess, student_id, section_id)
        rows.append(
            {
                "email": student.email,
                "user_id": student_id,
                "points": user_points(sess, student_id),
                "completed": progress["completed"],
                "percent": progress["percent"],
            }
        )

    rows.sort(key=lambda row: (-int(row["points"]), -int(row["completed"])))
    return rows[:limit]


def section_of_course(sess: Session, course_id: str) -> CourseSection | None:
    return sess.scalars(
        select(CourseSection)
        .where(CourseSection.course_id == course_id)
        .order_by(CourseSection.id)
    ).first()


def humanize_verb(verb: str) -> str:
    labels = {
        VERB_LESSON_COMPLETED: "hoàn thành bài học",
        VERB_QUIZ_SUBMITTED: "nộp bài quiz",
        VERB_FORUM_POSTED: "đăng bài thảo luận",
        VERB_LOGIN: "đăng nhập",
        VERB_ENROLLED: "ghi danh môn học",
    }
    return labels.get(verb, verb)


def as_date(value: datetime) -> str:
    return value.strftime("%d/%m/%Y %H:%M")
