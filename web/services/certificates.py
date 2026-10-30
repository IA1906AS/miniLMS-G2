"""Chứng chỉ hoàn thành khoá học + mã xác thực công khai."""

from __future__ import annotations

import secrets
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from web.models import (
    Certificate,
    Course,
    CourseSection,
    Enrollment,
    User,
    utcnow,
)
from web.services import activity


class CertificateError(Exception):
    """Vi phạm quy tắc cấp chứng chỉ."""


PASS_SCORE = 5.0


def _new_code() -> str:
    return secrets.token_urlsafe(12).replace("-", "").replace("_", "")[:16]


def issue_if_eligible(
    sess: Session, student_id: str, section_id: int
) -> Certificate | None:
    """Cấp chứng chỉ khi đã hoàn thành 100% bài học và điểm >= 5.

    Idempotent: đã có chứng chỉ thì trả lại chứng chỉ cũ.
    """
    existing = sess.scalars(
        select(Certificate).where(
            Certificate.user_id == student_id,
            Certificate.section_id == section_id,
        )
    ).first()
    if existing is not None:
        return existing

    enrollment = sess.scalars(
        select(Enrollment).where(
            Enrollment.section_id == section_id,
            Enrollment.student_id == student_id,
        )
    ).first()
    if enrollment is None or enrollment.status != "APPROVED":
        return None
    if float(enrollment.score) < PASS_SCORE:
        return None

    progress = activity.section_progress(sess, student_id, section_id)
    if progress["total"] == 0 or progress["completed"] < progress["total"]:
        return None

    certificate = Certificate(
        code=_new_code(),
        user_id=student_id,
        section_id=section_id,
        final_score=float(enrollment.score),
        issued_at=utcnow(),
    )
    sess.add(certificate)
    sess.flush()

    activity.award_points(
        sess,
        student_id,
        50,
        "certificate_issued",
        ref_type="section",
        ref_id=str(section_id),
    )
    activity.evaluate_badges(sess, student_id)
    return certificate


def certificates_of(sess: Session, user_id: str) -> list[dict[str, Any]]:
    rows = sess.execute(
        select(Certificate, CourseSection, Course)
        .join(CourseSection, Certificate.section_id == CourseSection.id)
        .join(Course, CourseSection.course_id == Course.id)
        .where(Certificate.user_id == user_id)
        .order_by(Certificate.issued_at.desc())
    ).all()
    return [
        {"certificate": cert, "section": section, "course": course}
        for cert, section, course in rows
    ]


def verify(sess: Session, code: str) -> dict[str, Any] | None:
    """Tra cứu công khai theo mã — dùng cho trang /verify/<code>."""
    certificate = sess.scalars(
        select(Certificate).where(Certificate.code == code.strip())
    ).first()
    if certificate is None:
        return None

    user = sess.get(User, certificate.user_id)
    section = sess.get(CourseSection, certificate.section_id)
    course = sess.get(Course, section.course_id) if section else None
    return {
        "certificate": certificate,
        "holder": (user.full_name or user.email) if user else "?",
        "email": user.email if user else "",
        "course": course,
        "section": section,
    }


def revoke(sess: Session, actor: dict[str, Any], certificate: Certificate) -> None:
    from web.models import ROLE_ADMIN

    if actor["role"] != ROLE_ADMIN:
        raise CertificateError("Chỉ quản trị viên mới thu hồi được chứng chỉ.")
    sess.delete(certificate)
    sess.flush()


def count_of_section(sess: Session, section_id: int) -> int:
    return (
        sess.scalar(
            select(func.count())
            .select_from(Certificate)
            .where(Certificate.section_id == section_id)
        )
        or 0
    )
