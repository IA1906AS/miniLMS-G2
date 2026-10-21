"""Tests cho các tính năng xác thực mới: đăng ký, đặt lại mật khẩu, đổi mật khẩu.

Bao gồm các kiểm tra bảo mật:
- R*: Register tests
- RP*: Reset-password tests (sau khi login)
- ARP*: Admin reset-password tests (cho bất kỳ tài khoản nào)
- CP*: Change-password tests
- AC*: Admin create user tests
"""

from __future__ import annotations

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
# Reset-password tests (sau khi login, không reset được khi chưa login)
# ===========================================================================


class TestResetPassword:
    def test_rp1_reset_password_requires_login(self, client):
        """RP1: POST /auth/reset-password không có JWT → 401."""
        res = client.post(
            "/auth/reset-password",
            json={"newPassword": "NewP@ss123"},
        )
        assert res.status_code == 401

    def test_rp2_login_and_reset_password_success(self, client):
        """RP2: Đăng nhập bằng tài khoản và reset pass thành công → 200."""
        token = _login(client, "chi.sv@lms.test")
        res = client.post(
            "/auth/reset-password",
            json={"newPassword": "NewP@ss123"},
            headers=_auth_header(token),
        )
        assert res.status_code == 200
        assert "message" in res.get_json()

        # Login với mật khẩu cũ thất bại
        login_old = client.post(
            "/auth/login",
            json={"email": "chi.sv@lms.test", "password": "Lms@2026"},
        )
        assert login_old.status_code == 401

        # Login với mật khẩu mới thành công
        login_new = client.post(
            "/auth/login",
            json={"email": "chi.sv@lms.test", "password": "NewP@ss123"},
        )
        assert login_new.status_code == 200
        assert "accessToken" in login_new.get_json()

    def test_rp3_weak_new_password_rejected(self, client):
        """RP3: Mật khẩu mới không đủ mạnh → 400."""
        token = _login(client, "chi.sv@lms.test")
        res = client.post(
            "/auth/reset-password",
            json={"newPassword": "weak"},
            headers=_auth_header(token),
        )
        assert res.status_code == 400

    def test_rp4_missing_new_password_rejected(self, client):
        """RP4: Thiếu newPassword khi tự reset → 400."""
        token = _login(client, "chi.sv@lms.test")
        res = client.post(
            "/auth/reset-password",
            json={},
            headers=_auth_header(token),
        )
        assert res.status_code == 400

    def test_rp5_student_cannot_reset_other_user_password(self, client):
        """RP5: User thường không được reset mật khẩu của tài khoản khác → 403."""
        token = _login(client, "chi.sv@lms.test")
        # Thử truyền userId của user khác
        res1 = client.post(
            "/auth/reset-password",
            json={"userId": "u2", "newPassword": "NewP@ss123"},
            headers=_auth_header(token),
        )
        assert res1.status_code == 403

        # Thử truyền email của user khác
        res2 = client.post(
            "/auth/reset-password",
            json={"email": "an.gv@lms.test", "newPassword": "NewP@ss123"},
            headers=_auth_header(token),
        )
        assert res2.status_code == 403

    def test_rp6_invalid_json_body_returns_400(self, client):
        """RP6: Body không phải JSON → 400."""
        token = _login(client, "chi.sv@lms.test")
        res = client.post(
            "/auth/reset-password",
            data="not a json",
            headers=_auth_header(token),
        )
        assert res.status_code == 400


# ===========================================================================
# Admin reset password tests (Admin có quyền reset/đặt password cho tất cả tài khoản)
# ===========================================================================


