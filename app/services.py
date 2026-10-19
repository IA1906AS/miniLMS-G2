"""Lớp 4 - quyền trên từng đối tượng (object-level authorization).

File này KHÔNG import flask: service nhận ``actor`` là dict và tự ném lỗi trong
``app.errors``. Nhờ vậy gỡ ``@require_role`` ở route thì service vẫn chặn (A15).

Dùng ``Store`` của Phần 1 qua ``app.store.get_store()``:
    get_course(course_id) / get_enrollment(course_id, student_id)
    get_course_enrollments(course_id) / update_score(course_id, student_id, score)
"""

from __future__ import annotations

from typing import Any

from app.audit import log_event
from app.errors import Forbidden, NotFound, ValidationError
from app.store import Store, get_store

ADMIN = "ADMIN"
INSTRUCTOR = "INSTRUCTOR"
STUDENT = "STUDENT"
ROLES = (ADMIN, INSTRUCTOR, STUDENT)

SCORE_MIN = 0
SCORE_MAX = 10


def _db() -> Store:
    return get_store()


def _role(actor: dict[str, Any]) -> str:
    role = actor.get("role")
    if role not in ROLES:
        raise Forbidden("Vai trò không hợp lệ")
    return str(role)


def _course_or_404(course_id: str) -> dict[str, Any]:
    course = _db().get_course(course_id)
    if course is None:
        raise NotFound("Môn học không tồn tại")
    return dict(course)


def _is_teacher_of(actor: dict[str, Any], course: dict[str, Any]) -> bool:
    return bool(actor["id"] == course["instructorId"])


def validate_score(score: Any) -> None:
    """Kiểm tra lại miền giá trị ở tầng service (lớp 5 yêu cầu)."""
    if isinstance(score, bool) or not isinstance(score, int | float):
        raise ValidationError("score phải là số")
    if not SCORE_MIN <= score <= SCORE_MAX:  # NaN cũng rơi vào đây
        raise ValidationError("score phải trong [0, 10]")


def authorize_read(actor: dict[str, Any], course_id: str) -> tuple[dict[str, Any], str]:
    """Trả (course, scope): scope = "ALL" cho ADMIN/GV dạy môn, "OWN" cho SV."""
    course = _course_or_404(course_id)
    role = _role(actor)

    if role == ADMIN:
        return course, "ALL"
    if role == INSTRUCTOR:
        if not _is_teacher_of(actor, course):
            raise Forbidden("Không dạy môn này")
        return course, "ALL"

    if _db().get_enrollment(course["id"], actor["id"]) is None:
        raise Forbidden("Không ghi danh môn này")
    return course, "OWN"


def authorize_update(actor: dict[str, Any], course_id: str) -> dict[str, Any]:
    """Chỉ GV dạy chính môn đó được sửa điểm; ADMIN và SV đều 403."""
    course = _course_or_404(course_id)
    if _role(actor) != INSTRUCTOR or not _is_teacher_of(actor, course):
        raise Forbidden("Không có quyền sửa điểm môn này")
    return course


def get_grades(actor: dict[str, Any], course_id: str) -> list[dict[str, Any]]:
    course, scope = authorize_read(actor, course_id)
    rows = _db().get_course_enrollments(course["id"])

    if scope == "OWN":
        rows = [row for row in rows if row["studentId"] == actor["id"]]

    return [{"studentId": row["studentId"], "score": row["score"]} for row in rows]


def update_grade(
    actor: dict[str, Any], course_id: str, student_id: str, score: Any
) -> dict[str, Any]:
    course = authorize_update(actor, course_id)
    validate_score(score)

    if _db().get_enrollment(course["id"], student_id) is None:
        raise NotFound("Sinh viên không ghi danh môn này")

    old_score = _db().update_score(course["id"], student_id, score)

    log_event(
        actor_id=actor["id"],
        action="GRADE_UPDATE",
        resource=f"course:{course['id']}/student:{student_id}",
        result="ALLOW",
        old_score=old_score,
        new_score=score,
    )

    return {"courseId": course["id"], "studentId": student_id, "score": score}
