from __future__ import annotations

import base64
import json
import time
from typing import Any

import pytest

from app import create_app
from app.audit import log_audit

TEST_SECRET = "test-secret-key-that-is-at-least-32-chars-long-12345"


@pytest.fixture
def app():
    return create_app({"JWT_SECRET": TEST_SECRET})


@pytest.fixture
def client(app):
    return app.test_client()


def test_a1_login_credentials_identical_response(client):
    """A1: Login khongco@lms.test vs login chi.sv@lms.test sai mật khẩu.

    Cả hai 401, body giống hệt.
    """
    res1 = client.post(
        "/auth/login",
        json={"email": "khongco@lms.test", "password": "wrong_password"},
    )
    res2 = client.post(
        "/auth/login",
        json={"email": "chi.sv@lms.test", "password": "wrong_password"},
    )

    assert res1.status_code == 401
    assert res2.status_code == 401
    assert res1.get_json() == {"error": "INVALID_CREDENTIALS"}
    assert res2.get_json() == {"error": "INVALID_CREDENTIALS"}
    assert res1.get_json() == res2.get_json()


def test_a2_get_me_without_token(client):
    """A2: GET /me không token -> 401."""
    res = client.get("/me")
    assert res.status_code == 401
    assert res.get_json() == {"error": "UNAUTHENTICATED"}


def test_a3_tampered_token_signature(client):
    """A3: Token của Chi, sửa sub thành u1, giữ chữ ký cũ -> 401."""
    # 1. Login as Chi (u4)
    res = client.post(
        "/auth/login",
        json={"email": "chi.sv@lms.test", "password": "Lms@2026"},
    )
    assert res.status_code == 200
    token = res.get_json()["accessToken"]

    # 2. Tamper token: change sub from u4 to u1, keep original signature
    header_b64, payload_b64, sig_b64 = token.split(".")

    # Pad payload_b64 for base64 decode if needed
    rem = len(payload_b64) % 4
    padded = payload_b64 + ("=" * (4 - rem) if rem else "")
    payload_dict = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
    payload_dict["sub"] = "u1"

    tampered_payload_b64 = (
        base64.urlsafe_b64encode(json.dumps(payload_dict).encode("utf-8"))
        .decode("utf-8")
        .rstrip("=")
    )
    tampered_token = f"{header_b64}.{tampered_payload_b64}.{sig_b64}"

    # 3. Request /me with tampered token
    me_res = client.get(
        "/me",
        headers={"Authorization": f"Bearer {tampered_token}"},
    )
    assert me_res.status_code == 401
    assert me_res.get_json() == {"error": "UNAUTHENTICATED"}


def test_a4_alg_none_token(client):
    """A4: Token có header alg: none -> 401."""
    header = {"alg": "none", "typ": "JWT"}
    payload = {
        "sub": "u4",
        "iat": int(time.time()),
        "exp": int(time.time() + 900),
    }

    header_b64 = (
        base64.urlsafe_b64encode(json.dumps(header).encode("utf-8"))
        .decode("utf-8")
        .rstrip("=")
    )
    payload_b64 = (
        base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8"))
        .decode("utf-8")
        .rstrip("=")
    )
    none_token = f"{header_b64}.{payload_b64}."

    res = client.get(
        "/me",
        headers={"Authorization": f"Bearer {none_token}"},
    )
    assert res.status_code == 401
    assert res.get_json() == {"error": "UNAUTHENTICATED"}


def test_a5_token_expired(client):
    """A5: TOKEN_TTL_SECONDS=1, chờ 2 giây, gọi /me -> 401."""
    expiring_app = create_app({"JWT_SECRET": TEST_SECRET, "TOKEN_TTL_SECONDS": 1})
    expiring_client = expiring_app.test_client()

    login_res = expiring_client.post(
        "/auth/login",
        json={"email": "chi.sv@lms.test", "password": "Lms@2026"},
    )
    assert login_res.status_code == 200
    token = login_res.get_json()["accessToken"]

    time.sleep(2)

    res = expiring_client.get(
        "/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 401
    assert res.get_json() == {"error": "UNAUTHENTICATED"}


def test_a6_no_passwords_leaked_in_responses(client):
    """A6: Soi mọi response -> Không có password, password_hash, passwordHash."""
    # Check login response
    login_res = client.post(
        "/auth/login",
        json={"email": "admin@lms.test", "password": "Lms@2026"},
    )
    token = login_res.get_json()["accessToken"]

    for res in [
        login_res,
        client.get("/me", headers={"Authorization": f"Bearer {token}"}),
        client.get("/courses/c1/grades", headers={"Authorization": f"Bearer {token}"}),
    ]:
        body_text = res.get_data(as_text=True).lower()
        assert "password" not in body_text
        assert "password_hash" not in body_text
        assert "passwordhash" not in body_text


def test_a16_unregistered_route_protected_by_gate(app, client):
    """A16: Thêm GET /debug không khai báo gì, gọi không token -> 401."""

    @app.route("/debug", methods=["GET"])
    def debug_route():
        return "debug_ok", 200

    res = client.get("/debug")
    assert res.status_code == 401
    assert res.get_json() == {"error": "UNAUTHENTICATED"}


def test_a17_missing_or_short_jwt_secret_raises():
    """A17: create_app() khi thiếu JWT_SECRET hoặc < 32 ký tự -> RuntimeError."""
    with pytest.raises(RuntimeError):
        create_app({"JWT_SECRET": ""})

    with pytest.raises(RuntimeError):
        create_app({"JWT_SECRET": "too-short-secret"})


def test_a18_brute_force_lockout_dung(client):
    """A18: Sai mật khẩu Dũng 5 lần, lần 6 nhập đúng -> 429 ACCOUNT_LOCKED."""
    dung_email = "dung.sv@lms.test"

    # 5 failed attempts
    for _ in range(5):
        res = client.post(
            "/auth/login",
            json={"email": dung_email, "password": "wrong_password"},
        )
        assert res.status_code == 401
        assert res.get_json() == {"error": "INVALID_CREDENTIALS"}

    # 6th attempt with correct password
    res6 = client.post(
        "/auth/login",
        json={"email": dung_email, "password": "Lms@2026"},
    )
    assert res6.status_code == 429
    assert res6.get_json() == {"error": "ACCOUNT_LOCKED"}


def test_a19_audit_log_format(tmp_path):
    """A19: Format audit log kiểm tra cấu trúc JSON, không chứa mật khẩu/token."""
    audit_file = tmp_path / "test_audit.log"
    log_audit(
        audit_log_path=str(audit_file),
        actor_id="u2",
        action="PUT",
        resource="/courses/c1/grades/u4",
        result="SUCCESS",
        old_score=7.5,
        new_score=9.0,
    )

    lines = audit_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])

    assert "ts" in record
    assert record["actorId"] == "u2"
    assert record["action"] == "PUT"
    assert record["resource"] == "/courses/c1/grades/u4"
    assert record["result"] == "SUCCESS"
    assert record["oldScore"] == 7.5
    assert record["newScore"] == 9.0

    raw_text = lines[0].lower()
    assert "password" not in raw_text
    assert "token" not in raw_text


