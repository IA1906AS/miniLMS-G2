"""Tải lên / tải xuống tệp (thành phần LƯU TRỮ TỆP).

Mọi tệp đều nằm ngoài static và chỉ được trả qua các route có kiểm tra quyền:
- Avatar: mọi người dùng đã đăng nhập, xem được avatar của người khác.
- Tài liệu bài giảng: chỉ SV đã ghi danh hoặc GV/Admin của khoá.
- Tệp bài nộp: chỉ chủ bài nộp hoặc GV/Admin của khoá.
"""

from __future__ import annotations

import os
from typing import Any

from flask import Blueprint, abort, flash, redirect, request, url_for
from flask import send_file
from sqlalchemy import select
from sqlalchemy.orm import Session
from werkzeug.wrappers import Response

from web.audit import record as audit_record
from web.auth import can_manage_course, current_user, login_required
from web.database import get_db
from web.models import (
    ROLE_STUDENT,
    Attachment,
    Chapter,
    Course,
    Enrollment,
    Lesson,
    Submission,
    User,
)
from web.storage import (
    CODE_EXT,
    DOC_EXT,
    IMAGE_EXT,
    MAX_DOC_BYTES,
    MAX_IMAGE_BYTES,
    abspath,
    delete_file,
    save_upload,
)

bp = Blueprint("files", __name__)


def _actor() -> dict[str, Any]:
    actor = current_user()
    if actor is None:
        abort(403)
    return actor


def _is_enrolled(sess: Session, student_id: str, course_id: str) -> bool:
    return bool(
        sess.scalars(
            select(Enrollment.id).where(
                Enrollment.course_id == course_id,
                Enrollment.student_id == student_id,
                Enrollment.status == "ACTIVE",
            )
        ).first()
    )


def _course_of_lesson(sess: Session, lesson_id: int) -> Course | None:
    return sess.scalars(
        select(Course)
        .join(Chapter, Chapter.course_id == Course.id)
        .join(Lesson, Lesson.chapter_id == Chapter.id)
        .where(Lesson.id == lesson_id)
    ).first()


def _course_of_assignment(sess: Session, assignment_id: int) -> Course | None:
    from web.models import Assignment

    return sess.scalars(
        select(Course)
        .join(Assignment, Assignment.course_id == Course.id)
        .where(Assignment.id == assignment_id)
    ).first()


# ---------------------------------------------------------------------------
# Avatar
# ---------------------------------------------------------------------------


@bp.post("/profile/avatar")
@login_required
def upload_avatar() -> Response:
    actor = _actor()
    file = request.files.get("avatar")
    if file is None or not file.filename:
        flash("Vui lòng chọn ảnh đại diện.", "error")
        return redirect(request.referrer or url_for("main.dashboard"))
    try:
        rel = save_upload(
            file, "avatars", allowed=IMAGE_EXT, max_bytes=MAX_IMAGE_BYTES
        )
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(request.referrer or url_for("main.dashboard"))

    with get_db().session() as sess:
        user = sess.get(User, actor["id"])
        if user is None:
            abort(404)
        old = user.avatar_path
        user.avatar_path = rel
        sess.flush()
    delete_file(old)
    audit_record("AVATAR_UPDATED", f"user:{actor['id']}", actor_id=actor["id"])
    flash("Đã cập nhật ảnh đại diện.", "success")
    return redirect(request.referrer or url_for("main.dashboard"))


@bp.get("/avatar/<user_id>")
@login_required
def serve_avatar(user_id: str) -> Response:
    with get_db().session() as sess:
        user = sess.get(User, user_id)
        if user is None or not user.avatar_path:
            abort(404)
        path = abspath(user.avatar_path)
    if not path.is_file():
        abort(404)
    return send_file(path, max_age=300)


# ---------------------------------------------------------------------------
# Tài liệu bài giảng
# ---------------------------------------------------------------------------


