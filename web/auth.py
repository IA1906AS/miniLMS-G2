"""Xác thực cho giao diện web: cookie httpOnly chứa JWT (dùng lại app.auth)."""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any

from flask import current_app, g, redirect, request, url_for
from werkzeug.wrappers import Response

from app.auth import decode_token, encode_token, verify_password
from app.errors import AppError
from web.database import User, get_db, normalize_role


def _cookie_name() -> str:
    return str(current_app.config.get("AUTH_COOKIE_NAME", "lms_token"))


def load_user_from_cookie() -> dict[str, Any] | None:
    """Đọc cookie, verify JWT HS256, trả actor {"id","email","role"} hoặc None."""
    token = request.cookies.get(_cookie_name())
    if not token:
        return None

    try:
        payload = decode_token(token, current_app.config["JWT_SECRET"])
    except AppError:
        return None

    user_id = payload.get("sub")
    if not isinstance(user_id, str):
        return None

    with get_db().session() as sess:
        user = sess.get(User, user_id)
        if user is None:
            return None
        return {"id": user.id, "email": user.email, "role": normalize_role(user.role)}


def current_user() -> dict[str, Any] | None:
    cached: dict[str, Any] | None = None
    if hasattr(g, "_lms_user"):
        cached = g._lms_user
        return cached
    user = load_user_from_cookie()
    g._lms_user = user
    return user


def login_required(view: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(view)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        if current_user() is None:
            return redirect(url_for("web.login", next=request.path))
        return view(*args, **kwargs)

    return wrapper


def authenticate(email: str, password: str) -> dict[str, Any] | None:
    """Kiểm tra email + mật khẩu (bcrypt). Sai thì trả None, không lộ bên nào sai."""
    with get_db().session() as sess:
        user = (
            sess.query(User).filter(User.email == email.strip().lower()).one_or_none()
        )
        if user is None or not verify_password(password, user.password_hash):
            return None
        return {"id": user.id, "email": user.email, "role": normalize_role(user.role)}


def attach_session(response: Response, user_id: str) -> Response:
    ttl = int(current_app.config.get("TOKEN_TTL_SECONDS", 900))
    token = encode_token(user_id, current_app.config["JWT_SECRET"], ttl)
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
    response.delete_cookie(_cookie_name(), path="/")
    return response
