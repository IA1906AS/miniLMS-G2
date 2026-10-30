"""Báo cáo: bảng điểm lớp, tỷ lệ hoàn thành, pass/fail, export CSV."""

from __future__ import annotations

import csv
import io
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from web.models import (
    ActivityEvent,
    Course,
    CourseSection,
    Enrollment,
    Quiz,
    QuizAttempt,
    User,
)
from web.services import activity


def section_report(sess: Session, section_id: int) -> dict[str, Any] | None:
    section = sess.get(CourseSection, section_id)
    if section is None:
        return None
    course = sess.get(Course, section.course_id)

    rows = sess.execute(
        select(Enrollment, User)
        .join(User, Enrollment.student_id == User.id)
        .where(Enrollment.section_id == section_id)
        .order_by(User.email)
    ).all()

    quizzes = list(
        sess.scalars(select(Quiz).where(Quiz.section_id == section_id)).all()
    )

    students: list[dict[str, Any]] = []
    passed = 0
    for enrollment, student in rows:
        progress = activity.section_progress(sess, student.id, section_id)
        attempts = sess.scalars(
            select(QuizAttempt)
            .where(
                QuizAttempt.student_id == student.id,
                QuizAttempt.status == "SUBMITTED",
                QuizAttempt.quiz_id.in_([q.id for q in quizzes] or [0]),
            )
            .order_by(QuizAttempt.score.desc())
        ).all()
        best_quiz = attempts[0].score if attempts else None
        is_pass = bool(enrollment.score >= 5.0)
        passed += 1 if is_pass else 0
        students.append(
            {
                "student_id": student.id,
                "email": student.email,
                "full_name": student.full_name,
                "final_score": enrollment.score,
                "best_quiz": best_quiz,
                "completed": progress["completed"],
                "total_lessons": progress["total"],
                "percent": progress["percent"],
                "passed": is_pass,
            }
        )

    total = len(students)
    return {
        "section": section,
        "course": course,
        "students": students,
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": round(passed * 100 / total) if total else 0,
    }


def reports_of_teacher(sess: Session, teacher_id: str) -> list[dict[str, Any]]:
    sections = sess.execute(
        select(CourseSection, Course)
        .join(Course, CourseSection.course_id == Course.id)
        .where(Course.instructor_id == teacher_id)
        .order_by(Course.title)
    ).all()
    return [{"section": section, "course": course} for section, course in sections]


def platform_report(sess: Session) -> dict[str, Any]:
    stats: dict[str, Any] = {
        "users": sess.scalar(select(func.count()).select_from(User)) or 0,
        "courses": sess.scalar(select(func.count()).select_from(Course)) or 0,
        "sections": sess.scalar(select(func.count()).select_from(CourseSection)) or 0,
        "enrollments": sess.scalar(select(func.count()).select_from(Enrollment)) or 0,
        "events": sess.scalar(select(func.count()).select_from(ActivityEvent)) or 0,
    }
    scores = sess.scalars(select(Enrollment.score)).all()
    stats["avg_score"] = round(sum(scores) / len(scores), 2) if scores else 0.0
    stats["pass_count"] = sum(1 for score in scores if score >= 5.0)
    stats["fail_count"] = len(scores) - stats["pass_count"]
    return stats


def _section_rows_csv(sess: Session, section_id: int) -> list[list[str]]:
    report = section_report(sess, section_id)
    if report is None:
        return []
    rows = [
        [
            "student_id",
            "email",
            "full_name",
            "final_score",
            "best_quiz",
            "completed",
            "total_lessons",
            "percent",
            "passed",
        ]
    ]
    for student in report["students"]:
        rows.append(
            [
                student["student_id"],
                student["email"],
                student["full_name"] or "",
                f"{student['final_score']:.2f}",
                "" if student["best_quiz"] is None else f"{student['best_quiz']:.2f}",
                str(student["completed"]),
                str(student["total_lessons"]),
                f"{student['percent']}%",
                "PASS" if student["passed"] else "FAIL",
            ]
        )
    return rows


def section_csv(sess: Session, section_id: int) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    for row in _section_rows_csv(sess, section_id):
        writer.writerow(row)
    return buffer.getvalue()
