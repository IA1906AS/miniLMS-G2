"""Xác thực: cookie httpOnly chứa JWT + phiên thu hồi được.

Spec mục "Ghi chú kỹ thuật":
  1. Auth middleware — route private kiểm tra JWT/session, decode role, redirect.
  2. Role enum ADMIN | INSTRUCTOR | STUDENT | GUEST.
  7. Redirect sau login: Admin → /admin/dashboard, GV/SV → /dashboard.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from functools import wraps
from typing import Any

import jwt
from flask import current_app, g, redirect, request, url_for
from werkzeug.wrappers import Response

from app.auth import decode_token, verify_password
from app.errors import AccountLocked, AppError
from app.store import get_store
from web.database import User, get_db
from web.models import (
    ROLE_ADMIN,
    ROLE_GUEST,
    ROLE_INSTRUCTOR,
    ROLE_STUDENT,
    USER_STATUS_ACTIVE,
    normalize_role,
    utcnow,
)

#: Đích chuyển hướng sau khi đăng nhập, theo spec dòng 151.
ROLE_HOME = {
    ROLE_ADMIN: "main.dashboard",
    ROLE_INSTRUCTOR: "main.dashboard",
    ROLE_STUDENT: "main.dashboard",
    ROLE_GUEST: "main.home",
}


class AuthError(Exception):
    """Vi phạm quy tắc xác thực."""


def _cookie_name() -> str:
    return str(current_app.config.get("AUTH_COOKIE_NAME", "lms_token"))


def _payload_from_cookie() -> dict[str, Any] | None:
    token = request.cookies.get(_cookie_name())
    if not token:
        return None
    try:
        return decode_token(token, current_app.config["JWT_SECRET"])
    except AppError:
        return None


def load_user_from_cookie() -> dict[str, Any] | None:
    """Đọc cookie, verify JWT, kiểm tra phiên trong DB còn hiệu lực."""
    payload = _payload_from_cookie()
    if payload is None:
        return None

    user_id = payload.get("sub")
    jti = payload.get("jti")
    if not isinstance(user_id, str) or not isinstance(jti, str):
        return None

    from web.models import AuthSession

    with get_db().session() as sess:
        row = sess.get(AuthSession, jti)
        if row is None or row.user_id != user_id:
            return None
        if row.revoked_at is not None or row.expires_at <= utcnow():
            return None
        user = sess.get(User, user_id)
        if user is None or user.status != USER_STATUS_ACTIVE:
            return None
        return {
            "id": user.id,
            "email": user.email,
            "role": normalize_role(user.role),
            "full_name": user.display_name,
            "avatar_path": user.avatar_path,
        }


def current_user() -> dict[str, Any] | None:
    if hasattr(g, "_lms_user"):
        cached: dict[str, Any] | None = g._lms_user
        return cached
    user = load_user_from_cookie()
    g._lms_user = user
    return user


def current_role() -> str:
    user = current_user()
    return user["role"] if user else ROLE_GUEST


# ---------------------------------------------------------------------------
# Guard
# ---------------------------------------------------------------------------


def login_required(view: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(view)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        if current_user() is None:
            return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))
        return view(*args, **kwargs)

    return wrapper


def role_required(*roles: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Chỉ cho phép các vai trò liệt kê. Chưa đăng nhập → về /login."""

    def decorator(view: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(view)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            user = current_user()
            if user is None:
                return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))
            if user["role"] not in roles:
                from flask import abort

                abort(403)
            return view(*args, **kwargs)

        return wrapper

    return decorator


admin_required = role_required(ROLE_ADMIN)
instructor_required = role_required(ROLE_INSTRUCTOR)
student_required = role_required(ROLE_STUDENT)


def require_roles(*roles: str) -> dict[str, Any]:
    """Dùng trong route đã có ``login_required``: trả actor hoặc abort(403)."""
    from flask import abort

    actor = current_user()
    if actor is None:
        abort(403)
    if roles and actor["role"] not in roles:
        abort(403)
    return actor


def can_manage_course(actor: dict[str, Any] | None, course: Any) -> bool:
    """Spec dòng 147: GV chỉ CRUD khoá có instructorId === currentUser.id.

    Dòng 150: Admin bypass mọi ownership check.
    """
    if actor is None:
        return False
    if actor["role"] == ROLE_ADMIN:
        return True
    return bool(actor["role"] == ROLE_INSTRUCTOR and course.instructor_id == actor["id"])


# ---------------------------------------------------------------------------
# Đăng nhập / đăng xuất
# ---------------------------------------------------------------------------


def authenticate(email: str, password: str) -> dict[str, Any] | None:
    """Kiểm tra email + mật khẩu, có chống brute-force."""
    store = get_store()
    now = time.time()
    normalized = email.strip().lower()

    if store.is_account_locked(normalized, now):
        raise AccountLocked("Tài khoản tạm thời bị khoá do sai quá nhiều lần.")

    with get_db().session() as sess:
        user = sess.query(User).filter(User.email == normalized).one_or_none()
        if user is None or not verify_password(password, user.password_hash):
            store.record_login_failure(normalized, now)
            return None
        if user.status != USER_STATUS_ACTIVE:
            raise AuthError("Tài khoản đã bị khoá. Liên hệ quản trị viên.")
        actor = {
            "id": user.id,
            "email": user.email,
            "role": normalize_role(user.role),
        }

    store.record_login_success(normalized)
    return actor


def attach_session(response: Response, user_id: str) -> Response:
    """Tạo phiên trong DB rồi gắn JWT (có jti) vào cookie httpOnly."""
    import uuid

    from web.models import AuthSession

    ttl = int(current_app.config.get("TOKEN_TTL_SECONDS", 86400))
    jti = uuid.uuid4().hex

    with get_db().session() as sess:
        from datetime import timedelta

        sess.add(
            AuthSession(
                id=jti,
                user_id=user_id,
                expires_at=utcnow() + timedelta(seconds=ttl),
            )
        )

    now = int(time.time())
    token = jwt.encode(
        {"sub": user_id, "iat": now, "exp": now + ttl, "jti": jti},
        current_app.config["JWT_SECRET"],
        algorithm="HS256",
    )
    response.set_cookie(
        _cookie_name(),
        token,
        max_age=ttl,
        httponly=True,
        samesite="Lax",
        secure=bool(current_app.config.get("SESSION_COOKIE_SECURE", False)),
        path="/",
    )
    return response


def clear_session(response: Response) -> Response:
    """Thu hồi phiên trong DB rồi xoá cookie."""
    from web.models import AuthSession

    payload = _payload_from_cookie()
    if payload is not None:
        jti = payload.get("jti")
        if isinstance(jti, str):
            with get_db().session() as sess:
                row = sess.get(AuthSession, jti)
                if row is not None and row.revoked_at is None:
                    row.revoked_at = utcnow()
    response.delete_cookie(_cookie_name(), path="/")
    return response


def home_url_for(role: str) -> str:
    return url_for(ROLE_HOME.get(role, ROLE_HOME[ROLE_GUEST]))
