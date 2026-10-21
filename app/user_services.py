"""User management services: register, reset password, change password.

File này KHÔNG import flask. Mọi lỗi được ném qua app.errors để
routes và gate vẫn bắt và trả về JSON chuẩn.

Quy tắc mật khẩu:
  - Tối thiểu 8 ký tự
  - Có ít nhất 1 chữ hoa, 1 chữ thường, 1 chữ số, 1 ký tự đặc biệt
"""

from __future__ import annotations

import re
import secrets
from typing import Any

from app.audit import log_event
from app.auth import hash_password, verify_password
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
        raise ValidationError(f"Mật khẩu phải có ít nhất {_PASSWORD_MIN_LENGTH} ký tự")
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
        raise ValidationError(f"Role không hợp lệ. Giá trị cho phép: {sorted(allowed)}")
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
# 3. Reset password — đặt lại mật khẩu khi đã đăng nhập hoặc do ADMIN thực hiện
# ---------------------------------------------------------------------------


def reset_password(
    actor: dict[str, Any],
    new_password: Any,
    target_user_id: Any = None,
    target_email: Any = None,
    store: Store | None = None,
) -> dict[str, Any]:
    """Đặt lại mật khẩu cho tài khoản.

    Quy tắc:
    - Phải đăng nhập (actor từ g.current_user do gate xác thực).
    - User thường (STUDENT/INSTRUCTOR): chỉ reset mật khẩu cho chính mình.
    - ADMIN: có quyền reset và đặt mật khẩu cho bất kỳ tài khoản nào.
    - Nếu là ADMIN và không truyền new_password, hệ thống tự sinh mật khẩu tạm thời.
    """
    if store is None:
        store = get_store()

    # Xác định user mục tiêu
    target_user: dict[str, Any] | None = None

    if target_user_id or target_email:
        # Nếu chỉ định tài khoản khác, phải có role ADMIN
        is_same_user = False
        if target_user_id and str(target_user_id).strip() == actor.get("id"):
            is_same_user = True
        if (
            target_email
            and str(target_email).strip().lower() == str(actor.get("email")).lower()
        ):
            is_same_user = True

        if not is_same_user and actor.get("role") != "ADMIN":
            raise Forbidden("Chỉ ADMIN mới có quyền reset mật khẩu cho tài khoản khác")

        if target_user_id:
            target_user = store.get_user_by_id(str(target_user_id).strip())
        elif target_email:
            target_user = store.get_user_by_email(str(target_email).strip().lower())

        if target_user is None:
            raise NotFound("Tài khoản không tồn tại")
    else:
        # Tự reset mật khẩu cho chính mình
        target_user = store.get_user_by_id(actor["id"])
        if target_user is None:
            raise NotFound("Tài khoản không tồn tại")

    # Xử lý mật khẩu mới
    if new_password is None or (
        isinstance(new_password, str) and not new_password.strip()
    ):
        if actor.get("role") == "ADMIN" and target_user["id"] != actor.get("id"):
            # ADMIN reset nhưng không truyền mật khẩu cụ thể -> tự sinh mật khẩu tạm
            new_password = "Reset@" + secrets.token_hex(4) + "A1"
        else:
            raise ValidationError("Mật khẩu mới là bắt buộc")
    else:
        _validate_password_strength(new_password)

    new_hash = hash_password(new_password)
    store.update_password(target_user["id"], new_hash)

    is_admin_action = actor.get("role") == "ADMIN" and target_user["id"] != actor.get(
        "id"
    )
    action_name = "ADMIN_RESET_PASSWORD" if is_admin_action else "RESET_PASSWORD"
    log_event(
        actor_id=actor["id"],
        action=action_name,
        resource=f"user:{target_user['id']}",
        result="ALLOW",
    )

    result: dict[str, Any] = {
        "message": "Mật khẩu đã được đặt lại thành công",
        "userId": target_user["id"],
        "email": target_user["email"],
    }
    if is_admin_action:
        result["newPassword"] = new_password

    return result


def admin_reset_password(
    actor: dict[str, Any],
    target_user_id: Any = None,
    target_email: Any = None,
    new_password: Any = None,
    store: Store | None = None,
) -> dict[str, Any]:
    """ADMIN đặt lại mật khẩu cho bất kỳ tài khoản nào.

    Kiểm tra quyền ADMIN ở service layer (defense-in-depth).
    """
    if store is None:
        store = get_store()

    if actor.get("role") != "ADMIN":
        raise Forbidden("Chỉ ADMIN mới có quyền reset mật khẩu cho tài khoản khác")

    if not target_user_id and not target_email:
        raise ValidationError("Cần cung cấp userId hoặc email của tài khoản cần reset")

    return reset_password(
        actor=actor,
        new_password=new_password,
        target_user_id=target_user_id,
        target_email=target_email,
        store=store,
    )


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
