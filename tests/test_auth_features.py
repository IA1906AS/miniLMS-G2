"""Tests cho các tính năng xác thực mới: đăng ký, đặt lại mật khẩu, đổi mật khẩu.

Bao gồm các kiểm tra bảo mật:
- R*: Register tests
- FP*: Forgot-password tests
- RP*: Reset-password tests
- CP*: Change-password tests
- AC*: Admin create user tests
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from app import create_app

TEST_SECRET = "test-secret-key-that-is-at-least-32-chars-long-12345"


@pytest.fixture
def app():
    return create_app({"JWT_SECRET": TEST_SECRET})


@pytest.fixture
def client(app):
    return app.test_client()


def _login(client, email: str, password: str = "Lms@2026") -> str:
    """Helper: login và trả về accessToken."""
    res = client.post("/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, f"Login failed: {res.get_json()}"
    return res.get_json()["accessToken"]


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ===========================================================================
# Register tests
# ===========================================================================


class TestRegister:
    def test_r1_register_student_success(self, client):
        """R1: Đăng ký STUDENT hợp lệ → 201, trả về {id, email, role}."""
        res = client.post(
            "/auth/register",
            json={
                "email": "newstudent@example.com",
                "password": "StrongP@ss1",
                "role": "STUDENT",
            },
        )
        assert res.status_code == 201
        body = res.get_json()
        assert body["email"] == "newstudent@example.com"
        assert body["role"] == "STUDENT"
        assert "id" in body
        assert "password" not in body
        assert "password_hash" not in body

    def test_r2_register_instructor_success(self, client):
        """R2: Đăng ký INSTRUCTOR hợp lệ → 201."""
        res = client.post(
            "/auth/register",
            json={
                "email": "newinstructor@example.com",
                "password": "StrongP@ss1",
                "role": "INSTRUCTOR",
            },
        )
        assert res.status_code == 201
        assert res.get_json()["role"] == "INSTRUCTOR"

    def test_r3_duplicate_email_returns_409(self, client):
        """R3: Đăng ký email đã tồn tại → 409 CONFLICT."""
        res = client.post(
            "/auth/register",
            json={
                "email": "chi.sv@lms.test",  # đã có trong seed
                "password": "StrongP@ss1",
                "role": "STUDENT",
            },
        )
        assert res.status_code == 409
        assert res.get_json() == {"error": "CONFLICT"}

    def test_r4_cannot_register_as_admin(self, client):
        """R4: Đăng ký với role=ADMIN → 400 VALIDATION_ERROR."""
        res = client.post(
            "/auth/register",
            json={
                "email": "hacker@example.com",
                "password": "StrongP@ss1",
                "role": "ADMIN",
            },
        )
        assert res.status_code == 400
        assert res.get_json() == {"error": "VALIDATION_ERROR"}

    def test_r5_weak_password_rejected(self, client):
        """R5: Mật khẩu yếu → 400."""
        for weak_pass in ["short", "alllowercase1!", "ALLUPPERCASE1!", "NoSpecial1"]:
            res = client.post(
                "/auth/register",
                json={
                    "email": f"user_{weak_pass}@example.com",
                    "password": weak_pass,
                    "role": "STUDENT",
                },
            )
            assert res.status_code == 400, f"Expected 400 for password: {weak_pass}"

    def test_r6_invalid_email_rejected(self, client):
        """R6: Email không hợp lệ → 400."""
        for bad_email in ["notanemail", "no_at_sign", "@nodomain"]:
            res = client.post(
                "/auth/register",
                json={
                    "email": bad_email,
                    "password": "StrongP@ss1",
                    "role": "STUDENT",
                },
            )
            assert res.status_code == 400

    def test_r7_missing_field_rejected(self, client):
        """R7: Thiếu field bắt buộc → 400."""
        res = client.post(
            "/auth/register",
            json={"email": "user@example.com", "password": "StrongP@ss1"},
            # thiếu role
        )
        assert res.status_code == 400

    def test_r8_no_password_in_response(self, client):
        """R8: Response không chứa password hay password_hash."""
        res = client.post(
            "/auth/register",
            json={
                "email": "safe@example.com",
                "password": "StrongP@ss1",
                "role": "STUDENT",
            },
        )
        body_text = res.get_data(as_text=True).lower()
        assert "password" not in body_text
        assert "password_hash" not in body_text

    def test_r9_registered_user_can_login(self, client):
        """R9: Sau đăng ký thành công, user có thể đăng nhập."""
        client.post(
            "/auth/register",
            json={
                "email": "canlogin@example.com",
                "password": "StrongP@ss1",
                "role": "STUDENT",
            },
        )
        login_res = client.post(
            "/auth/login",
            json={"email": "canlogin@example.com", "password": "StrongP@ss1"},
        )
        assert login_res.status_code == 200
        assert "accessToken" in login_res.get_json()

    def test_r10_register_public_no_token_needed(self, client):
        """R10: POST /auth/register không cần JWT."""
        # Gọi không có Authorization header
        res = client.post(
            "/auth/register",
            json={
                "email": "public@example.com",
                "password": "StrongP@ss1",
                "role": "STUDENT",
            },
        )
        assert res.status_code == 201


# ===========================================================================
# Forgot-password tests
# ===========================================================================


class TestForgotPassword:
    def test_fp1_valid_email_returns_token(self, client):
        """FP1: Email hợp lệ và tồn tại → 200, resetToken không None."""
        res = client.post(
            "/auth/forgot-password",
            json={"email": "chi.sv@lms.test"},
        )
        assert res.status_code == 200
        body = res.get_json()
        assert "message" in body
        assert body["resetToken"] is not None
        assert body["expiresIn"] == 900  # 15 phút

    def test_fp2_unknown_email_same_response(self, client):
        """FP2: Email không tồn tại → cùng 200 (tránh user enumeration)."""
        res = client.post(
            "/auth/forgot-password",
            json={"email": "unknown@example.com"},
        )
        assert res.status_code == 200
        body = res.get_json()
        # Vẫn trả về message nhưng resetToken là None
        assert "message" in body
        assert body.get("resetToken") is None

    def test_fp3_response_bodies_same_structure(self, client):
        """FP3: Response structure giống nhau cho email tồn tại và không tồn tại."""
        res_exist = client.post(
            "/auth/forgot-password",
            json={"email": "chi.sv@lms.test"},
        )
        res_unknown = client.post(
            "/auth/forgot-password",
            json={"email": "notexist@example.com"},
        )
        body_exist = res_exist.get_json()
        body_unknown = res_unknown.get_json()
        # Cùng keys
        assert set(body_exist.keys()) == set(body_unknown.keys())

    def test_fp4_public_no_token_needed(self, client):
        """FP4: POST /auth/forgot-password không cần JWT."""
        res = client.post(
            "/auth/forgot-password",
            json={"email": "chi.sv@lms.test"},
        )
        assert res.status_code == 200

    def test_fp5_invalid_body_returns_400(self, client):
        """FP5: Body không phải JSON → 400."""
        res = client.post("/auth/forgot-password", data="plain text")
        assert res.status_code == 400


# ===========================================================================
# Reset-password tests
# ===========================================================================


class TestResetPassword:
    def _get_reset_token(self, client, email: str = "chi.sv@lms.test") -> str:
        """Helper: lấy reset token từ forgot-password."""
        res = client.post("/auth/forgot-password", json={"email": email})
        return res.get_json()["resetToken"]

    def test_rp1_valid_token_resets_password(self, client):
        """RP1: Token hợp lệ + mật khẩu mới hợp lệ → 200, có thể login ngay."""
        token = self._get_reset_token(client)
        res = client.post(
            "/auth/reset-password",
            json={"resetToken": token, "newPassword": "NewP@ss123"},
        )
        assert res.status_code == 200
        assert "message" in res.get_json()

        # Verify: có thể login với mật khẩu mới
        login_res = client.post(
            "/auth/login",
            json={"email": "chi.sv@lms.test", "password": "NewP@ss123"},
        )
        assert login_res.status_code == 200

    def test_rp2_old_password_no_longer_works(self, client):
        """RP2: Sau reset, mật khẩu cũ không còn hoạt động."""
        token = self._get_reset_token(client)
        client.post(
            "/auth/reset-password",
            json={"resetToken": token, "newPassword": "NewP@ss123"},
        )

        login_old = client.post(
            "/auth/login",
            json={"email": "chi.sv@lms.test", "password": "Lms@2026"},
        )
        assert login_old.status_code == 401

    def test_rp3_token_one_time_use(self, client):
        """RP3: Reset token chỉ dùng được một lần."""
        token = self._get_reset_token(client)
        # Lần 1: thành công
        res1 = client.post(
            "/auth/reset-password",
            json={"resetToken": token, "newPassword": "NewP@ss123"},
        )
        assert res1.status_code == 200

        # Lần 2: token đã hết hạn/bị xóa
        res2 = client.post(
            "/auth/reset-password",
            json={"resetToken": token, "newPassword": "AnotherP@ss1"},
        )
        assert res2.status_code == 400
        assert res2.get_json() == {"error": "INVALID_RESET_TOKEN"}

    def test_rp4_invalid_token_rejected(self, client):
        """RP4: Token giả → 400 INVALID_RESET_TOKEN."""
        res = client.post(
            "/auth/reset-password",
            json={"resetToken": "fakefakefake12345", "newPassword": "NewP@ss123"},
        )
        assert res.status_code == 400
        assert res.get_json() == {"error": "INVALID_RESET_TOKEN"}

    def test_rp5_expired_token_rejected(self, client, app):
        """RP5: Token đã hết TTL → 410 TOKEN_EXPIRED."""
        store = app.config["STORE"]
        token = "expired_test_token_xyz"
        # Lưu token với expires_at đã qua
        store.store_reset_token(token, "chi.sv@lms.test", expires_at=time.time() - 1)

        res = client.post(
            "/auth/reset-password",
            json={"resetToken": token, "newPassword": "NewP@ss123"},
        )
        assert res.status_code == 410
        assert res.get_json() == {"error": "TOKEN_EXPIRED"}

    def test_rp6_weak_new_password_rejected(self, client):
        """RP6: Mật khẩu mới yếu → 400."""
        token = self._get_reset_token(client)
        res = client.post(
            "/auth/reset-password",
            json={"resetToken": token, "newPassword": "weak"},
        )
        assert res.status_code == 400

    def test_rp7_public_no_token_needed(self, client):
        """RP7: POST /auth/reset-password không cần JWT."""
        token = self._get_reset_token(client)
        # Gọi không có Authorization header — đây là endpoint public
        res = client.post(
            "/auth/reset-password",
            json={"resetToken": token, "newPassword": "NewP@ss123"},
        )
        assert res.status_code == 200


# ===========================================================================
# Change-password tests
# ===========================================================================


class TestChangePassword:
    def test_cp1_change_password_success(self, client):
        """CP1: Đổi mật khẩu đúng cũ, mới hợp lệ → 200."""
        token = _login(client, "chi.sv@lms.test")
        res = client.post(
            "/auth/change-password",
            json={"oldPassword": "Lms@2026", "newPassword": "NewP@ss123"},
            headers=_auth_header(token),
        )
        assert res.status_code == 200
        assert "message" in res.get_json()

    def test_cp2_old_password_wrong_returns_401(self, client):
        """CP2: Mật khẩu cũ sai → 401 INVALID_CREDENTIALS."""
        token = _login(client, "chi.sv@lms.test")
        res = client.post(
            "/auth/change-password",
            json={"oldPassword": "WrongP@ss1", "newPassword": "NewP@ss123"},
            headers=_auth_header(token),
        )
        assert res.status_code == 401
        assert res.get_json() == {"error": "INVALID_CREDENTIALS"}

    def test_cp3_new_same_as_old_rejected(self, client):
        """CP3: Mật khẩu mới trùng mật khẩu cũ → 400."""
        token = _login(client, "chi.sv@lms.test")
        res = client.post(
            "/auth/change-password",
            json={"oldPassword": "Lms@2026", "newPassword": "Lms@2026"},
            headers=_auth_header(token),
        )
        assert res.status_code == 400

    def test_cp4_requires_jwt(self, client):
        """CP4: POST /auth/change-password không có JWT → 401."""
        res = client.post(
            "/auth/change-password",
            json={"oldPassword": "Lms@2026", "newPassword": "NewP@ss123"},
        )
        assert res.status_code == 401

    def test_cp5_after_change_old_password_fails(self, client):
        """CP5: Sau khi đổi mật khẩu, mật khẩu cũ không còn hoạt động."""
        token = _login(client, "dung.sv@lms.test")
        client.post(
            "/auth/change-password",
            json={"oldPassword": "Lms@2026", "newPassword": "NewP@ss123"},
            headers=_auth_header(token),
        )
        login_old = client.post(
            "/auth/login",
            json={"email": "dung.sv@lms.test", "password": "Lms@2026"},
        )
        assert login_old.status_code == 401

    def test_cp6_after_change_new_password_works(self, client):
        """CP6: Sau khi đổi mật khẩu, mật khẩu mới hoạt động."""
        token = _login(client, "em.sv@lms.test")
        client.post(
            "/auth/change-password",
            json={"oldPassword": "Lms@2026", "newPassword": "NewP@ss123"},
            headers=_auth_header(token),
        )
        login_new = client.post(
            "/auth/login",
            json={"email": "em.sv@lms.test", "password": "NewP@ss123"},
        )
        assert login_new.status_code == 200

    def test_cp7_weak_new_password_rejected(self, client):
        """CP7: Mật khẩu mới yếu → 400."""
        token = _login(client, "chi.sv@lms.test")
        res = client.post(
            "/auth/change-password",
            json={"oldPassword": "Lms@2026", "newPassword": "weak"},
            headers=_auth_header(token),
        )
        assert res.status_code == 400


# ===========================================================================
# Admin create user tests
# ===========================================================================


class TestAdminCreateUser:
    def test_ac1_admin_creates_student(self, client):
        """AC1: ADMIN tạo STUDENT → 201."""
        admin_token = _login(client, "admin@lms.test")
        res = client.post(
            "/auth/admin/users",
            json={
                "email": "newadmin_created_student@lms.test",
                "password": "StrongP@ss1",
                "role": "STUDENT",
            },
            headers=_auth_header(admin_token),
        )
        assert res.status_code == 201
        body = res.get_json()
        assert body["role"] == "STUDENT"
        assert "password" not in body

    def test_ac2_admin_creates_admin(self, client):
        """AC2: ADMIN tạo ADMIN → 201 (chỉ ADMIN mới làm được)."""
        admin_token = _login(client, "admin@lms.test")
        res = client.post(
            "/auth/admin/users",
            json={
                "email": "new_admin@lms.test",
                "password": "StrongP@ss1",
                "role": "ADMIN",
            },
            headers=_auth_header(admin_token),
        )
        assert res.status_code == 201
        assert res.get_json()["role"] == "ADMIN"

    def test_ac3_instructor_cannot_create_user(self, client):
        """AC3: INSTRUCTOR gọi /auth/admin/users → 403."""
        inst_token = _login(client, "an.gv@lms.test")
        res = client.post(
            "/auth/admin/users",
            json={
                "email": "hacked@lms.test",
                "password": "StrongP@ss1",
                "role": "STUDENT",
            },
            headers=_auth_header(inst_token),
        )
        assert res.status_code == 403

    def test_ac4_student_cannot_create_user(self, client):
        """AC4: STUDENT gọi /auth/admin/users → 403."""
        student_token = _login(client, "chi.sv@lms.test")
        res = client.post(
            "/auth/admin/users",
            json={
                "email": "hacked@lms.test",
                "password": "StrongP@ss1",
                "role": "STUDENT",
            },
            headers=_auth_header(student_token),
        )
        assert res.status_code == 403

    def test_ac5_requires_jwt(self, client):
        """AC5: Gọi /auth/admin/users không có JWT → 401."""
        res = client.post(
            "/auth/admin/users",
            json={
                "email": "hacked@lms.test",
                "password": "StrongP@ss1",
                "role": "STUDENT",
            },
        )
        assert res.status_code == 401

    def test_ac6_duplicate_email_409(self, client):
        """AC6: ADMIN tạo user với email đã tồn tại → 409."""
        admin_token = _login(client, "admin@lms.test")
        res = client.post(
            "/auth/admin/users",
            json={
                "email": "chi.sv@lms.test",  # đã có trong seed
                "password": "StrongP@ss1",
                "role": "STUDENT",
            },
            headers=_auth_header(admin_token),
        )
        assert res.status_code == 409

    def test_ac7_created_user_can_login(self, client):
        """AC7: User được ADMIN tạo có thể đăng nhập ngay."""
        admin_token = _login(client, "admin@lms.test")
        client.post(
            "/auth/admin/users",
            json={
                "email": "freshuser@lms.test",
                "password": "FreshP@ss1",
                "role": "INSTRUCTOR",
            },
            headers=_auth_header(admin_token),
        )
        login_res = client.post(
            "/auth/login",
            json={"email": "freshuser@lms.test", "password": "FreshP@ss1"},
        )
        assert login_res.status_code == 200
