"""Route: 4 endpoint công khai + /me.

Router mỏng: mọi kiểm tra quyền nằm ở lớp 2 (gate), lớp 3 (guards) và lớp 4
(services) để gỡ một lớp vẫn còn lớp khác chặn.
"""

from __future__ import annotations

from typing import Any

from flask import Blueprint, current_app, g, jsonify, request

from app.auth import login
from app.errors import ValidationError
from app.guards import require_role
from app.schemas import parse_score_update
from app.services import authorize_update, get_grades, update_grade

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
    # g.current_user do gate.py đặt, chỉ gồm id, email, role
    return jsonify(g.current_user), 200


@bp.route("/courses/<course_id>/grades", methods=["GET"])
@require_role("ADMIN", "INSTRUCTOR", "STUDENT")
def route_get_grades(course_id: str) -> tuple[Any, int]:
    # Lớp 4: services tự kiểm tra ma trận quyền (404 môn trước, rồi 403).
    return jsonify(get_grades(g.current_user, course_id)), 200


@bp.route("/courses/<course_id>/grades/<student_id>", methods=["PUT"])
@require_role("INSTRUCTOR")
def route_update_grade(course_id: str, student_id: str) -> tuple[Any, int]:
    # Thứ tự: 401 (gate) -> 404 môn -> 403 -> 400 body -> 404 ghi danh.
    # Kiểm tra môn + quyền trước để 403 thắng 400 khi body cũng sai.
    authorize_update(g.current_user, course_id)
    data = parse_score_update(request.get_json(silent=True))
    result = update_grade(g.current_user, course_id, student_id, data["score"])
    return jsonify(result), 200
