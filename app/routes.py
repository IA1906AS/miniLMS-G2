from __future__ import annotations

from typing import Any

from flask import Blueprint, current_app, g, jsonify, request

from app.auth import login
from app.errors import ValidationError
from app.guards import require_role

bp = Blueprint("routes", __name__)


@bp.route("/auth/login", methods=["POST"])
def auth_login() -> tuple[Any, int]:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValidationError("Request body must be a JSON object")

    email = data.get("email")
    password = data.get("password")
    if not isinstance(email, str) or not isinstance(password, str):
        raise ValidationError("Email and password are required")

    secret = current_app.config["JWT_SECRET"]
    ttl = current_app.config.get("TOKEN_TTL_SECONDS", 900)

    result = login(email=email, password=password, secret=secret, ttl_seconds=ttl)
    return jsonify(result), 200


@bp.route("/me", methods=["GET"])
def get_me() -> tuple[Any, int]:
    # g.current_user was set in gate.py and only contains id, email, role
    return jsonify(g.current_user), 200


# Stubs for course endpoints (to be fully integrated with Person B's services.py)
@bp.route("/courses/<course_id>/grades", methods=["GET"])
def route_get_grades(course_id: str) -> tuple[Any, int]:
    try:
        from app.services import get_grades  # type: ignore[import-not-found]

        grades = get_grades(g.current_user, course_id)
        return jsonify(grades), 200
    except ImportError:
        return jsonify({"error": "NOT_IMPLEMENTED"}), 501


@bp.route("/courses/<course_id>/grades/<student_id>", methods=["PUT"])
@require_role("INSTRUCTOR")
def route_update_grade(course_id: str, student_id: str) -> tuple[Any, int]:
    try:
        from app.services import update_grade

        data = request.get_json(silent=True)
        if not isinstance(data, dict) or "score" not in data:
            raise ValidationError("score is required")
        res = update_grade(g.current_user, course_id, student_id, data["score"])
        return jsonify(res), 200
    except ImportError:
        return jsonify({"error": "NOT_IMPLEMENTED"}), 501
