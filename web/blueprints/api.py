"""REST API JSON (spec mục 8 — tuỳ chọn) + tài liệu OpenAPI.

Xác thực dùng chung cookie JWT với giao diện web. Mọi endpoint đều kiểm tra
quyền giống bản HTML, chỉ khác định dạng trả về (JSON).
"""

from __future__ import annotations

from typing import Any

from flask import Blueprint, abort, jsonify, request, url_for

from web.auth import can_manage_course, current_user, login_required
from web.database import get_db
from web.models import (
    ROLE_STUDENT,
    Assignment,
    Chapter,
    Course,
    Enrollment,
    Lesson,
    Quiz,
    Submission,
    User,
)
from sqlalchemy import select

bp = Blueprint("api", __name__, url_prefix="/api")


def _course_json(course: Course, instructor: User | None) -> dict[str, Any]:
    return {
        "id": course.id,
        "title": course.title,
        "description": course.description,
        "status": course.status,
        "price": course.price,
        "categoryId": course.category_id,
        "instructor": (
            {"id": instructor.id, "name": instructor.display_name}
            if instructor
            else None
        ),
    }


@bp.get("/me")
@login_required
def me() -> Any:
    actor = current_user()
    assert actor is not None
    return jsonify(
        {
            "id": actor["id"],
            "email": actor["email"],
            "role": actor["role"],
            "fullName": actor.get("full_name"),
        }
    )


@bp.get("/courses")
def list_courses() -> Any:
    q = (request.args.get("q") or "").strip().lower()
    category_id = request.args.get("category", type=int)
    instructor_id = (request.args.get("instructor") or "").strip()

    with get_db().session() as sess:
        stmt = select(Course).where(Course.status == "PUBLISHED")
        if category_id:
            stmt = stmt.where(Course.category_id == category_id)
        if instructor_id:
            stmt = stmt.where(Course.instructor_id == instructor_id)
        if q:
            stmt = stmt.where(Course.title.ilike(f"%{q}%"))
        courses = list(sess.scalars(stmt.order_by(Course.title)).all())
        payload = []
        for course in courses:
            instructor = sess.get(User, course.instructor_id)
            payload.append(_course_json(course, instructor))
    return jsonify({"items": payload, "total": len(payload)})


@bp.get("/courses/<course_id>")
def get_course(course_id: str) -> Any:
    with get_db().session() as sess:
        course = sess.get(Course, course_id)
        if course is None or course.status != "PUBLISHED":
            abort(404)
        instructor = sess.get(User, course.instructor_id)
        chapters = []
        for chapter in sess.scalars(
            select(Chapter)
            .where(Chapter.course_id == course_id)
            .order_by(Chapter.position, Chapter.id)
        ).all():
            lessons = [
                {
                    "id": lesson.id,
                    "title": lesson.title,
                    "kind": lesson.kind,
                    "durationMin": lesson.duration_min,
                    "isFreePreview": lesson.is_free_preview,
                }
                for lesson in sess.scalars(
                    select(Lesson)
                    .where(Lesson.chapter_id == chapter.id)
                    .order_by(Lesson.position, Lesson.id)
                ).all()
            ]
            chapters.append(
                {"id": chapter.id, "title": chapter.title, "lessons": lessons}
            )
        quizzes = [
            {
                "id": quiz.id,
                "title": quiz.title,
                "timeLimitMin": quiz.time_limit_min,
                "passScore": quiz.pass_score,
                "maxAttempts": quiz.max_attempts,
            }
            for quiz in sess.scalars(
                select(Quiz).where(
                    Quiz.course_id == course_id, Quiz.status == "PUBLISHED"
                )
            ).all()
        ]
        assignments = [
            {
                "id": a.id,
                "title": a.title,
                "dueAt": a.due_at.isoformat() if a.due_at else None,
                "maxScore": a.max_score,
            }
            for a in sess.scalars(
                select(Assignment).where(Assignment.course_id == course_id)
            ).all()
        ]
        data = _course_json(course, instructor)
        data.update({"chapters": chapters, "quizzes": quizzes, "assignments": assignments})
    return jsonify(data)


