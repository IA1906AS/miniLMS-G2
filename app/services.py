"""Lớp 4 - quyền trên từng đối tượng (object-level authorization).

File này KHÔNG import flask: service nhận ``actor`` là dict và tự ném lỗi
trong ``app.errors``. Nhờ vậy gỡ ``@require_role`` ở route vẫn bị chặn (A15).

Hợp đồng với ``app/store.py`` (Phần 1 phải cung cấp):

    get_course(course_id) -> dict | None      # {"id", "title", "instructorId"}
    get_enrollment(course_id, student_id) -> dict | None
    list_enrollments(course_id) -> list[dict]  # [{"courseId","studentId","score"}]
    set_score(course_id, student_id, score) -> None

Hợp đồng với ``app/audit.py`` (Phần 1 phải cung cấp):

    log(actor_id, action, resource, result, **extra) -> None
"""

from typing import Any

from . import audit, store
from .errors import Forbidden, NotFound, ValidationError

ADMIN = "ADMIN"
INSTRUCTOR = "INSTRUCTOR"
STUDENT = "STUDENT"
ROLES = (ADMIN, INSTRUCTOR, STUDENT)

SCORE_MIN = 0
SCORE_MAX = 10


def _role(actor: dict[str, Any]) -> str:
    role = actor.get("role")
    if role not in ROLES:
        raise Forbidden()
    return role


def _course_or_404(course_id: str) -> dict[str, Any]:
    course = store.get_course(course_id)
    if course is None:
        raise NotFound()
    return course


def _is_teacher_of(actor: dict[str, Any], course: dict[str, Any]) -> bool:
    return bool(actor["id"] == course["instructorId"])


def validate_score(score: Any) -> None:
    """Kiểm tra lại miền giá trị ở tầng service (lớp 5 yêu cầu)."""
    if isinstance(score, bool) or not isinstance(score, int | float):
        raise ValidationError()
    if not SCORE_MIN <= score <= SCORE_MAX:  # NaN cũng rơi vào đây
        raise ValidationError()


def authorize_read(actor: dict[str, Any], course_id: str) -> tuple[dict[str, Any], str]:
    """Trả (course, scope) với scope = "ALL" cho ADMIN/GV dạy môn, "OWN" cho SV."""
    course = _course_or_404(course_id)
    role = _role(actor)

    if role == ADMIN:
        return course, "ALL"
    if role == INSTRUCTOR:
        if not _is_teacher_of(actor, course):
            raise Forbidden()
        return course, "ALL"

    if store.get_enrollment(course["id"], actor["id"]) is None:
        raise Forbidden()
    return course, "OWN"


def authorize_update(actor: dict[str, Any], course_id: str) -> dict[str, Any]:
    """Chỉ GV dạy chính môn đó được sửa điểm; ADMIN và SV đều 403."""
    course = _course_or_404(course_id)
    if _role(actor) != INSTRUCTOR or not _is_teacher_of(actor, course):
        raise Forbidden()
    return course


def get_grades(actor: dict[str, Any], course_id: str) -> list[dict[str, Any]]:
    course, scope = authorize_read(actor, course_id)
    rows = store.list_enrollments(course["id"])

    if scope == "OWN":
        rows = [row for row in rows if row["studentId"] == actor["id"]]

    return [{"studentId": row["studentId"], "score": row["score"]} for row in rows]


def update_grade(
    actor: dict[str, Any], course_id: str, student_id: str, score: Any
) -> dict[str, Any]:
    course = authorize_update(actor, course_id)
    validate_score(score)

    enrollment = store.get_enrollment(course["id"], student_id)
    if enrollment is None:
        raise NotFound()

    old_score = enrollment["score"]
    store.set_score(course["id"], student_id, score)

    audit.log(
        actor["id"],
        "GRADE_UPDATE",
        f"course:{course['id']}/student:{student_id}",
        "ALLOW",
        oldScore=old_score,
        newScore=score,
    )

    return {"courseId": course["id"], "studentId": student_id, "score": score}
