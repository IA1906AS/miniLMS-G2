"""Blueprint xác thực: đăng nhập, đăng ký, quên mật khẩu, đăng xuất.

Spec mục 1 (Khách): /login, /register, /forgot-password.
Spec dòng 151: sau đăng nhập Admin → /admin/dashboard, GV/SV → /dashboard.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from sqlalchemy import func, select
from werkzeug.wrappers import Response

from app.auth import hash_password
from app.errors import AppError
from web.audit import record as audit_record
from web.auth import (
    ROLE_HOME,
    attach_session,
    authenticate,
    clear_session,
    current_user,
)
from web.database import get_db
from web.mailer import send_password_reset
from web.models import (
    ROLE_ADMIN,
    ROLE_INSTRUCTOR,
    ROLE_STUDENT,
    USER_STATUS_ACTIVE,
    AuthSession,
    PasswordResetToken,
    User,
    normalize_role,
    utcnow,
)

bp = Blueprint("auth", __name__)


def _safe_next(target: str | None) -> str | None:
    """Chỉ cho phép chuyển hướng nội bộ (chặn open redirect)."""
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return None


def _redirect_after_login(actor: dict) -> Response:
    nxt = _safe_next(request.args.get("next") or request.form.get("next"))
    target = nxt or url_for(ROLE_HOME.get(actor["role"], ROLE_HOME[ROLE_STUDENT]))
    return attach_session(redirect(target), actor["id"])


@bp.route("/login", methods=["GET", "POST"])
def login() -> tuple[str, int] | Response:
    actor = current_user()
    if actor is not None:
        return redirect(url_for(ROLE_HOME.get(actor["role"], ROLE_HOME[ROLE_STUDENT])))

    error: str | None = None
    email = ""

    if request.method == "POST":
        email = (request.form.get("email") or "").strip()
        password = request.form.get("password") or ""
        if not email or not password:
            error = "Vui lòng nhập đầy đủ email và mật khẩu."
        else:
            try:
                logged = authenticate(email, password)
            except AppError as exc:
                error = str(exc)
                logged = None
            except Exception:
                error = (
                    "Tài khoản tạm thời bị khoá do đăng nhập sai quá nhiều lần. "
                    "Thử lại sau 15 phút."
                )
                logged = None

            if logged is None:
                error = error or "Email hoặc mật khẩu không đúng."
                audit_record("LOGIN_FAILED", f"email:{email.strip().lower()}")
            else:
                audit_record(
                    "LOGIN", f"user:{logged['id']}", actor_id=logged["id"]
                )
                return _redirect_after_login(logged)

    status = 401 if error and request.method == "POST" else 200
    return render_template("auth/login.html", error=error, email=email), status


@bp.post("/logout")
def logout() -> Response:
    actor = current_user()
    if actor is not None:
        audit_record("LOGOUT", f"user:{actor['id']}", actor_id=actor["id"])
    return clear_session(redirect(url_for("auth.login")))


@bp.route("/register", methods=["GET", "POST"])
def register() -> tuple[str, int] | Response:
    actor = current_user()
    if actor is not None:
        return redirect(url_for(ROLE_HOME.get(actor["role"], ROLE_HOME[ROLE_STUDENT])))

    error: str | None = None
    email = ""
    full_name = ""
    want_instructor = False

    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        full_name = (request.form.get("full_name") or "").strip()
        password = request.form.get("password") or ""
        confirm = request.form.get("confirm_password") or ""
        want_instructor = request.form.get("role") == "INSTRUCTOR"
        role = ROLE_INSTRUCTOR if want_instructor else ROLE_STUDENT

        if not email or not password or not confirm:
            error = "Vui lòng nhập đầy đủ thông tin."
        elif password != confirm:
            error = "Mật khẩu xác nhận không khớp."
        elif len(password) < 8:
            error = "Mật khẩu phải có ít nhất 8 ký tự."

        if not error:
            with get_db().session() as sess:
                exists = sess.scalars(
                    select(User.id).where(func.lower(User.email) == email)
                ).first()
                if exists:
                    error = "Email này đã được sử dụng."
                else:
                    ids = sess.scalars(select(User.id)).all()
                    nums = [int(i[1:]) for i in ids if i[0] == "u" and i[1:].isdigit()]
                    user = User(
                        id=f"u{max(nums, default=0) + 1}",
                        email=email,
                        password_hash=hash_password(password),
                        role=role,
                        full_name=full_name or None,
                        status=USER_STATUS_ACTIVE,
                    )
                    sess.add(user)
                    sess.flush()
                    new_id = user.id
                    new_role = normalize_role(user.role)

            if not error:
                actor = {"id": new_id, "email": email, "role": new_role}
                flash("Tạo tài khoản thành công.", "success")
                return _redirect_after_login(actor)

    status = 400 if error and request.method == "POST" else 200
    return (
        render_template(
            "auth/register.html",
            error=error,
            email=email,
            full_name=full_name,
            want_instructor=want_instructor,
        ),
        status,
    )


@bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password() -> tuple[str, int] | str:
    """Gửi liên kết đặt lại mật khẩu có thời hạn qua email (spec mục 1)."""
    error: str | None = None
    success: str | None = None
    email = ""

    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        if not email:
            error = "Vui lòng nhập email."
        else:
            user_email: str | None = None
            ttl = int(current_app.config.get("RESET_TOKEN_TTL_MINUTES", 30))
            with get_db().session() as sess:
                user = sess.scalars(
                    select(User).where(func.lower(User.email) == email)
                ).first()
                if user is not None:
                    raw_token = secrets.token_urlsafe(32)
                    digest = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
                    sess.add(
                        PasswordResetToken(
                            token_hash=digest,
                            user_id=user.id,
                            expires_at=utcnow() + timedelta(minutes=ttl),
                        )
                    )
                    user_email = user.email
                    reset_url = url_for(
                        "auth.reset_password", token=raw_token, _external=True
                    )
            if user_email is not None:
                send_password_reset(user_email, reset_url, ttl)
                audit_record("PASSWORD_RESET_REQUESTED", f"email:{user_email}")
            # Luôn trả thông báo chung: không tiết lộ email có tồn tại hay không.
            success = (
                "Nếu email tồn tại trong hệ thống, liên kết đặt lại mật khẩu "
                f"đã được gửi (hiệu lực {ttl} phút)."
            )

    status = 400 if error and request.method == "POST" else 200
    return (
        render_template(
            "auth/forgot.html", error=error, success=success, email=email
        ),
        status,
    )


@bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token: str) -> tuple[str, int] | str:
    """Trang đặt mật khẩu mới từ liên kết trong email."""
    error: str | None = None
    success: str | None = None
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    valid_link = False

    with get_db().session() as sess:
        record_row = sess.scalars(
            select(PasswordResetToken).where(PasswordResetToken.token_hash == digest)
        ).first()
        now = utcnow()
        valid_link = (
            record_row is not None
            and record_row.used_at is None
            and record_row.expires_at > now
        )

        if not valid_link:
            error = "Liên kết không hợp lệ, đã dùng hoặc đã hết hạn."
        elif request.method == "POST":
            new_password = request.form.get("new_password") or ""
            confirm = request.form.get("confirm_password") or ""
            if len(new_password) < 8:
                error = "Mật khẩu phải có ít nhất 8 ký tự."
            elif new_password != confirm:
                error = "Mật khẩu xác nhận không khớp."
            else:
                user = sess.get(User, record_row.user_id)
                if user is None:
                    error = "Tài khoản không còn tồn tại."
                else:
                    user.password_hash = hash_password(new_password)
                    record_row.used_at = now
                    # Thu hồi mọi phiên cũ sau khi đổi mật khẩu.
                    for session_row in sess.scalars(
                        select(AuthSession).where(
                            AuthSession.user_id == user.id,
                            AuthSession.revoked_at.is_(None),
                        )
                    ).all():
                        session_row.revoked_at = now
                    sess.flush()
                    success = "Đặt lại mật khẩu thành công. Bạn có thể đăng nhập."
                    audit_record(
                        "PASSWORD_RESET", f"user:{user.id}", actor_id=user.id
                    )

    status = 400 if error and request.method == "POST" else 200
    return (
        render_template(
            "auth/reset_password.html",
            token=token,
            error=error,
            success=success,
            valid=valid_link,
        ),
        status,
    )