"""Test giao diện web (homepage + account page) với SQLite in-memory."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from web import create_web_app
from web.database import (
    ROLE_ADMIN,
    ROLE_GUEST,
    ROLE_STUDENT,
    ROLE_TEACHER,
    User,
    normalize_role,
)

TEST_SECRET = "test-secret-key-that-is-at-least-32-chars-long-12345"
SEED_PATH = str(Path(__file__).resolve().parent.parent / "seed.json")
PASSWORD = "Lms@2026"


@pytest.fixture
def webapp():
    return create_web_app(
        {
            "JWT_SECRET": TEST_SECRET,
            "DATABASE_URL": "sqlite://",
            "SEED_PATH": SEED_PATH,
        }
    )


@pytest.fixture
def client(webapp):
    return webapp.test_client()


def login(client: Any, email: str, password: str = PASSWORD) -> Any:
    return client.post("/login", data={"email": email, "password": password})


# ---------- 4 vai trò: ADMIN / TEACHER / STUDENT / GUEST ----------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("ADMIN", ROLE_ADMIN),
        ("admin", ROLE_ADMIN),
        ("TEACHER", ROLE_TEACHER),
        ("INSTRUCTOR", ROLE_TEACHER),  # giá trị của seed.json bản API
        ("teacher", ROLE_TEACHER),
        ("STUDENT", ROLE_STUDENT),
        ("guest", ROLE_GUEST),
        ("khong-hop-le", ROLE_GUEST),
        (None, ROLE_GUEST),
    ],
)
def test_normalize_role(raw, expected):
    assert normalize_role(raw) == expected


def test_seed_doi_instructor_thanh_teacher(webapp):
    with webapp.extensions["lms_db"].session() as sess:
        assert sess.get(User, "u2").role == ROLE_TEACHER
        assert sess.get(User, "u4").role == ROLE_STUDENT
        assert sess.get(User, "u1").role == ROLE_ADMIN


# ---------- guest ----------


def test_homepage_public_va_lists_courses(client):
    res = client.get("/")
    body = res.get_data(as_text=True)
    assert res.status_code == 200
    assert "miniLMS" in body
    assert "Lập trình Web" in body
    assert "Cơ sở dữ liệu" in body


def test_guest_thay_badge_khach_va_loi_moi_dang_nhap(client):
    body = client.get("/").get_data(as_text=True)
    assert "Khách" in body
    assert "tư cách khách" in body
    assert "Đăng nhập" in body
    # Guest không thấy điểm của ai
    assert "Điểm của bạn" not in body


def test_guest_vao_account_bi_redirect(client):
    res = client.get("/account")
    assert res.status_code == 302
    assert "/login" in res.headers["Location"]


# ---------- login ----------


def test_login_sai_mat_khau(client):
    res = login(client, "chi.sv@lms.test", "sai-mat-khau")
    assert res.status_code == 401
    assert "không đúng" in res.get_data(as_text=True)


def test_login_email_khong_ton_tai_cung_thong_diep(client):
    res = login(client, "khongco@lms.test")
    assert res.status_code == 401
    assert "không đúng" in res.get_data(as_text=True)


# ---------- STUDENT ----------


def test_student_xem_diem_cua_minh(client):
    assert login(client, "chi.sv@lms.test").status_code == 302

    body = client.get("/account").get_data(as_text=True)
    assert "chi.sv@lms.test" in body
    assert "Sinh viên" in body
    assert "Lập trình Web" in body
    assert "7.5" in body


def test_homepage_hien_diem_khi_da_dang_nhap(client):
    assert login(client, "dung.sv@lms.test").status_code == 302

    body = client.get("/").get_data(as_text=True)
    assert "Điểm của bạn" in body
    assert "8.0" in body


# ---------- TEACHER ----------


def test_teacher_chi_thay_mon_minh_day(client):
    assert login(client, "an.gv@lms.test").status_code == 302

    body = client.get("/account").get_data(as_text=True)
    assert "Giảng viên" in body
    assert "Môn tôi dạy" in body
    assert "Lập trình Web" in body
    assert "Cơ sở dữ liệu" not in body


def test_homepage_danh_dau_mon_cua_teacher(client):
    assert login(client, "an.gv@lms.test").status_code == 302

    body = client.get("/").get_data(as_text=True)
    assert "Bạn dạy" in body


# ---------- ADMIN ----------


def test_admin_thay_toan_bo_mon_va_so_lieu(client):
    assert login(client, "admin@lms.test").status_code == 302

    body = client.get("/account").get_data(as_text=True)
    assert "Toàn bộ môn học" in body
    assert "Lập trình Web" in body
    assert "Cơ sở dữ liệu" in body
    assert "Lượt ghi danh" in body


# ---------- khác ----------


def test_logout_xoa_cookie(client):
    assert login(client, "chi.sv@lms.test").status_code == 302
    assert client.post("/logout").status_code == 302
    assert client.get("/account").status_code == 302


def test_trang_khong_ton_tai_404(client):
    assert client.get("/khong-co-trang-nay").status_code == 404


def test_khong_cho_open_redirect(client):
    res = client.post(
        "/login?next=//evil.example.com",
        data={"email": "chi.sv@lms.test", "password": PASSWORD},
    )
    assert res.status_code == 302
    assert "evil.example.com" not in res.headers["Location"]


def test_login_thieu_thong_tin(client):
    res = client.post("/login", data={"email": "", "password": ""})
    assert res.status_code == 401
    assert "Vui lòng nhập đầy đủ" in res.get_data(as_text=True)


def test_login_da_dang_nhap_duoc_redirect(client):
    assert login(client, "chi.sv@lms.test").status_code == 302
    res = client.get("/login")
    assert res.status_code == 302
    assert "/account" in res.headers["Location"]


def test_login_brute_force_lockout(client):
    from app.store import get_store

    email = "chi.sv@lms.test"
    try:
        for _ in range(5):
            res = login(client, email, "sai-mat-khau")
            assert res.status_code == 401
            assert "không đúng" in res.get_data(as_text=True)

        # Lần 6 bị khóa 15 phút
        res = login(client, email, "sai-mat-khau")
        assert res.status_code == 401
        assert "bị khóa" in res.get_data(as_text=True)

        # Nhập đúng pass khi đang bị khóa cũng vẫn bị từ chối
        res = login(client, email, PASSWORD)
        assert res.status_code == 401
        assert "bị khóa" in res.get_data(as_text=True)
    finally:
        get_store().failed_logins.clear()


def test_account_vai_tro_la_bi_403(webapp):
    from unittest.mock import patch

    client = webapp.test_client()
    fake_user = {"id": "u99", "email": "unknown@lms.test", "role": "UNKNOWN"}
    with (
        patch("web.auth.current_user", return_value=fake_user),
        patch("web.views.current_user", return_value=fake_user),
    ):
        res = client.get("/account")
        assert res.status_code == 403


# ---------- register / reset-password / change-password ----------


def test_web_register_page_get(client):
    res = client.get("/register")
    assert res.status_code == 200
    assert "Đăng ký tài khoản" in res.get_data(as_text=True)


def test_web_register_success(client):
    res = client.post(
        "/register",
        data={
            "email": "newbie@lms.test",
            "password": "Password@123",
            "confirm_password": "Password@123",
            "role": "STUDENT",
        },
    )
    assert res.status_code == 302
    assert "/account" in res.headers["Location"]

    # Verify session cookie attached
    body = client.get("/account").get_data(as_text=True)
    assert "newbie@lms.test" in body


def test_web_register_validation_error(client):
    # Weak password
    res = client.post(
        "/register",
        data={
            "email": "bad@lms.test",
            "password": "123",
            "confirm_password": "123",
            "role": "STUDENT",
        },
    )
    assert res.status_code == 400
    assert "ít nhất 8 ký tự" in res.get_data(as_text=True)

    # Password mismatch
    res = client.post(
        "/register",
        data={
            "email": "mismatch@lms.test",
            "password": "Password@123",
            "confirm_password": "DifferentPassword@123",
            "role": "STUDENT",
        },
    )
    assert res.status_code == 400
    assert "không khớp" in res.get_data(as_text=True)


def test_web_register_duplicate_email(client):
    res = client.post(
        "/register",
        data={
            "email": "chi.sv@lms.test",
            "password": "Password@123",
            "confirm_password": "Password@123",
            "role": "STUDENT",
        },
    )
    assert res.status_code == 400
    assert "đã được sử dụng" in res.get_data(as_text=True)


def test_web_reset_password_page_get(client):
    res = client.get("/reset-password")
    assert res.status_code == 200
    assert "Đặt lại mật khẩu" in res.get_data(as_text=True)


def test_web_reset_password_success(client):
    res = client.post(
        "/reset-password",
        data={
            "email": "chi.sv@lms.test",
            "new_password": "NewSecret@2026",
            "confirm_password": "NewSecret@2026",
        },
    )
    assert res.status_code == 302
    assert "/login?reset=1" in res.headers["Location"]

    # Now login with new password
    login_res = login(client, "chi.sv@lms.test", "NewSecret@2026")
    assert login_res.status_code == 302


def test_web_reset_password_user_not_found(client):
    res = client.post(
        "/reset-password",
        data={
            "email": "notfound@lms.test",
            "new_password": "NewSecret@2026",
            "confirm_password": "NewSecret@2026",
        },
    )
    assert res.status_code == 400
    assert "Không tìm thấy" in res.get_data(as_text=True)


def test_web_change_password_unauthenticated(client):
    res = client.get("/change-password")
    assert res.status_code == 302
    assert "/login" in res.headers["Location"]


def test_web_change_password_success(client):
    login(client, "dung.sv@lms.test", PASSWORD)
    res = client.post(
        "/change-password",
        data={
            "old_password": PASSWORD,
            "new_password": "FreshPassword@2026",
            "confirm_password": "FreshPassword@2026",
        },
    )
    assert res.status_code == 200
    assert "thành công" in res.get_data(as_text=True)


def test_web_change_password_wrong_old(client):
    login(client, "dung.sv@lms.test", PASSWORD)
    res = client.post(
        "/change-password",
        data={
            "old_password": "WrongPassword@123",
            "new_password": "FreshPassword@2026",
            "confirm_password": "FreshPassword@2026",
        },
    )
    assert res.status_code == 400
    assert "không đúng" in res.get_data(as_text=True)
