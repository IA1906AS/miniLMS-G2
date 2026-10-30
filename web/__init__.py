"""Giao diện web miniLMS (Flask + Jinja2 + SQLite).

Chạy: ``flask --app webapp run``

Tách khỏi package ``app/``: phần đó là API chấm thi (in-memory theo đề bài),
còn giao diện này dùng SQLite qua SQLAlchemy.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from flask import Flask

from web.database import ROLE_LABELS, Database

DEFAULT_CONFIG: dict[str, Any] = {
    "TOKEN_TTL_SECONDS": 3600,
    "AUTH_COOKIE_NAME": "lms_token",
    "SEED_PATH": "seed.json",
}


def _instance_dir() -> Path:
    instance = Path(__file__).resolve().parent.parent / "instance"
    instance.mkdir(parents=True, exist_ok=True)
    return instance


def _default_database_url() -> str:
    return f"sqlite:///{(_instance_dir() / 'lms.db').as_posix()}"


def create_web_app(config: dict[str, Any] | None = None) -> Flask:
    """Application factory cho giao diện web.

    Thứ tự ưu tiên: mặc định -> biến môi trường -> ``config`` (ghi đè tất cả).
    """
    app = Flask(__name__)

    cfg: dict[str, Any] = dict(DEFAULT_CONFIG)
    cfg["JWT_SECRET"] = os.environ.get("JWT_SECRET")
    cfg["DATABASE_URL"] = os.environ.get("DATABASE_URL") or _default_database_url()
    cfg["UPLOAD_ROOT"] = os.environ.get("UPLOAD_ROOT") or str(
        _instance_dir() / "uploads"
    )
    cfg["SECRET_KEY"] = os.environ.get("SECRET_KEY")
    if config:
        cfg.update(config)

    secret = cfg.get("JWT_SECRET")
    if not secret or not isinstance(secret, str) or len(secret) < 32:
        raise RuntimeError("JWT_SECRET là bắt buộc và phải dài ít nhất 32 ký tự.")

    app.config.update(cfg)
    # ``flash`` cần secret key; mặc định dùng luôn JWT_SECRET để dev không phải
    # cấu hình thêm, nhưng vẫn cho phép ghi đè bằng SECRET_KEY riêng.
    app.secret_key = app.config.get("SECRET_KEY") or secret

    upload_root = Path(str(app.config["UPLOAD_ROOT"]))
    upload_root.mkdir(parents=True, exist_ok=True)
    app.config["UPLOAD_ROOT"] = str(upload_root)

    db = Database(str(app.config["DATABASE_URL"]))
    db.create_all()
    seeded = db.seed_if_empty(str(app.config["SEED_PATH"]))
    app.extensions["lms_db"] = db
    app.extensions["lms_seeded"] = seeded

    from web.auth import current_user
    from web.blueprints.catalog import bp as catalog_bp
    from web.views import bp

    app.register_blueprint(bp)
    app.register_blueprint(catalog_bp)

    @app.context_processor
    def inject_globals() -> dict[str, Any]:
        return {"current_user": current_user(), "role_labels": ROLE_LABELS}

    return app
