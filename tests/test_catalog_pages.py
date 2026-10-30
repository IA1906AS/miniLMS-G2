"""Test các trang danh mục khoá học (blueprint catalog)."""

from __future__ import annotations

from pathlib import Path

import pytest

from web import create_web_app

TEST_SECRET = "test-secret-key-that-is-at-least-32-chars-long-12345"
SEED_PATH = str(Path(__file__).resolve().parent.parent / "seed.json")
PASSWORD = "Lms@2026"


@pytest.fixture
def webapp(tmp_path):
    return create_web_app(
        {
            "JWT_SECRET": TEST_SECRET,
            "DATABASE_URL": "sqlite://",
            "SEED_PATH": SEED_PATH,
            "UPLOAD_ROOT": str(tmp_path / "uploads"),
        }
    )


@pytest.fixture
def client(webapp):
    return webapp.test_client()


def login(client, email: str) -> None:
    res = client.post("/login", data={"email": email, "password": PASSWORD})
    assert res.status_code == 302


def test_catalog_public(client):
    res = client.get("/catalog/")
    body = res.get_data(as_text=True)
    assert res.status_code == 200
    assert "Lập trình Web" in body


def test_catalog_search(client):
    body = client.get("/catalog/?q=Lập trình").get_data(as_text=True)
    assert "Lập trình Web" in body
    assert "Cơ sở dữ liệu" not in body


def test_catalog_filter_by_tag(client):
    assert "Khoá mới" not in client.get("/catalog/?tag=web").get_data(as_text=True)


def test_course_detail_shows_outline(client):
    body = client.get("/catalog/c1").get_data(as_text=True)
    assert "Lập trình Web" in body
    assert "Giới thiệu môn học" in body
    assert "Chương 1" in body


def test_unknown_course_404(client):
    assert client.get("/catalog/khong-co").status_code == 404


def test_guest_cannot_create_course(client):
    assert client.get("/catalog/manage/new").status_code == 302
    assert client.post("/catalog/manage/new", data={"title": "Hack"}).status_code == 302


def test_teacher_creates_course(client):
    login(client, "an.gv@lms.test")
    res = client.post(
        "/catalog/manage/new",
        data={
            "title": "Khoá mới của An",
            "description": "Mô tả",
            "price": "0",
            "status": "PUBLISHED",
            "tags": "web, python",
        },
    )
    assert res.status_code == 302
    body = client.get("/catalog/").get_data(as_text=True)
    assert "Khoá mới của An" in body


def test_student_cannot_create_course(client):
    login(client, "chi.sv@lms.test")
    assert client.get("/catalog/manage/new").status_code == 403


def test_student_enrolls_in_free_course(client):
    login(client, "em.sv@lms.test")
    res = client.post("/catalog/c1/enroll")
    assert res.status_code == 302
    body = client.get("/catalog/c1").get_data(as_text=True)
    assert "Đã ghi danh" in body or "Ghi danh thành công" in body


def test_teacher_edits_own_course_but_not_others(client):
    login(client, "an.gv@lms.test")
    assert client.get("/catalog/manage/c1").status_code == 200
    assert client.get("/catalog/manage/c2").status_code == 403