@bp.post("/lessons/<int:lesson_id>/attachments")
@login_required
def upload_attachment(lesson_id: int) -> Response:
    actor = _actor()
    with get_db().session() as sess:
        lesson = sess.get(Lesson, lesson_id)
        if lesson is None:
            abort(404)
        course = _course_of_lesson(sess, lesson_id)
        if course is None or not can_manage_course(actor, course):
            abort(403)

    file = request.files.get("file")
    title = (request.form.get("title") or "").strip() or (
        file.filename if file is not None else ""
    )
    if file is None or not file.filename:
        flash("Vui lòng chọn tệp tài liệu.", "error")
        return redirect(request.referrer or url_for("main.dashboard"))
    try:
        rel = save_upload(file, "attachments", allowed=DOC_EXT, max_bytes=MAX_DOC_BYTES)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(request.referrer or url_for("main.dashboard"))

    with get_db().session() as sess:
        lesson = sess.get(Lesson, lesson_id)
        sess.add(
            Attachment(
                owner_id=actor["id"],
                lesson_id=lesson_id,
                title=title[:200],
                stored_name=rel,
                mime=file.mimetype or "application/octet-stream",
                size_bytes=file.stream.tell() if file.stream else 0,
            )
        )
        sess.flush()
    audit_record(
        "ATTACHMENT_UPLOADED",
        f"lesson:{lesson_id}",
        actor_id=actor["id"],
        file=rel,
    )
    flash("Đã tải tài liệu lên.", "success")
    return redirect(request.referrer or url_for("main.dashboard"))


@bp.post("/attachments/<int:attachment_id>/delete")
@login_required
def delete_attachment(attachment_id: int) -> Response:
    actor = _actor()
    with get_db().session() as sess:
        attachment = sess.get(Attachment, attachment_id)
        if attachment is None:
            abort(404)
        course = (
            _course_of_lesson(sess, attachment.lesson_id)
            if attachment.lesson_id
            else None
        )
        if course is None or not can_manage_course(actor, course):
            abort(403)
        rel = attachment.stored_name
        sess.delete(attachment)
        sess.flush()
    delete_file(rel)
    audit_record(
        "ATTACHMENT_DELETED", f"attachment:{attachment_id}", actor_id=actor["id"]
    )
    flash("Đã xoá tài liệu.", "success")
    return redirect(request.referrer or url_for("main.dashboard"))


@bp.get("/attachments/<int:attachment_id>/download")
@login_required
def download_attachment(attachment_id: int) -> Response:
    actor = _actor()
    with get_db().session() as sess:
        attachment = sess.get(Attachment, attachment_id)
        if attachment is None or attachment.lesson_id is None:
            abort(404)
        course = _course_of_lesson(sess, attachment.lesson_id)
        if course is None:
            abort(404)
        staff = can_manage_course(actor, course)
        enrolled = actor["role"] == ROLE_STUDENT and _is_enrolled(
            sess, actor["id"], course.id
        )
        if not staff and not enrolled:
            abort(403)
        path = abspath(attachment.stored_name)
        title = attachment.title
    if not path.is_file():
        abort(404)
    return send_file(path, as_attachment=True, download_name=title)


# ---------------------------------------------------------------------------
# Tệp bài nộp
# ---------------------------------------------------------------------------


@bp.get("/submissions/<int:submission_id>/download")
@login_required
def download_submission(submission_id: int) -> Response:
    actor = _actor()
    with get_db().session() as sess:
        submission = sess.get(Submission, submission_id)
        if submission is None or not submission.file_path:
            abort(404)
        course = _course_of_assignment(sess, submission.assignment_id)
        if course is None:
            abort(404)
        if actor["id"] != submission.student_id and not can_manage_course(
            actor, course
        ):
            abort(403)
        path = abspath(submission.file_path)
        download_name = os.path.basename(submission.file_path)
    if not path.is_file():
        abort(404)
    return send_file(path, as_attachment=True, download_name=download_name)
