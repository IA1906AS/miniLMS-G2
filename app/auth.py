from __future__ import annotations

import time
from typing import Any

import bcrypt
import jwt

from app.errors import AccountLocked, InvalidCredentials, Unauthenticated
from app.store import Store, get_store


def hash_password(plain_password: str) -> str:
    """Hash password using bcrypt with cost >= 10."""
    return bcrypt.hashpw(
        plain_password.encode("utf-8"), bcrypt.gensalt(rounds=10)
    ).decode("utf-8")


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Verify password against bcrypt hash."""
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"), password_hash.encode("utf-8")
        )
    except Exception:
        return False


def encode_token(user_id: str, secret: str, ttl_seconds: int = 900) -> str:
    """Encode JWT token with HS256 containing only sub, iat, exp."""
    now = int(time.time())
    payload = {
        "sub": user_id,
        "iat": now,
        "exp": now + ttl_seconds,
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_token(token: str, secret: str) -> dict[str, Any]:
    """Decode and verify JWT token.

    Must specify algorithms=['HS256'] to prevent alg:none attacks.
    """
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            options={"require": ["exp", "iat", "sub"]},
        )
        return payload
    except (jwt.PyJWTError, Exception) as exc:
        raise Unauthenticated("Invalid, expired, or malformed token") from exc


def login(
    email: str,
    password: str,
    secret: str,
    ttl_seconds: int = 900,
    store: Store | None = None,
) -> dict[str, Any]:
    """Authenticate user with brute-force defense (Lớp 1 & Lớp 7).

    Returns identical error for non-existent email and wrong password.
    Locks account after 5 consecutive failures for 15 minutes.
    """
    if store is None:
        store = get_store()

    now = time.time()
    normalized_email = email.strip().lower()

    # 1. Check brute-force lockout (Lớp 7)
    if store.is_account_locked(normalized_email, now):
        raise AccountLocked("Account is temporarily locked")

    # 2. Check credentials
    user = store.get_user_by_email(normalized_email)
    if not user:
        store.record_login_failure(normalized_email, now)
        raise InvalidCredentials("Invalid email or password")

    if not verify_password(password, user["password_hash"]):
        store.record_login_failure(normalized_email, now)
        raise InvalidCredentials("Invalid email or password")

    # 3. Successful login resets failure counter
    store.record_login_success(normalized_email)

    # 4. Generate token containing only sub, iat, exp
    token = encode_token(user["id"], secret, ttl_seconds)
    return {
        "accessToken": token,
        "expiresIn": ttl_seconds,
    }
