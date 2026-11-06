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
}

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
    for key in ("UPLOAD_DIR", "MAIL_DIR", "MAIL_FROM", "SMTP_HOST", "SMTP_PORT",
                "SMTP_USER", "SMTP_PASSWORD"):
        if os.environ.get(key):
            cfg[key] = os.environ[key]
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

    @app.context_processor
    def inject_globals() -> dict[str, Any]:
        return {
            "current_user": current_user(),
            "role_labels": ROLE_LABELS,
        }

    return app
