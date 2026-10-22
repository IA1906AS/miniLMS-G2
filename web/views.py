"""Route của giao diện web: trang chủ, đăng nhập/đăng xuất, trang tài khoản."""

from __future__ import annotations

import contextlib
from typing import Any

from flask import Blueprint, abort, redirect, render_template, request, url_for
from sqlalchemy import select
from werkzeug.wrappers import Response

from app.auth import hash_password, verify_password
from app.errors import AccountLocked, ValidationError
from app.store import get_store
from app.user_services import _validate_email, _validate_password_strength
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
    User,
    course_overview,
    get_db,
    normalize_role,
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


@bp.route("/register", methods=["GET", "POST"])
def register() -> Response | tuple[str, int]:
    if current_user() is not None:
        return redirect(url_for("web.account"))

    error: str | None = None
    email = ""
    role = ROLE_STUDENT

    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        confirm_password = request.form.get("confirm_password") or ""
        raw_role = (request.form.get("role") or "").strip().upper()
        role = normalize_role(raw_role)

        if not email or not password or not confirm_password:
            error = "Vui lòng nhập đầy đủ thông tin."
        elif password != confirm_password:
            error = "Mật khẩu xác nhận không khớp."
        elif role not in {ROLE_STUDENT, ROLE_TEACHER}:
            error = "Vai trò đăng ký không hợp lệ."
        else:
            try:
                _validate_email(email)
                _validate_password_strength(password)
            except ValidationError as exc:
                error = str(exc)

            if not error:
                with get_db().session() as sess:
                    existing = (
                        sess.query(User).filter(User.email == email).one_or_none()
                    )
                    if existing is not None:
                        error = "Email này đã được sử dụng."
                    else:
                        all_ids = sess.scalars(select(User.id)).all()
                        nums = [
                            int(i[1:])
                            for i in all_ids
                            if i.startswith("u") and i[1:].isdigit()
                        ]
                        new_id = f"u{max(nums, default=0) + 1}"
                        user = User(
                            id=new_id,
                            email=email,
                            role=role,
                            password_hash=hash_password(password),
                        )
                        sess.add(user)
                        sess.flush()

                        with contextlib.suppress(Exception):
                            store_role = "INSTRUCTOR" if role == ROLE_TEACHER else role
                            get_store().create_user(
                                email=email,
                                password_hash=user.password_hash,
                                role=store_role,
                            )

                        response = redirect(url_for("web.account"))
                        return attach_session(response, user.id)

    status = 400 if error is not None and request.method == "POST" else 200
    return render_template("register.html", error=error, email=email, role=role), status


@bp.route("/reset-password", methods=["GET", "POST"])
def reset_password() -> Response | tuple[str, int]:
    error: str | None = None
    email = ""

    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        new_password = request.form.get("new_password") or ""
        confirm_password = request.form.get("confirm_password") or ""

        if not email or not new_password or not confirm_password:
            error = "Vui lòng nhập đầy đủ email và mật khẩu mới."
        elif new_password != confirm_password:
            error = "Mật khẩu xác nhận không khớp."
        else:
            try:
                _validate_password_strength(new_password)
            except ValidationError as exc:
                error = str(exc)

            if not error:
                with get_db().session() as sess:
                    user = sess.query(User).filter(User.email == email).one_or_none()
                    if user is None:
                        error = "Không tìm thấy tài khoản với email này."
                    else:
                        new_hash = hash_password(new_password)
                        user.password_hash = new_hash
                        sess.flush()

                        with contextlib.suppress(Exception):
                            store = get_store()
                            store.update_password(user.id, new_hash)
                            store.record_login_success(email)

                        return redirect(url_for("web.login", reset=1))

    status = 400 if error is not None and request.method == "POST" else 200
    return render_template("reset_password.html", error=error, email=email), status


@bp.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password() -> tuple[str, int]:
    actor = current_user()
    assert actor is not None

    error: str | None = None
    success: str | None = None

    if request.method == "POST":
        old_password = request.form.get("old_password") or ""
        new_password = request.form.get("new_password") or ""
        confirm_password = request.form.get("confirm_password") or ""

        if not old_password or not new_password or not confirm_password:
            error = "Vui lòng nhập đầy đủ các trường mật khẩu."
        elif new_password != confirm_password:
            error = "Mật khẩu mới xác nhận không khớp."
        elif new_password == old_password:
            error = "Mật khẩu mới không được trùng với mật khẩu hiện tại."
        else:
            try:
                _validate_password_strength(new_password)
            except ValidationError as exc:
                error = str(exc)

            if not error:
                with get_db().session() as sess:
                    user = sess.get(User, actor["id"])
                    if user is None or not verify_password(
                        old_password, user.password_hash
                    ):
                        error = "Mật khẩu hiện tại không đúng."
                    else:
                        new_hash = hash_password(new_password)
                        user.password_hash = new_hash
                        sess.flush()

                        with contextlib.suppress(Exception):
                            get_store().update_password(actor["id"], new_hash)

                        success = "Đổi mật khẩu thành công!"

    status = 400 if error is not None else 200
    return (
        render_template("change_password.html", error=error, success=success),
        status,
    )
