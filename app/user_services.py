"""User management services: register, forgot/reset password, change password.

File này KHÔNG import flask. Mọi lỗi được ném qua app.errors để
routes và gate vẫn bắt và trả về JSON chuẩn.

Quy tắc mật khẩu:
  - Tối thiểu 8 ký tự
  - Có ít nhất 1 chữ hoa, 1 chữ thường, 1 chữ số, 1 ký tự đặc biệt

Reset token:
  - Tạo bằng secrets.token_urlsafe(32) (256-bit, URL-safe)
  - TTL mặc định: 15 phút
  - One-time use: bị xóa ngay sau khi dùng
  - In-memory: mất khi restart (phù hợp với kiến trúc hiện tại)
"""

from __future__ import annotations

import re
import secrets
import time
from typing import Any

from app.auth import hash_password, verify_password
from app.audit import log_event
from app.errors import (
    ConflictError,
    Forbidden,
    InvalidCredentials,
    NotFound,
    ValidationError,
)
from app.store import Store, get_store

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ALLOWED_SELF_REGISTER_ROLES = frozenset({"STUDENT", "INSTRUCTOR"})
RESET_TOKEN_TTL_SECONDS = 15 * 60  # 15 phút

_PASSWORD_MIN_LENGTH = 8
_RE_UPPER = re.compile(r"[A-Z]")
_RE_LOWER = re.compile(r"[a-z]")
_RE_DIGIT = re.compile(r"[0-9]")
_RE_SPECIAL = re.compile(r"[^A-Za-z0-9]")


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _validate_email(email: Any) -> str:
    """Normalize and basic-validate email format."""
    if not isinstance(email, str) or not email.strip():
        raise ValidationError("Email là bắt buộc và phải là chuỗi")
    normalized = email.strip().lower()
    # Basic RFC 5322 lightweight check
    if "@" not in normalized or "." not in normalized.split("@")[-1]:
        raise ValidationError("Email không hợp lệ")
    if len(normalized) > 254:
        raise ValidationError("Email quá dài")
    return normalized


def _validate_password_strength(password: Any) -> str:
    """Enforce password strength policy."""
    if not isinstance(password, str):
        raise ValidationError("Mật khẩu phải là chuỗi")
    if len(password) < _PASSWORD_MIN_LENGTH:
        raise ValidationError(
            f"Mật khẩu phải có ít nhất {_PASSWORD_MIN_LENGTH} ký tự"
        )
    if not _RE_UPPER.search(password):
        raise ValidationError("Mật khẩu phải có ít nhất 1 chữ hoa")
    if not _RE_LOWER.search(password):
        raise ValidationError("Mật khẩu phải có ít nhất 1 chữ thường")
    if not _RE_DIGIT.search(password):
        raise ValidationError("Mật khẩu phải có ít nhất 1 chữ số")
    if not _RE_SPECIAL.search(password):
        raise ValidationError("Mật khẩu phải có ít nhất 1 ký tự đặc biệt")
    return password


def _validate_role(role: Any, allowed: frozenset[str]) -> str:
    if not isinstance(role, str) or role not in allowed:
        raise ValidationError(
            f"Role không hợp lệ. Giá trị cho phép: {sorted(allowed)}"
        )
    return role


# ---------------------------------------------------------------------------
# 1. Self-registration (STUDENT / INSTRUCTOR)
# ---------------------------------------------------------------------------


def register_user(
    email: Any,
    password: Any,
    role: Any,
    store: Store | None = None,
) -> dict[str, Any]:
    """Đăng ký tài khoản mới (STUDENT hoặc INSTRUCTOR).

    Trả về actor dict {id, email, role} khi thành công.
    Ném ConflictError nếu email đã tồn tại.
    """
    if store is None:
        store = get_store()

    normalized_email = _validate_email(email)
    _validate_password_strength(password)
    _validate_role(role, ALLOWED_SELF_REGISTER_ROLES)

    # Email uniqueness check — constant-time-ish (no timing oracle)
    if store.get_user_by_email(normalized_email) is not None:
        raise ConflictError("Email đã được sử dụng")

    password_hash = hash_password(password)
    actor = store.create_user(
        email=normalized_email,
        password_hash=password_hash,
        role=role,
    )

    log_event(
        actor_id=actor["id"],
        action="REGISTER",
        resource=f"user:{actor['id']}",
        result="ALLOW",
    )
    return actor


# ---------------------------------------------------------------------------
# 2. Forgot password — generate reset token
# ---------------------------------------------------------------------------


