"""Routes: Auth, User management, Grades.

Router mỏng: mọi kiểm tra quyền nằm ở lớp 2 (gate), lớp 3 (guards) và lớp 4
(services) để gỡ một lớp vẫn còn lớp khác chặn.

Public endpoints (không cần JWT):
  POST /auth/login          - Đăng nhập, trả về accessToken
  POST /auth/register       - Đăng ký (STUDENT hoặc INSTRUCTOR)
  POST /auth/forgot-password - Yêu cầu reset token (giả lập gửi email)
  POST /auth/reset-password - Đặt mật khẩu mới bằng reset token

Protected endpoints (cần JWT):
  GET  /me                           - Xem thông tin bản thân
  POST /auth/change-password         - Đổi mật khẩu (biết mật khẩu cũ)
  POST /auth/admin/users             - ADMIN tạo user mới (kể cả ADMIN)
  GET  /courses/<id>/grades          - Xem điểm
  PUT  /courses/<id>/grades/<sid>    - Cập nhật điểm (INSTRUCTOR)
"""

from __future__ import annotations

from typing import Any

from flask import Blueprint, current_app, g, jsonify, request

from app.auth import login
from app.errors import ValidationError
from app.guards import require_role
from app.schemas import parse_score_update
from app.services import authorize_update, get_grades, update_grade
from app.user_services import (
    admin_create_user,
    change_password,
    forgot_password,
    register_user,
    reset_password,
)

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


# ---------------------------------------------------------------------------
# Auth: Register
# ---------------------------------------------------------------------------


@bp.route("/auth/register", methods=["POST"])
def auth_register() -> tuple[Any, int]:
    """Đăng ký tài khoản mới (STUDENT hoặc INSTRUCTOR).

    Body: {email, password, role}
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValidationError("Request body must be a JSON object")

    actor = register_user(
        email=data.get("email"),
        password=data.get("password"),
        role=data.get("role"),
    )
    return jsonify(actor), 201


# ---------------------------------------------------------------------------
# Auth: Forgot password
# ---------------------------------------------------------------------------


@bp.route("/auth/forgot-password", methods=["POST"])
def auth_forgot_password() -> tuple[Any, int]:
    """Yêu cầu reset token để đặt lại mật khẩu.

    Body: {email}
    Luôn trả về 200 để tránh user enumeration.
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValidationError("Request body must be a JSON object")

    result = forgot_password(email=data.get("email"))
    return jsonify(result), 200


# ---------------------------------------------------------------------------
# Auth: Reset password (dùng token từ forgot-password)
# ---------------------------------------------------------------------------


@bp.route("/auth/reset-password", methods=["POST"])
def auth_reset_password() -> tuple[Any, int]:
    """Đặt lại mật khẩu bằng reset token.

    Body: {resetToken, newPassword}
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValidationError("Request body must be a JSON object")

    result = reset_password(
        token=data.get("resetToken"),
        new_password=data.get("newPassword"),
    )
    return jsonify(result), 200


# ---------------------------------------------------------------------------
# Auth: Change password (cần JWT — biết mật khẩu cũ)
# ---------------------------------------------------------------------------


@bp.route("/auth/change-password", methods=["POST"])
def auth_change_password() -> tuple[Any, int]:
    """Đổi mật khẩu khi đã đăng nhập, yêu cầu mật khẩu cũ.

    Body: {oldPassword, newPassword}
    Header: Authorization: Bearer <token>
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValidationError("Request body must be a JSON object")

    result = change_password(
        actor=g.current_user,
        old_password=data.get("oldPassword"),
        new_password=data.get("newPassword"),
    )
    return jsonify(result), 200


# ---------------------------------------------------------------------------
# Admin: Create user (ADMIN only, cần JWT)
# ---------------------------------------------------------------------------


@bp.route("/auth/admin/users", methods=["POST"])
@require_role("ADMIN")
def auth_admin_create_user() -> tuple[Any, int]:
    """ADMIN tạo tài khoản mới với bất kỳ role nào.

    Body: {email, password, role}
    Header: Authorization: Bearer <ADMIN token>
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValidationError("Request body must be a JSON object")

    new_user = admin_create_user(
        actor=g.current_user,
        email=data.get("email"),
        password=data.get("password"),
        role=data.get("role"),
    )
    return jsonify(new_user), 201