def test_guards_and_403(app, client):
    """Test require_role decorator directly."""
    from app.guards import require_role

    @app.route("/instructor-only", methods=["GET"])
    @require_role("INSTRUCTOR")
    def instructor_only():
        return {"status": "ok"}, 200

    # 1. Login as Student Chi
    res_student = client.post(
        "/auth/login",
        json={"email": "chi.sv@lms.test", "password": "Lms@2026"},
    )
    student_token = res_student.get_json()["accessToken"]

    # Student cannot access instructor-only
    res_forbidden = client.get(
        "/instructor-only",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert res_forbidden.status_code == 403
    assert res_forbidden.get_json() == {"error": "FORBIDDEN"}

    # 2. Login as Instructor An
    res_inst = client.post(
        "/auth/login",
        json={"email": "an.gv@lms.test", "password": "Lms@2026"},
    )
    inst_token = res_inst.get_json()["accessToken"]

    # Instructor can access
    res_ok = client.get(
        "/instructor-only",
        headers={"Authorization": f"Bearer {inst_token}"},
    )
    assert res_ok.status_code == 200
    assert res_ok.get_json() == {"status": "ok"}


def test_http_error_handlers(client):
    """Test 404, 405 error handlers."""
    # 1. Login to pass gate
    login_res = client.post(
        "/auth/login",
        json={"email": "admin@lms.test", "password": "Lms@2026"},
    )
    token = login_res.get_json()["accessToken"]

    # 404 on non-existent route
    res_404 = client.get(
        "/non-existent-route",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res_404.status_code == 404
    assert res_404.get_json() == {"error": "NOT_FOUND"}

    # 405 on method not allowed (POST on /me)
    res_405 = client.post(
        "/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res_405.status_code == 405
    assert res_405.get_json() == {"error": "METHOD_NOT_ALLOWED"}


def test_gate_header_variations(client):
    """Test gate rejecting non-Bearer or malformed Authorization header."""
    res1 = client.get("/me", headers={"Authorization": "Basic 12345"})
    assert res1.status_code == 401
    assert res1.get_json() == {"error": "UNAUTHENTICATED"}

    res2 = client.get("/me", headers={"Authorization": "Bearer "})
    assert res2.status_code == 401
    assert res2.get_json() == {"error": "UNAUTHENTICATED"}


def test_login_validation_errors(client):
    """Test login endpoint with malformed bodies."""
    # Non-json body
    res1 = client.post("/auth/login", data="plain text")
    assert res1.status_code == 400
    assert res1.get_json() == {"error": "VALIDATION_ERROR"}

    # Missing email
    res2 = client.post("/auth/login", json={"password": "123"})
    assert res2.status_code == 400
    assert res2.get_json() == {"error": "VALIDATION_ERROR"}


def test_store_operations(app):
    """Test store helper methods."""
    store = app.config["STORE"]

    course = store.get_course("c1")
    assert course is not None
    assert course["title"] == "Lập trình Web"

    assert store.get_course("non-existent") is None

    enrollment = store.get_enrollment("c1", "u4")
    assert enrollment is not None
    assert enrollment["score"] == 7.5

    assert store.get_enrollment("c1", "u6") is None

    enrollments_c1 = store.get_course_enrollments("c1")
    assert len(enrollments_c1) == 2

    old = store.update_score("c1", "u4", 8.5)
    assert old == 7.5
    assert store.get_enrollment("c1", "u4")["score"] == 8.5

    with pytest.raises(KeyError):
        store.update_score("c1", "u6", 10.0)
