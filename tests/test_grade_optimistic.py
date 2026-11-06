"""Kiểm thử Optimistic Locking cho nghiệp vụ sửa điểm.

Bao phủ 3 lỗi đã sửa:
  V01 - mất cập nhật khi hai người sửa cùng lúc (version conflict -> 409)
  V02 - chỉnh điểm quiz làm máy chủ 500 (AttributeError attempt.quiz)
  V03 - nhận xét bị xoá khi yêu cầu không gửi trường feedback
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from web import create_web_app
from web.models import Quiz, QuizAttempt, Submission, utcnow

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


def login(client: Any, email: str) -> Any:
    return client.post("/login", data={"email": email, "password": PASSWORD})


def make_submission(webapp, *, score: float = 5.0, feedback: str | None = "Tốt") -> int:
    with webapp.extensions["lms_db"].session() as sess:
        sub = Submission(
            assignment_id=1,
            student_id="u4",
            text="Bài làm",
            submitted_at=utcnow(),
            score=score,
            feedback=feedback,
            graded_at=utcnow(),
            version=1,
        )
        sess.add(sub)
        sess.flush()
        return sub.id


def make_attempt(webapp, *, score: float = 5.0) -> int:
    with webapp.extensions["lms_db"].session() as sess:
        attempt = QuizAttempt(
            quiz_id=1,
            student_id="u4",
            status="SUBMITTED",
            score=score,
            passed=False,
            started_at=utcnow(),
            submitted_at=utcnow(),
            version=1,
        )
        sess.add(attempt)
        sess.flush()
        return attempt.id


def read_submission(webapp, sub_id: int) -> Submission:
    with webapp.extensions["lms_db"].session() as sess:
        return sess.get(Submission, sub_id)


def read_attempt(webapp, attempt_id: int) -> QuizAttempt:
    with webapp.extensions["lms_db"].session() as sess:
        return sess.get(QuizAttempt, attempt_id)


# ---------------------------------------------------------------------------
# V01 - lost update
# ---------------------------------------------------------------------------


def test_sua_diem_dung_version_va_giu_nhan_xet(client, webapp):
    sub_id = make_submission(webapp, score=5.0, feedback="Tốt")
    login(client, "an.gv@lms.test")

    res = client.post(
        f"/assignments/1/submissions/{sub_id}/grade",
        data={"score": "9", "version": "1"},
    )
    assert res.status_code == 302

    sub = read_submission(webapp, sub_id)
    assert sub.score == 9.0
    assert sub.version == 2
    # Không gửi feedback => giữ nguyên nhận xét cũ (V03)
    assert sub.feedback == "Tốt"


def test_sua_diem_version_cu_tra_409_va_khong_ghi_de(client, webapp):
    sub_id = make_submission(webapp, score=5.0, feedback="Tốt")
    login(client, "an.gv@lms.test")

    # Người A lưu thành công -> version 2
    assert client.post(
        f"/assignments/1/submissions/{sub_id}/grade",
        data={"score": "9", "version": "1"},
    ).status_code == 302

    # Người B vẫn cầm version 1 -> phải bị chặn
    res = client.post(
        f"/assignments/1/submissions/{sub_id}/grade",
        data={"score": "2", "version": "1"},
    )
    assert res.status_code == 409
    assert "ai đó" in res.get_data(as_text=True) or "người khác" in res.get_data(as_text=True)

    sub = read_submission(webapp, sub_id)
    assert sub.score == 9.0  # không bị ghi đè
    assert sub.version == 2


def test_thieu_version_bi_tu_choi(client, webapp):
    sub_id = make_submission(webapp, score=5.0)
    login(client, "an.gv@lms.test")

    res = client.post(
        f"/assignments/1/submissions/{sub_id}/grade",
        data={"score": "9"},
    )
    assert res.status_code == 302  # redirect kèm flash lỗi
    sub = read_submission(webapp, sub_id)
    assert sub.score == 5.0
    assert sub.version == 1


def test_diem_ngoai_mien_bi_tu_choi(client, webapp):
    sub_id = make_submission(webapp, score=5.0)
    login(client, "admin@lms.test")

    for bad in ("99", "-1", "abc", "nan"):
        res = client.post(
            f"/admin/grades/assignment/{sub_id}/adjust",
            data={"score": bad, "version": "1"},
        )
        assert res.status_code == 302
        sub = read_submission(webapp, sub_id)
        assert sub.score == 5.0, f"score bị đổi với input {bad}"
        assert sub.version == 1


# ---------------------------------------------------------------------------
# V02 - quiz adjust
# ---------------------------------------------------------------------------


def test_admin_sua_diem_quiz_khong_con_500(client, webapp):
    attempt_id = make_attempt(webapp, score=5.0)
    login(client, "admin@lms.test")

    res = client.post(
        f"/admin/grades/quiz/{attempt_id}/adjust",
        data={"score": "8", "version": "1"},
    )
    assert res.status_code == 302

    attempt = read_attempt(webapp, attempt_id)
    assert attempt.score == 8.0
    assert attempt.version == 2
    with webapp.extensions["lms_db"].session() as sess:
        quiz = sess.get(Quiz, attempt.quiz_id)
        assert attempt.passed is (8.0 >= quiz.pass_score)


def test_admin_sua_diem_quiz_version_cu_tra_409(client, webapp):
    attempt_id = make_attempt(webapp, score=5.0)
    login(client, "admin@lms.test")

    assert client.post(
        f"/admin/grades/quiz/{attempt_id}/adjust",
        data={"score": "8", "version": "1"},
    ).status_code == 302

    res = client.post(
        f"/admin/grades/quiz/{attempt_id}/adjust",
        data={"score": "1", "version": "1"},
    )
    assert res.status_code == 409
    attempt = read_attempt(webapp, attempt_id)
    assert attempt.score == 8.0
    assert attempt.version == 2


def test_bang_diem_hien_thi_version(client, webapp):
    sub_id = make_submission(webapp, score=7.0)
    attempt_id = make_attempt(webapp, score=6.0)
    login(client, "admin@lms.test")

    res = client.get("/admin/grades")
    assert res.status_code == 200
    body = res.get_data(as_text=True)
    assert f'name="version" value="1"' in body
    assert "v1" in body
