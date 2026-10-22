from __future__ import annotations

from flask import Flask, current_app, g, request

from app.auth import decode_token
from app.errors import Unauthenticated
from app.store import get_store


def register_gate(app: Flask) -> None:
    """Register global before_request gate (Lớp 2: Mặc định từ chối).

    Requires a valid Bearer token for all requests, except the single
    allowlisted endpoint: POST /auth/login.
    """

    # Public endpoints that do NOT require authentication
    _PUBLIC_ENDPOINTS: frozenset[str] = frozenset(
        {
            "/auth/login",
            "/auth/register",
        }
    )

    @app.before_request
    def gate_check() -> None:
        # Allowlist: các endpoint công khai không cần JWT
        if request.method == "POST" and request.path in _PUBLIC_ENDPOINTS:
            return None

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            raise Unauthenticated("Authorization header missing or not Bearer")

        token = auth_header[len("Bearer ") :].strip()
        if not token:
            raise Unauthenticated("Bearer token is empty")

        secret = current_app.config.get("JWT_SECRET", "")
        payload = decode_token(token, secret)

        sub = payload.get("sub")
        if not sub or not isinstance(sub, str):
            raise Unauthenticated("Token subject is invalid")

        store = get_store()
        user = store.get_user_by_id(sub)
        if not user:
            raise Unauthenticated("User in token does not exist")

        # Save actor to g without exposing password_hash
        actor = {
            "id": user["id"],
            "email": user["email"],
            "role": user["role"],
        }
        g.current_user = actor
        g.actor = actor
        return None
