"""Trang danh mục khoá học: danh sách, chi tiết, ghi danh, quản lý."""

from __future__ import annotations

from typing import Any

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from werkzeug.wrappers import Response

from web.auth import current_user, login_required
from web.database import get_db
from web.models import ROLE_ADMIN, ROLE_TEACHER, User
from web.services import catalog as svc
from web.services.catalog import CatalogError
from web.services.content import outline
from web.services.reporting import section_report

bp = Blueprint("catalog", __name__, url_prefix="/catalog")


def _require_staff(actor: dict[str, Any] | None) -> dict[str, Any]:
    if actor is None or actor["role"] not in {ROLE_ADMIN, ROLE_TEACHER}:
        abort(403)
    return actor


@bp.get("/")
def index() -> str:
    q = request.args.get("q", "").strip()
    tag = request.args.get("tag", "").strip() or None
    category_id = request.args.get("category", type=int)
    page = request.args.get("page", 1, type=int)

    with get_db().session() as sess:
        result = svc.list_courses(
            sess, q=q or None, tag=tag, category_id=category_id, page=page
        )
        cats = svc.categories(sess)
        rows = [
            {"course": course, "instructor": sess.get(User, course.instructor_id)}
            for course in result["items"]
        ]

    return render_template(
        "catalog/index.html",
        rows=rows,
        result=result,
        categories=cats,
        q=q,
        tag=tag or "",
        category_id=category_id or 0,
    )


@bp.get("/<course_id>")
def detail(course_id: str) -> str:
    actor = current_user()
    with get_db().session() as sess:
        data = svc.course_detail(sess, course_id)
        if data is None:
            abort(404)
        enrolled = svc.is_enrolled(sess, actor["id"], course_id) if actor else False
        outlines = [
            {"section": section, "outline": outline(sess, section.id)}
            for section in data["sections"]
        ]

    return render_template(
        "catalog/detail.html", data=data, outlines=outlines, enrolled=enrolled
    )


@bp.post("/<course_id>/enroll")
@login_required
def enroll(course_id: str) -> Response:
    actor = current_user()
    assert actor is not None
    with get_db().session() as sess:
        data = svc.course_detail(sess, course_id)
        if data is None:
            abort(404)
        section = data["sections"][0] if data["sections"] else None
        try:
            row = svc.enroll(sess, actor, data["course"], section)
            flash(
                "Đã ghi danh, đang chờ giảng viên duyệt."
                if row.status == "PENDING"
                else "Ghi danh thành công!",
                "success",
            )
        except CatalogError as exc:
            flash(str(exc), "error")
    return redirect(url_for("catalog.detail", course_id=course_id))


@bp.get("/manage/new")
@login_required
def new_course() -> str:
    _require_staff(current_user())
    with get_db().session() as sess:
        cats = svc.categories(sess)
    return render_template("catalog/form.html", course=None, categories=cats)


@bp.post("/manage/new")
@login_required
def create_course() -> Response:
    actor = _require_staff(current_user())
    with get_db().session() as sess:
        try:
            course = svc.create_course(
                sess,
                actor,
                title=request.form.get("title", ""),
                description=request.form.get("description", ""),
                price=float(request.form.get("price") or 0),
                category_id=request.form.get("category_id", type=int),
                status=request.form.get("status", "DRAFT"),
            )
            svc.set_tags(sess, course, request.form.get("tags", ""))
            flash("Đã tạo khoá học ở trạng thái nháp.", "success")
            return redirect(url_for("catalog.detail", course_id=course.id))
        except (CatalogError, ValueError) as exc:
            flash(str(exc), "error")
            return redirect(url_for("catalog.new_course"))


@bp.route("/manage/<course_id>", methods=["GET", "POST"])
@login_required
def edit_course(course_id: str) -> str | Response:
    actor = _require_staff(current_user())
    with get_db().session() as sess:
        data = svc.course_detail(sess, course_id)
        if data is None:
            abort(404)
        course = data["course"]
        if not svc.can_manage_course(actor, course):
            abort(403)

        if request.method == "POST":
            try:
                svc.update_course(
                    sess,
                    actor,
                    course,
                    title=request.form.get("title", ""),
                    description=request.form.get("description", ""),
                    price=float(request.form.get("price") or 0),
                    category_id=request.form.get("category_id", type=int),
                    status=request.form.get("status", "DRAFT"),
                )
                svc.set_tags(sess, course, request.form.get("tags", ""))
                flash("Đã lưu thay đổi.", "success")
                return redirect(url_for("catalog.edit_course", course_id=course_id))
            except (CatalogError, ValueError) as exc:
                flash(str(exc), "error")

        cats = svc.categories(sess)
        sections = data["sections"]
        section_id = request.args.get("section", type=int) or (
            sections[0].id if sections else None
        )
        outline_data = outline(sess, section_id) if section_id else []
        report = section_report(sess, section_id) if section_id else None

    return render_template(
        "catalog/manage.html",
        data=data,
        categories=cats,
        section_id=section_id,
        outline=outline_data,
        report=report,
    )
