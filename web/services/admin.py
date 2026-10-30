"""Quản trị người dùng, audit log, thống kê hệ thống."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.auth import hash_password
from web.models import (
    USER_STATUS_ACTIVE,
    USER_STATUS_LOCKED,
    AuditEvent,
    AuthSession,
    Enrollment,
    User,
    utcnow,
)
from web.services import activity


class AdminError(Exception):
    """Vi phạm quy tắc nghiệp vụ của khu vực quản trị."""


def record_audit(
    sess: Session,
    *,
    actor_id: str | None,
    action: str,
    resource: str,
    result: str = "ALLOW",
    detail: dict[str, Any] | None = None,
) -> AuditEvent:
    event = AuditEvent(
        actor_id=actor_id,
        action=action,
        resource=resource,
        result=result,
        detail=detail or {},
    )
    sess.add(event)
    sess.flush()
    return event


def list_users(
    sess: Session,
    *,
    q: str | None = None,
    role: str | None = None,
    status: str | None = None,
    page: int = 1,
    per_page: int = 20,
) -> dict[str, Any]:
    stmt = select(User)
    if q:
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(User.email).like(like), func.lower(User.full_name).like(like)
            )
        )
    if role:
        stmt = stmt.where(User.role == role)
    if status:
        stmt = stmt.where(User.status == status)

    total = sess.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    page = max(1, page)
    rows = sess.scalars(
        stmt.order_by(User.created_at.desc(), User.id)
        .offset((page - 1) * per_page)
        .limit(per_page)
    ).all()
    return {
        "items": rows,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": max(1, (total + per_page - 1) // per_page),
    }


def set_status(sess: Session, actor: dict[str, Any], user: User, status: str) -> User:
    if user.id == actor["id"]:
        raise AdminError("Bạn không thể tự khoá tài khoản của mình.")
    if status not in {USER_STATUS_ACTIVE, USER_STATUS_LOCKED}:
        raise AdminError("Trạng thái tài khoản không hợp lệ.")
    user.status = status
    if status == USER_STATUS_LOCKED:
        revoke_all_sessions(sess, user.id)
    sess.flush()
    record_audit(
        sess,
        actor_id=actor["id"],
        action="USER_STATUS_CHANGED",
        resource=f"user:{user.id}",
        detail={"status": status},
    )
    return user


def set_role(sess: Session, actor: dict[str, Any], user: User, role: str) -> User:
    allowed = {"ADMIN", "TEACHER", "STUDENT"}
    if role not in allowed:
        raise AdminError("Vai trò không hợp lệ.")
    if user.id == actor["id"] and role != "ADMIN":
        raise AdminError("Bạn không thể tự hạ quyền của mình.")
    user.role = role
    sess.flush()
    record_audit(
        sess,
        actor_id=actor["id"],
        action="USER_ROLE_CHANGED",
        resource=f"user:{user.id}",
        detail={"role": role},
    )
    return user


def reset_password(
    sess: Session, actor: dict[str, Any], user: User, new_password: str
) -> User:
    user.password_hash = hash_password(new_password)
    user.must_change_password = True
    revoke_all_sessions(sess, user.id)
    sess.flush()
    record_audit(
        sess,
        actor_id=actor["id"],
        action="USER_PASSWORD_RESET",
        resource=f"user:{user.id}",
    )
    return user


def user_detail(sess: Session, user: User) -> dict[str, Any]:
    enrollments = list(
        sess.scalars(select(Enrollment).where(Enrollment.student_id == user.id)).all()
    )
    sessions_count = (
        sess.scalar(
            select(func.count())
            .select_from(AuthSession)
            .where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
        )
        or 0
    )
    events = activity.recent_activity(sess, limit=10)
    return {
        "user": user,
        "enrollments": enrollments,
        "points": activity.user_points(sess, user.id),
        "badges": activity.user_badges(sess, user.id),
        "streak": activity.activity_streak(sess, user.id),
        "active_sessions": sessions_count,
        "recent_events": [e for e in events if e["email"] == user.email][:10],
    }


# ---------------------------------------------------------------------------
# Phiên đăng nhập
# ---------------------------------------------------------------------------


def create_session(
    sess: Session,
    user_id: str,
    *,
    ttl_seconds: int,
    ip: str | None = None,
    user_agent: str | None = None,
) -> str:
    from datetime import timedelta

    jti = uuid.uuid4().hex
    sess.add(
        AuthSession(
            id=jti,
            user_id=user_id,
            expires_at=utcnow() + timedelta(seconds=ttl_seconds),
            ip=(ip or "")[:64] or None,
            user_agent=(user_agent or "")[:255] or None,
        )
    )
    sess.flush()
    return jti


def session_is_valid(sess: Session, jti: str, user_id: str) -> bool:
    row = sess.get(AuthSession, jti)
    if row is None or row.user_id != user_id:
        return False
    if row.revoked_at is not None:
        return False
    return row.expires_at > utcnow()


def revoke_session(sess: Session, jti: str) -> None:
    row = sess.get(AuthSession, jti)
    if row is not None and row.revoked_at is None:
        row.revoked_at = utcnow()
        sess.flush()


def revoke_all_sessions(sess: Session, user_id: str) -> int:
    rows = sess.scalars(
        select(AuthSession).where(
            AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None)
        )
    ).all()
    for row in rows:
        row.revoked_at = utcnow()
    if rows:
        sess.flush()
    return len(rows)


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


def audit_log(
    sess: Session,
    *,
    actor_id: str | None = None,
    action: str | None = None,
    result: str | None = None,
    page: int = 1,
    per_page: int = 30,
) -> dict[str, Any]:
    stmt = select(AuditEvent)
    if actor_id:
        stmt = stmt.where(AuditEvent.actor_id == actor_id)
    if action:
        stmt = stmt.where(AuditEvent.action == action)
    if result:
        stmt = stmt.where(AuditEvent.result == result)

    total = sess.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    page = max(1, page)
    rows = sess.scalars(
        stmt.order_by(AuditEvent.ts.desc(), AuditEvent.id.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    ).all()
    return {
        "items": rows,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": max(1, (total + per_page - 1) // per_page),
    }


def audit_actions(sess: Session) -> list[str]:
    return list(
        sess.scalars(
            select(AuditEvent.action).distinct().order_by(AuditEvent.action)
        ).all()
    )
