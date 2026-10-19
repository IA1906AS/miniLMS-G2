"""Route của 4 endpoint (2 route điểm + /me).

Router mỏng: mọi kiểm tra quyền nằm ở lớp 2 (gate), lớp 3 (guards) và lớp 4
(services) để gỡ một lớp vẫn còn lớp khác chặn.

Thứ tự kiểm tra của PUT: 401 (gate) -> 404 môn -> 403 -> 400 body -> 404 ghi danh.
"""

from typing import Any

from flask import Blueprint, Response, g, jsonify, request

from . import schemas, services
from .guards import require_role

bp = Blueprint("lms", __name__)


@bp.get("/me")
def me() -> Response:
    actor: dict[str, Any] = g.actor
    return jsonify({"id": actor["id"], "email": actor["email"], "role": actor["role"]})


@bp.get("/courses/<course_id>/grades")
@require_role("ADMIN", "INSTRUCTOR", "STUDENT")
def get_course_grades(course_id: str) -> Response:
    return jsonify(services.get_grades(g.actor, course_id))


@bp.put("/courses/<course_id>/grades/<student_id>")
@require_role("INSTRUCTOR")
def put_student_grade(course_id: str, student_id: str) -> Response:
    # 404 môn + 403 trước, để 403 thắng 400 khi body cũng sai.
    services.authorize_update(g.actor, course_id)
    data = schemas.parse_score_update(request.get_json(silent=True))
    return jsonify(services.update_grade(g.actor, course_id, student_id, data["score"]))
