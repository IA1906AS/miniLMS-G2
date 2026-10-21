from __future__ import annotations

from typing import TYPE_CHECKING, Any

from flask import Flask, current_app, g, jsonify, request
from werkzeug.exceptions import HTTPException

if TYPE_CHECKING:
    pass


class AppError(Exception):
    status_code: int = 500
    error_code: str = "INTERNAL_ERROR"

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.error_code)


class ValidationError(AppError):
    status_code: int = 400
    error_code: str = "VALIDATION_ERROR"


class InvalidCredentials(AppError):
    status_code: int = 401
    error_code: str = "INVALID_CREDENTIALS"


class Unauthenticated(AppError):
    status_code: int = 401
    error_code: str = "UNAUTHENTICATED"


class Forbidden(AppError):
    status_code: int = 403
    error_code: str = "FORBIDDEN"


class NotFound(AppError):
    status_code: int = 404
    error_code: str = "NOT_FOUND"


class AccountLocked(AppError):
    status_code: int = 429
    error_code: str = "ACCOUNT_LOCKED"


class ConflictError(AppError):
    status_code: int = 409
    error_code: str = "CONFLICT"


class TokenExpiredError(AppError):
    status_code: int = 410
    error_code: str = "TOKEN_EXPIRED"


class TokenInvalidError(AppError):
    status_code: int = 400
    error_code: str = "INVALID_RESET_TOKEN"


def _record_audit_403() -> None:
    try:
        from app.audit import log_audit

        audit_path = current_app.config.get("AUDIT_LOG_PATH", "audit.log")
        actor = getattr(g, "current_user", None)
        actor_id = actor.get("id") if isinstance(actor, dict) else None
        action = request.method
        resource = request.path
        log_audit(
            audit_log_path=audit_path,
            actor_id=actor_id,
            action=action,
            resource=resource,
            result="FORBIDDEN",
        )
    except Exception:
        pass


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(AppError)
    def handle_app_error(exc: AppError) -> tuple[Any, int]:
        if exc.status_code == 403:
            _record_audit_403()
        return jsonify({"error": exc.error_code}), exc.status_code

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc: HTTPException) -> tuple[Any, int]:
        code = exc.code or 500
        if code == 400:
            error_code = "VALIDATION_ERROR"
        elif code == 401:
            error_code = "UNAUTHENTICATED"
        elif code == 403:
            _record_audit_403()
            error_code = "FORBIDDEN"
        elif code == 404:
            error_code = "NOT_FOUND"
        elif code == 405:
            error_code = "METHOD_NOT_ALLOWED"
        elif code == 409:
            error_code = "CONFLICT"
        elif code == 410:
            error_code = "TOKEN_EXPIRED"
        elif code == 429:
            error_code = "ACCOUNT_LOCKED"
        else:
            error_code = "INTERNAL_ERROR"
        return jsonify({"error": error_code}), code

    @app.errorhandler(Exception)
    def handle_unexpected_error(exc: Exception) -> tuple[Any, int]:
        # Fail-closed: Never leak stack trace or internal exception details
        return jsonify({"error": "INTERNAL_ERROR"}), 500
