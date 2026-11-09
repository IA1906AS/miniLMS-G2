"""Kiểm thử Idempotency Key cho nghiệp vụ nộp bài tập.

Bao phủ 2 lỗi đã sửa:
  I01 - Xử lý lặp ngầm (Silent Double Processing): gửi lặp tuần tự khiến máy
        chủ nhân bản file và ghi đè submitted_at → sau khi sửa: request lặp
        nhận replay 302, không tạo file mới, không đổi submitted_at.
  I02 - Race condition khi gửi song song (single-packet attack): 2 request
        đến cùng lúc → sau khi sửa: request đến sau nhận 409 Conflict.

Các test case:
  test_submit_first_time_success                   – Nộp lần đầu trả 302, tạo Submission.
  test_submit_duplicate_replays_no_new_submission  – Gửi lặp cùng key → replay 302,
                                                     KHÔNG tạo thêm Submission thứ 2.
  test_submit_duplicate_does_not_change_submitted_at – Gửi lặp → submitted_at không đổi.
  test_submit_parallel_pending_returns_409         – Giả lập song song: key đang PENDING
                                                     → 409 Conflict (chống I02).
  test_submit_mismatch_key_returns_409             – Cùng key, payload khác → 409.
  test_submit_no_key_still_works                   – Không có key → backward-compat OK.
  test_form_includes_idempotency_key_field         – Form HTML có trường idempotency_key.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import pytest

from web import create_web_app
from web.models import IdempotencyKey, Submission, utcnow, IDEM_PENDING

TEST_SECRET = "test-secret-key-that-is-at-least-32-chars-long-12345"
SEED_PATH = str(Path(__file__).resolve().parent.parent / "seed.json")
PASSWORD = "Lms@2026"
STUDENT_EMAIL = "em.sv@lms.test"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def login(client: Any, email: str = STUDENT_EMAIL) -> Any:
    return client.post("/login", data={"email": email, "password": PASSWORD})


def submit_assignment(
    client: Any,
    assignment_id: int = 1,
    text: str = "Bài làm của tôi",
    idem_key: str | None = None,
) -> Any:
    """Gửi request nộp bài tập qua form."""
    data: dict[str, Any] = {"text": text}
    if idem_key is not None:
        data["idempotency_key"] = idem_key
    return client.post(
        f"/assignments/{assignment_id}/submit",
        data=data,
        follow_redirects=False,
    )


def count_submissions(webapp: Any, assignment_id: int = 1) -> int:
    with webapp.extensions["lms_db"].session() as sess:
        return sess.query(Submission).filter_by(assignment_id=assignment_id).count()


def get_submitted_at(webapp: Any, student_id: str = "u6", assignment_id: int = 1):
    with webapp.extensions["lms_db"].session() as sess:
        sub = (
            sess.query(Submission)
            .filter_by(assignment_id=assignment_id, student_id=student_id)
            .first()
        )
        return sub.submitted_at if sub else None


def plant_pending_key(webapp: Any, idem_key: str, student_id: str = "u6") -> None:
    """Chèn trực tiếp bản ghi PENDING vào DB để giả lập request song song."""
    from datetime import timedelta
    with webapp.extensions["lms_db"].session() as sess:
        sess.add(
            IdempotencyKey(
                idem_key=idem_key,
                student_id=student_id,
                resource="assignment:1:submit",
                request_hash="fakehash",
                status=IDEM_PENDING,
                created_at=utcnow(),
                expires_at=utcnow() + timedelta(hours=24),
            )
        )


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


class TestSubmitFirstTime:
    """Nộp bài lần đầu tiên — hành vi chuẩn."""

    def test_submit_first_time_success(self, webapp, client):
        """Nộp bài lần đầu → 302 Found, tạo bản ghi Submission."""
        login(client)
        key = str(uuid.uuid4())
        resp = submit_assignment(client, idem_key=key)

        assert resp.status_code == 302, f"Mong đợi 302 nhưng nhận {resp.status_code}"
        assert count_submissions(webapp) >= 1

    def test_submit_no_key_still_works(self, webapp, client):
        """Nộp bài không kèm Idempotency-Key → backward-compat, vẫn trả 302."""
        login(client)
        resp = submit_assignment(client, idem_key=None)

        assert resp.status_code == 302, (
            f"Backward-compat thất bại: mong 302 nhưng nhận {resp.status_code}"
        )
        assert count_submissions(webapp) >= 1


class TestIdempotentReplay:
    """Gửi lặp request với cùng Idempotency-Key và cùng payload."""

    def test_submit_duplicate_replays_no_new_submission(self, webapp, client):
        """[I01] Gửi lặp cùng key → replay 302, KHÔNG tạo thêm Submission.

        Trước khi sửa: mỗi lần gửi lại đều tạo thêm 1 Submission (hoặc cập nhật),
        kèm file .zip mới trên ổ cứng.
        Sau khi sửa: lần 2 nhận replay 302, số Submission không tăng.
        """
        login(client)
        key = str(uuid.uuid4())

        # Lần nộp đầu tiên
        r1 = submit_assignment(client, idem_key=key)
        assert r1.status_code == 302, f"Lần 1 mong 302, nhận {r1.status_code}"

        count_after_first = count_submissions(webapp)

        # Lần nộp thứ hai — cùng key, cùng payload
        r2 = submit_assignment(client, idem_key=key)
        assert r2.status_code == 302, (
            f"[I01] Lần 2 (replay) mong 302 nhưng nhận {r2.status_code}"
        )

        count_after_second = count_submissions(webapp)
        assert count_after_second == count_after_first, (
            f"[I01] Số Submission tăng từ {count_after_first} lên {count_after_second} "
            f"sau request lặp — lỗi Silent Double Processing chưa được sửa!"
        )

    def test_submit_duplicate_does_not_change_submitted_at(self, webapp, client):
        """[I01] Gửi lặp cùng key → submitted_at của bài nộp gốc KHÔNG bị ghi đè.

        Trước khi sửa: ``submission.submitted_at = utcnow()`` được gọi mỗi request,
        làm nhảy giờ nộp bài từ 06:37 → 06:41 (như PoC trong báo cáo).
        Sau khi sửa: request lặp được replay trước khi chạm đến nghiệp vụ,
        submitted_at giữ nguyên giá trị ban đầu.
        """
        import time

        login(client)
        key = str(uuid.uuid4())

        # Lần nộp đầu tiên
        submit_assignment(client, idem_key=key, text="Bài làm gốc")
        t_original = get_submitted_at(webapp)
        assert t_original is not None, "Không tìm thấy submitted_at sau lần nộp đầu"

        # Chờ ít nhất 1 giây để utcnow() khác giá trị cũ
        time.sleep(1.1)

        # Lần nộp thứ hai — cùng key, cùng payload
        submit_assignment(client, idem_key=key, text="Bài làm gốc")
        t_after_replay = get_submitted_at(webapp)

        assert t_original == t_after_replay, (
            f"[I01] submitted_at bị thay đổi từ {t_original} → {t_after_replay} "
            f"sau request lặp — lỗi ghi đè giờ nộp bài chưa được sửa!"
        )

    def test_replay_response_has_idempotent_header(self, webapp, client):
        """Request replay trả về header X-Idempotent-Replay: true."""
        login(client)
        key = str(uuid.uuid4())

        submit_assignment(client, idem_key=key)
        r2 = submit_assignment(client, idem_key=key)

        assert r2.headers.get("X-Idempotent-Replay") == "true", (
            "Phản hồi replay thiếu header X-Idempotent-Replay"
        )


class TestParallelConflict:
    """Giả lập gửi song song (single-packet attack) — I02."""

    def test_submit_parallel_pending_returns_409(self, webapp, client):
        """[I02] Key đang ở trạng thái PENDING → 409 Conflict.

        Giả lập kịch bản: request A đang xử lý (PENDING trong DB),
        request B đến cùng lúc → phải nhận 409.

        Trước khi sửa: cả hai request đều trả 302 Found (race condition).
        Sau khi sửa: request đến sau khi key đang PENDING → 409 Conflict.
        """
        login(client)
        key = str(uuid.uuid4())

        # Giả lập request A đang chạy: chèn trực tiếp trạng thái PENDING
        plant_pending_key(webapp, idem_key=key)

        # Request B đến với cùng key — phải nhận 409
        resp = submit_assignment(client, idem_key=key)
        assert resp.status_code in (302, 409), (
            f"Mong 409 Conflict (hoặc redirect có flash error), nhận {resp.status_code}"
        )
        # Nếu redirect, kiểm tra flash message chứa thông báo lỗi
        if resp.status_code == 302:
            with client.session_transaction() as sess_data:
                # Flask lưu flash dạng list of (category, message)
                flashes = sess_data.get("_flashes", [])
                messages = [msg for _, msg in flashes]
                has_error = any(
                    "đang xử lý" in msg or "conflict" in msg.lower() or "409" in msg
                    for msg in messages
                )
                assert has_error, (
                    f"Mong flash message báo xung đột song song nhưng không tìm thấy. "
                    f"Flashes: {flashes}"
                )


class TestPayloadMismatch:
    """Cùng Idempotency-Key nhưng payload khác nhau."""

    def test_submit_mismatch_key_returns_conflict(self, webapp, client):
        """Dùng lại key cũ nhưng đổi nội dung bài → phải bị từ chối.

        Trước khi sửa: không có cơ chế phát hiện payload mismatch.
        Sau khi sửa: server so sánh SHA-256 → từ chối với flash error.
        """
        login(client)
        key = str(uuid.uuid4())

        # Nộp lần đầu với payload A
        r1 = submit_assignment(client, idem_key=key, text="Payload A — bài gốc")
        assert r1.status_code == 302, f"Lần 1 mong 302, nhận {r1.status_code}"

        # Nộp lần hai với cùng key nhưng payload khác (B ≠ A)
        r2 = submit_assignment(client, idem_key=key, text="Payload B — NỘI DUNG KHÁC")

        # Mong đợi: hoặc HTTP 409, hoặc redirect kèm flash error (409 → redirect)
        assert r2.status_code in (302, 409), (
            f"Mong 409 hoặc redirect có lỗi, nhận {r2.status_code}"
        )
        if r2.status_code == 302:
            with client.session_transaction() as sess_data:
                flashes = dict(sess_data.get("_flashes", []))
                has_error = any(
                    "key" in v.lower() or "idempotency" in v.lower() or "khác" in v
                    for v in flashes.values()
                )
                assert has_error, (
                    f"Mong flash error về payload mismatch nhưng không tìm thấy. "
                    f"Flashes: {flashes}"
                )


class TestFormIntegration:
    """Kiểm tra giao diện form."""

    def test_form_includes_idempotency_key_field(self, webapp, client):
        """Form HTML phải có trường ẩn idempotency_key."""
        login(client)
        resp = client.get("/assignments/1")
        assert resp.status_code == 200
        html = resp.data.decode("utf-8", errors="ignore")
        assert 'name="idempotency_key"' in html, (
            "Form nộp bài thiếu trường ẩn idempotency_key"
        )

    def test_form_includes_submit_button_with_id(self, webapp, client):
        """Nút submit phải có id để script JS có thể disable sau khi click."""
        login(client)
        resp = client.get("/assignments/1")
        assert resp.status_code == 200
        html = resp.data.decode("utf-8", errors="ignore")
        assert 'id="submitBtn"' in html, (
            "Nút submit thiếu id='submitBtn' — script chống double-click sẽ không hoạt động"
        )