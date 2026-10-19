from __future__ import annotations

import contextlib
import os
from typing import Any

from flask import Flask

from app.errors import register_error_handlers
from app.gate import register_gate
from app.routes import bp
from app.store import init_store


def create_app(config: dict[str, Any] | None = None) -> Flask:
    """Application factory for LMS Flask app.

    Reloads seed and creates fresh state on each call. Config parameter
    overrides environment variables.
    """
    app = Flask(__name__)

    # 1. Defaults
    token_ttl = 900
    audit_path = "audit.log"
    seed_path = "seed.json"
    jwt_secret = os.environ.get("JWT_SECRET")

    # 2. Environment variables
    if "TOKEN_TTL_SECONDS" in os.environ:
        with contextlib.suppress(ValueError):
            token_ttl = int(os.environ["TOKEN_TTL_SECONDS"])

    if "AUDIT_LOG_PATH" in os.environ:
        audit_path = os.environ["AUDIT_LOG_PATH"]

    if "SEED_PATH" in os.environ:
        seed_path = os.environ["SEED_PATH"]

    app.config["JWT_SECRET"] = jwt_secret
    app.config["TOKEN_TTL_SECONDS"] = token_ttl
    app.config["AUDIT_LOG_PATH"] = audit_path
    app.config["SEED_PATH"] = seed_path

    # 3. Config dict overrides environment variables
    if config:
        app.config.update(config)

    # 4. Validate JWT_SECRET: required, >= 32 characters
    secret = app.config.get("JWT_SECRET")
    if not secret or not isinstance(secret, str) or len(secret) < 32:
        raise RuntimeError(
            "JWT_SECRET is required and must be at least 32 characters long."
        )

    # 5. Initialize fresh in-memory store from seed
    seed_file = app.config.get("SEED_PATH", "seed.json")
    store = init_store(seed_path=seed_file)
    app.config["STORE"] = store

    # 6. Register error handlers (Lớp 6)
    register_error_handlers(app)

    # 7. Register deny-by-default before_request gate (Lớp 2)
    register_gate(app)

    # 8. Register routes
    app.register_blueprint(bp)

    return app