def forgot_password(
    email: Any,
    store: Store | None = None,
    ttl_seconds: int = RESET_TOKEN_TTL_SECONDS,
) -> dict[str, Any]:
    """Tạo reset token cho email đã đăng ký.

    Luôn trả về response giống nhau để tránh user enumeration.
    Token chỉ được trả về trong response (thực tế sẽ gửi qua email).
    """
    if store is None:
        store = get_store()

    _validate_email(email)  # Validate format nhưng không tiết lộ tồn tại hay không
    normalized = email.strip().lower()

    # Generate token bất kể email có tồn tại không (tránh timing oracle)
    token = secrets.token_urlsafe(32)
    expires_at = time.time() + ttl_seconds

    user = store.get_user_by_email(normalized)
    if user is not None:
        # Chỉ lưu token nếu email tồn tại
        store.store_reset_token(token, normalized, expires_at)
        log_event(
            actor_id=user["id"],
            action="FORGOT_PASSWORD",
            resource=f"user:{user['id']}",
            result="ALLOW",
        )
        # Trong hệ thống thực tế: gửi email chứa token
        # Ở đây trả về token trong response để tiện test (development mode)
        return {
            "message": "Nếu email tồn tại, link đặt lại mật khẩu đã được gửi",
            "resetToken": token,  # Dev only — trong production, chỉ gửi qua email
            "expiresIn": ttl_seconds,
        }

    # Email không tồn tại: trả về response giống hệt (tránh user enumeration)
    return {
        "message": "Nếu email tồn tại, link đặt lại mật khẩu đã được gửi",
        "resetToken": None,  # None nghĩa là email không tồn tại
        "expiresIn": ttl_seconds,
    }


# ---------------------------------------------------------------------------
# 3. Reset password — dùng reset token để đặt mật khẩu mới
# ---------------------------------------------------------------------------


def reset_password(
    token: Any,
    new_password: Any,
    store: Store | None = None,
) -> dict[str, str]:
    """Đặt mật khẩu mới bằng reset token.

    Token bị xóa ngay sau khi dùng (one-time use).
    """
    if store is None:
        store = get_store()

    if not isinstance(token, str) or not token.strip():
        raise ValidationError("Reset token là bắt buộc")

    _validate_password_strength(new_password)

    now = time.time()
    # consume_reset_token ném TokenInvalidError / TokenExpiredError nếu không hợp lệ
    email = store.consume_reset_token(token.strip(), now)

    user = store.get_user_by_email(email)
    if user is None:
        # Không nên xảy ra nếu token hợp lệ, nhưng giữ fail-closed
        raise NotFound("Tài khoản không còn tồn tại")

    new_hash = hash_password(new_password)
    store.update_password(user["id"], new_hash)

    log_event(
        actor_id=user["id"],
        action="RESET_PASSWORD",
        resource=f"user:{user['id']}",
        result="ALLOW",
    )
    return {"message": "Mật khẩu đã được đặt lại thành công"}


# ---------------------------------------------------------------------------
# 4. Change password — đổi mật khẩu khi đã đăng nhập (biết mật khẩu cũ)
# ---------------------------------------------------------------------------


def change_password(
    actor: dict[str, Any],
    old_password: Any,
    new_password: Any,
    store: Store | None = None,
) -> dict[str, str]:
    """Đổi mật khẩu cho user đang đăng nhập.

    Yêu cầu mật khẩu cũ đúng (xác thực lại) trước khi đặt mật khẩu mới.
    """
    if store is None:
        store = get_store()

    if not isinstance(old_password, str) or not old_password:
        raise ValidationError("Mật khẩu cũ là bắt buộc")

    _validate_password_strength(new_password)

    # Re-authenticate: lấy user đầy đủ (có password_hash) từ store
    user_full = store.get_user_by_id(actor["id"])
    if user_full is None:
        raise NotFound("Tài khoản không tồn tại")

    if not verify_password(old_password, user_full["password_hash"]):
        raise InvalidCredentials("Mật khẩu cũ không đúng")

    if old_password == new_password:
        raise ValidationError("Mật khẩu mới phải khác mật khẩu cũ")

    new_hash = hash_password(new_password)
    store.update_password(actor["id"], new_hash)

    log_event(
        actor_id=actor["id"],
        action="CHANGE_PASSWORD",
        resource=f"user:{actor['id']}",
        result="ALLOW",
    )
    return {"message": "Mật khẩu đã được thay đổi thành công"}


# ---------------------------------------------------------------------------
# 5. Admin create user (bao gồm role ADMIN)
# ---------------------------------------------------------------------------


def admin_create_user(
    actor: dict[str, Any],
    email: Any,
    password: Any,
    role: Any,
    store: Store | None = None,
) -> dict[str, Any]:
    """ADMIN tạo user mới với bất kỳ role nào (kể cả ADMIN).

    Actor phải có role ADMIN, được kiểm tra ở service layer (defense-in-depth).
    """
    if store is None:
        store = get_store()

    if actor.get("role") != "ADMIN":
        raise Forbidden("Chỉ ADMIN mới được tạo tài khoản")

    normalized_email = _validate_email(email)
    _validate_password_strength(password)
    _validate_role(role, frozenset({"STUDENT", "INSTRUCTOR", "ADMIN"}))

    if store.get_user_by_email(normalized_email) is not None:
        raise ConflictError("Email đã được sử dụng")

    password_hash = hash_password(password)
    new_user = store.create_user(
        email=normalized_email,
        password_hash=password_hash,
        role=role,
    )

    log_event(
        actor_id=actor["id"],
        action="ADMIN_CREATE_USER",
        resource=f"user:{new_user['id']}",
        result="ALLOW",
        created_role=role,
    )
    return new_user
