"""Giao diện web miniLMS (Flask + Jinja2 + SQLite).

Chạy: ``flask --app webapp run```

Tách khỏi package ``app/``: phần đó là API chấm thi (in-memory theo đề bài),
còn giao diện này dùng SQLite qua SQLAlchemy.

Kiến trúc: ``web.models`` (ORM) + ``web.database`` (engine/seed) +
``web.auth`` (JWT + guard) + ``web.blueprints/*`` (route theo vai trò).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from flask import Flask

from web.database import Database
from web.models import ROLE_LABELS

DEFAULT_CONFIG: dict[str, Any] = {
    "TOKEN_TTL_SECONDS": 3600,
    "AUTH_COOKIE_NAME": "lms_token",
    "SEED_PATH": "seed.json",
    "UPLOAD_DIR": "instance/uploads",
    "MAIL_DIR": "instance/mail",
    "MAIL_FROM": "no-reply@minilms.local",
    "RESET_TOKEN_TTL_MINUTES": 30,
    # 25MB: cho phép tệp bài nộp + request overhead.
    "MAX_CONTENT_LENGTH": 25 * 1024 * 1024,
    # URL gốc dùng để dựng link trong email (không lấy từ Host header).
    "PUBLIC_BASE_URL": "http://127.0.0.1:8888",
    "SESSION_COOKIE_SECURE": False,
}

_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _install_security_hooks(app: Flask) -> None:
    """Chống CSRF (kiểm tra Origin/Referer) + gắn security header."""
    from urllib.parse import urlsplit

    from flask import abort, request

    @app.before_request
    def _csrf_origin_check() -> None:
        if request.method not in _UNSAFE_METHODS:
            return
        source = request.headers.get("Origin") or request.headers.get("Referer")
        if not source:
            # Trình duyệt hiện đại luôn gửi Origin cho POST cross-site;
            # thiếu cả hai thường là client không phải trình duyệt (test, curl).
            return
        allowed = {request.host, urlsplit(str(app.config["PUBLIC_BASE_URL"])).netloc}
        if source == "null" or urlsplit(source).netloc not in allowed:
            abort(403)

    @app.after_request
    def _security_headers(response: Any) -> Any:
        headers = response.headers
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("X-Frame-Options", "DENY")
        headers.setdefault("Referrer-Policy", "same-origin")
        headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline'; frame-ancestors 'none'; form-action 'self'; "
            "base-uri 'self'; object-src 'none'",
        )
        return response


WEB_DIR = Path(__file__).resolve().parent


def _default_database_url() -> str:
    instance = WEB_DIR.parent / "instance"
    instance.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{(instance / 'lms.db').as_posix()}"


def create_web_app(config: dict[str, Any] | None = None) -> Flask:
    """Application factory cho giao diện web.

    Thứ tự ưu tiên: mặc định -> biến môi trường -> ``config`` (ghi đè tất cả).
    """
    app = Flask(
        __name__,
        template_folder=str(WEB_DIR / "templates"),
        static_folder=str(WEB_DIR / "static"),
    )

    cfg: dict[str, Any] = dict(DEFAULT_CONFIG)
    cfg["JWT_SECRET"] = os.environ.get("JWT_SECRET")
    cfg["DATABASE_URL"] = os.environ.get("DATABASE_URL") or _default_database_url()
    for key in (
        "UPLOAD_DIR",
        "MAIL_DIR",
        "MAIL_FROM",
        "SMTP_HOST",
        "SMTP_PORT",
        "SMTP_USER",
        "SMTP_PASSWORD",
        "PUBLIC_BASE_URL",
    ):
        if os.environ.get(key):
            cfg[key] = os.environ[key]
    if os.environ.get("SESSION_COOKIE_SECURE"):
        cfg["SESSION_COOKIE_SECURE"] = os.environ["SESSION_COOKIE_SECURE"].lower() in {"1", "true", "yes"}
    if config:
        cfg.update(config)

    secret = cfg.get("JWT_SECRET")
    if not secret or not isinstance(secret, str) or len(secret) < 32:
        raise RuntimeError("JWT_SECRET là bắt buộc và phải dài ít nhất 32 ký tự.")

    app.config.update(cfg)
    app.config["SECRET_KEY"] = app.config["JWT_SECRET"]

    db = Database(str(app.config["DATABASE_URL"]))
    db.create_all()
    seeded = db.seed_if_empty(str(app.config["SEED_PATH"]))
    app.extensions["lms_db"] = db
    app.extensions["lms_seeded"] = seeded

    from web.auth import current_user
    from web.blueprints.admin import bp as admin_bp
    from web.blueprints.api import bp as api_bp
    from web.blueprints.auth import bp as auth_bp
    from web.blueprints.files import bp as files_bp
    from web.blueprints.instructor import bp as instructor_bp
    from web.blueprints.main import bp as main_bp
    from web.blueprints.quiz import bp as quiz_bp
    from web.blueprints.student import bp as student_bp

    app.register_blueprint(api_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(files_bp)
    app.register_blueprint(student_bp)
    app.register_blueprint(quiz_bp)
    app.register_blueprint(instructor_bp)
    app.register_blueprint(admin_bp)
    _install_security_hooks(app)

    @app.template_filter("safe_url")
    def _safe_url(value: Any) -> str:
        """Chỉ cho phép http(s) hoặc đường dẫn nội bộ — chặn ``javascript:``/``data:``."""
        from urllib.parse import urlsplit

        url = str(value or "").strip()
        if url.startswith("/") and not url.startswith("//"):
            return url
        if urlsplit(url).scheme.lower() in {"http", "https"}:
            return url
        return "#"

    @app.context_processor
    def inject_globals() -> dict[str, Any]:
        return {
            "current_user": current_user(),
            "role_labels": ROLE_LABELS,
        }

    return app