class TestAdminResetPassword:
    def test_arp1_admin_resets_student_password_by_id(self, client):
        """ARP1: ADMIN reset mật khẩu cho user theo userId → 200."""
        admin_token = _login(client, "admin@lms.test")
        res = client.post(
            "/auth/admin/reset-password",
            json={"userId": "u2", "newPassword": "AdminSetP@ss1"},
            headers=_auth_header(admin_token),
        )
        assert res.status_code == 200
        body = res.get_json()
        assert body["userId"] == "u2"
        assert body["email"] == "an.gv@lms.test"

        # Đăng nhập bằng mật khẩu mới do Admin đặt
        login_res = client.post(
            "/auth/login",
            json={"email": "an.gv@lms.test", "password": "AdminSetP@ss1"},
        )
        assert login_res.status_code == 200

    def test_arp2_admin_resets_password_by_email(self, client):
        """ARP2: ADMIN reset mật khẩu theo email → 200."""
        admin_token = _login(client, "admin@lms.test")
        res = client.post(
            "/auth/admin/reset-password",
            json={"email": "chi.sv@lms.test", "newPassword": "AdminSetP@ss2"},
            headers=_auth_header(admin_token),
        )
        assert res.status_code == 200

        login_res = client.post(
            "/auth/login",
            json={"email": "chi.sv@lms.test", "password": "AdminSetP@ss2"},
        )
        assert login_res.status_code == 200

    def test_arp3_admin_reset_auto_generates_password_if_omitted(self, client):
        """ARP3: ADMIN reset không truyền mật khẩu mới → tự sinh mật khẩu tạm thời."""
        admin_token = _login(client, "admin@lms.test")
        res = client.post(
            "/auth/admin/reset-password",
            json={"email": "dung.sv@lms.test"},
            headers=_auth_header(admin_token),
        )
        assert res.status_code == 200
        body = res.get_json()
        assert "newPassword" in body
        generated_password = body["newPassword"]

        # Đăng nhập bằng mật khẩu tạm do hệ thống sinh
        login_res = client.post(
            "/auth/login",
            json={"email": "dung.sv@lms.test", "password": generated_password},
        )
        assert login_res.status_code == 200

    def test_arp4_instructor_cannot_call_admin_reset(self, client):
        """ARP4: INSTRUCTOR gọi /auth/admin/reset-password → 403."""
        inst_token = _login(client, "an.gv@lms.test")
        res = client.post(
            "/auth/admin/reset-password",
            json={"userId": "u2", "newPassword": "NewP@ss123"},
            headers=_auth_header(inst_token),
        )
        assert res.status_code == 403

    def test_arp5_student_cannot_call_admin_reset(self, client):
        """ARP5: STUDENT gọi /auth/admin/reset-password → 403."""
        student_token = _login(client, "chi.sv@lms.test")
        res = client.post(
            "/auth/admin/reset-password",
            json={"userId": "u1", "newPassword": "NewP@ss123"},
            headers=_auth_header(student_token),
        )
        assert res.status_code == 403

    def test_arp6_admin_reset_requires_jwt(self, client):
        """ARP6: Gọi /auth/admin/reset-password không có JWT → 401."""
        res = client.post(
            "/auth/admin/reset-password",
            json={"userId": "u1", "newPassword": "NewP@ss123"},
        )
        assert res.status_code == 401

    def test_arp7_admin_reset_target_not_found(self, client):
        """ARP7: Tài khoản mục tiêu không tồn tại → 404."""
        admin_token = _login(client, "admin@lms.test")
        res1 = client.post(
            "/auth/admin/reset-password",
            json={"userId": "non_existent_id", "newPassword": "NewP@ss123"},
            headers=_auth_header(admin_token),
        )
        assert res1.status_code == 404

        res2 = client.post(
            "/auth/admin/reset-password",
            json={"email": "notfound@lms.test", "newPassword": "NewP@ss123"},
            headers=_auth_header(admin_token),
        )
        assert res2.status_code == 404

    def test_arp8_admin_reset_missing_target(self, client):
        """ARP8: Không truyền userId hay email → 400."""
        admin_token = _login(client, "admin@lms.test")
        res = client.post(
            "/auth/admin/reset-password",
            json={"newPassword": "NewP@ss123"},
            headers=_auth_header(admin_token),
        )
        assert res.status_code == 400

    def test_arp9_admin_reset_via_reset_password_endpoint(self, client):
        """ARP9: ADMIN cũng có thể reset qua endpoint /auth/reset-password."""
        admin_token = _login(client, "admin@lms.test")
        res = client.post(
            "/auth/reset-password",
            json={"email": "em.sv@lms.test", "newPassword": "AdminSetP@ss3"},
            headers=_auth_header(admin_token),
        )
        assert res.status_code == 200

        login_res = client.post(
            "/auth/login",
            json={"email": "em.sv@lms.test", "password": "AdminSetP@ss3"},
        )
        assert login_res.status_code == 200


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