@bp.get("/courses/<course_id>/grades")
@login_required
def get_grades(course_id: str) -> Any:
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        course = sess.get(Course, course_id)
        if course is None:
            abort(404)
        staff = can_manage_course(actor, course)
        if actor["role"] == ROLE_STUDENT and not staff:
            enrolled = sess.scalars(
                select(Enrollment.id).where(
                    Enrollment.course_id == course_id,
                    Enrollment.student_id == actor["id"],
                )
            ).first()
            if not enrolled:
                abort(403)

        rows = sess.scalars(
            select(Enrollment).where(Enrollment.course_id == course_id)
        ).all()

        result = []
        for enrollment in rows:
            if not staff and enrollment.student_id != actor["id"]:
                continue
            submissions = sess.scalars(
                select(Submission)
                .join(Assignment, Submission.assignment_id == Assignment.id)
                .where(
                    Assignment.course_id == course_id,
                    Submission.student_id == enrollment.student_id,
                )
            ).all()
            result.append(
                {
                    "studentId": enrollment.student_id,
                    "status": enrollment.status,
                    "grades": [
                        {
                            "assignmentId": s.assignment_id,
                            "score": s.score,
                            "feedback": s.feedback,
                            "gradedAt": s.graded_at.isoformat() if s.graded_at else None,
                        }
                        for s in submissions
                    ],
                }
            )
    return jsonify({"courseId": course_id, "items": result})


@bp.get("/assignments/<int:assignment_id>")
@login_required
def get_assignment(assignment_id: int) -> Any:
    actor = current_user()
    assert actor is not None
    with get_db().session() as sess:
        assignment = sess.get(Assignment, assignment_id)
        if assignment is None:
            abort(404)
        course = sess.get(Course, assignment.course_id)
        if course is None:
            abort(404)
        staff = can_manage_course(actor, course)
        if not staff:
            enrolled = sess.scalars(
                select(Enrollment.id).where(
                    Enrollment.course_id == course.id,
                    Enrollment.student_id == actor["id"],
                )
            ).first()
            if not enrolled:
                abort(403)
        data = {
            "id": assignment.id,
            "courseId": assignment.course_id,
            "title": assignment.title,
            "description": assignment.description,
            "dueAt": assignment.due_at.isoformat() if assignment.due_at else None,
            "maxScore": assignment.max_score,
        }
    return jsonify(data)


_OPENAPI = {
    "openapi": "3.0.3",
    "info": {
        "title": "miniLMS API",
        "version": "1.0.0",
        "description": "REST API cho các tính năng chính. Xác thực bằng cookie JWT.",
    },
    "servers": [{"url": "/"}],
    "components": {
        "securitySchemes": {
            "cookieAuth": {"type": "apiKey", "in": "cookie", "name": "lms_token"}
        }
    },
    "paths": {
        "/api/me": {
            "get": {
                "summary": "Thông tin người dùng hiện tại",
                "security": [{"cookieAuth": []}],
                "responses": {"200": {"description": "OK"}},
            }
        },
        "/api/courses": {
            "get": {
                "summary": "Danh sách khoá học công khai",
                "parameters": [
                    {"name": "q", "in": "query", "schema": {"type": "string"}},
                    {"name": "category", "in": "query", "schema": {"type": "integer"}},
                    {"name": "instructor", "in": "query", "schema": {"type": "string"}},
                ],
                "responses": {"200": {"description": "OK"}},
            }
        },
        "/api/courses/{courseId}": {
            "get": {
                "summary": "Chi tiết khoá học (chương, bài, quiz, bài tập)",
                "parameters": [
                    {
                        "name": "courseId",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    }
                ],
                "responses": {"200": {"description": "OK"}, "404": {"description": "Not found"}},
            }
        },
        "/api/courses/{courseId}/grades": {
            "get": {
                "summary": "Điểm của khoá (SV chỉ thấy của mình)",
                "security": [{"cookieAuth": []}],
                "parameters": [
                    {
                        "name": "courseId",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    }
                ],
                "responses": {"200": {"description": "OK"}},
            }
        },
        "/api/assignments/{assignmentId}": {
            "get": {
                "summary": "Chi tiết bài tập",
                "security": [{"cookieAuth": []}],
                "parameters": [
                    {
                        "name": "assignmentId",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "integer"},
                    }
                ],
                "responses": {"200": {"description": "OK"}},
            }
        },
    },
}


@bp.get("/openapi.json")
def openapi() -> Any:
    return jsonify(_OPENAPI)


@bp.get("/docs")
def docs() -> Any:
    spec_url = url_for("api.openapi")
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>miniLMS API</title>"
        "<link rel='stylesheet' href='https://unpkg.com/swagger-ui-dist@5/swagger-ui.css'>"
        "</head><body><div id='swagger-ui'></div>"
        "<script src='https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js'></script>"
        f"<script>SwaggerUIBundle({{url:'{spec_url}',dom_id:'#swagger-ui'}});</script>"
        "</body></html>"
    )
