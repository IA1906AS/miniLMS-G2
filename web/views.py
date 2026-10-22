"""Route của giao diện web: trang chủ, đăng nhập/đăng xuất, trang tài khoản."""

from __future__ import annotations

from typing import Any

from flask import Blueprint, abort, redirect, render_template, request, url_for
from werkzeug.wrappers import Response

from app.errors import AccountLocked
from web.auth import (
    attach_session,
    authenticate,
    clear_session,
    current_user,
    login_required,
)
from web.database import (
    ROLE_ADMIN,
    ROLE_GUEST,
    ROLE_STUDENT,
    ROLE_TEACHER,
    course_overview,
    get_db,
    platform_stats,
    student_grades,
    teaching_courses,
)

bp = Blueprint("web", __name__)

ROLE_HOME_HINT = {
    ROLE_ADMIN: "Bạn đang xem với quyền quản trị: toàn bộ môn học và số liệu hệ thống.",
    ROLE_TEACHER: "Bạn là giảng viên: các môn bạn phụ trách được đánh dấu bên dưới.",
    ROLE_STUDENT: "Bạn là sinh viên: điểm của bạn hiển thị ngay trên từng môn.",
    ROLE_GUEST: (
        "Bạn đang xem với tư cách khách: chỉ thấy danh sách môn học. Đăng nhập để "
        "xem điểm và mở trang tài khoản."
    ),
}


def _safe_next(target: str | None) -> str:
    """Chỉ cho phép chuyển hướng trong nội bộ site (chặn open redirect)."""
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return url_for("web.account")


@bp.get("/")
def home() -> str:
    actor = current_user()
    with get_db().session() as sess:
        courses = course_overview(sess)
        stats = platform_stats(sess)
        my_scores: dict[str, float] = {}
        if actor is not None and actor["role"] == ROLE_STUDENT:
            my_scores = {
                row["id"]: row["score"] for row in student_grades(sess, actor["id"])
            }

    return render_template(
        "home.html",
        courses=courses,
        stats=stats,
        my_scores=my_scores,
        hint=ROLE_HOME_HINT[actor["role"]] if actor else ROLE_HOME_HINT[ROLE_GUEST],
    )


@bp.route("/login", methods=["GET", "POST"])
def login() -> Response | tuple[str, int]:
    if current_user() is not None:
        return redirect(url_for("web.account"))

    error: str | None = None
    email = ""

    if request.method == "POST":
        email = (request.form.get("email") or "").strip()
        password = request.form.get("password") or ""
        if not email or not password:
            error = "Vui lòng nhập đầy đủ email và mật khẩu."
        else:
            try:
                actor = authenticate(email, password)
            except AccountLocked:
                error = (
                    "Tài khoản tạm thời bị khóa do đăng nhập sai quá nhiều lần. "
                    "Thử lại sau 15 phút."
                )
                actor = None
            if actor is None:
                # Thông điệp giống nhau cho email sai và mật khẩu sai.
                error = error or "Email hoặc mật khẩu không đúng."
            else:
                response = redirect(_safe_next(request.args.get("next")))
                return attach_session(response, actor["id"])

    status = 401 if error is not None and request.method == "POST" else 200
    return render_template("login.html", error=error, email=email), status


@bp.post("/logout")
def logout() -> Response:
    return clear_session(redirect(url_for("web.login")))


@bp.get("/account")
@login_required
def account() -> str:
    actor = current_user()
    assert actor is not None  # login_required đã đảm bảo

    ctx: dict[str, Any] = {"section": actor["role"]}

    with get_db().session() as sess:
        if actor["role"] == ROLE_STUDENT:
            grades = student_grades(sess, actor["id"])
            ctx["grades"] = grades
            ctx["average"] = (
                round(sum(g["score"] for g in grades) / len(grades), 2)
                if grades
                else None
            )
        elif actor["role"] == ROLE_TEACHER:
            mine = teaching_courses(sess, actor["id"])
            ctx["courses"] = mine
            ctx["students"] = sum(c["students"] for c in mine)
        elif actor["role"] == ROLE_ADMIN:
            ctx["stats"] = platform_stats(sess)
            ctx["courses"] = course_overview(sess)
        else:
            # Vai trò không xác định (GUEST hoặc role lạ) — fail-closed
            abort(403)

    return render_template("account.html", **ctx)
