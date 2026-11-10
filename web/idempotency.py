"""Defensive Pattern #2: Idempotency Key cho tính năng Nộp bài tập.


Luồng sử dụng (xem quiz.py → assignment_submit):
  1. Client gửi form kèm trường ẩn ``idempotency_key`` (UUID v4, sinh phía JS).
  2. ``begin_idempotent_request()`` cố INSERT bản ghi PENDING ngay lập tức.
     - Thành công  → trả ``(NEW, record)``  — tiến hành xử lý nghiệp vụ.
     - PENDING tồn tại → ``(PENDING, record)``  → route trả 409 Conflict.
     - COMPLETED + hash khớp → ``(REPLAY, record)``  → route replay redirect cũ.
     - COMPLETED + hash khác → ``(MISMATCH, record)`` → route trả 422.
     - FAILED → ``(FAILED, record)`` → cho phép client thử lại.
  3. ``complete_idempotent_request()`` đánh dấu COMPLETED + lưu response_location.
  4. ``fail_idempotent_request()`` đánh dấu FAILED nếu xảy ra lỗi hệ thống,
     giải phóng khoá để client có thể retry bằng cùng key.
"""

from __future__ import annotations

import hashlib
from datetime import timedelta
from typing import Literal

from sqlalchemy import exc as sa_exc
from sqlalchemy import select
from sqlalchemy.orm import Session
from werkzeug.datastructures import FileStorage

from web.models import (
    IDEM_COMPLETED,
    IDEM_FAILED,
    IDEM_PENDING,
    IdempotencyKey,
    utcnow,
)

# Thời gian sống mặc định của một Idempotency Key.
_KEY_TTL = timedelta(hours=24)

# Kiểu trạng thái trả về từ begin_idempotent_request.
BeginResult = Literal["NEW", "PENDING", "REPLAY", "MISMATCH", "FAILED"]


# ---------------------------------------------------------------------------
# Hàm hỗ trợ
# ---------------------------------------------------------------------------


def compute_request_hash(text: str, file: FileStorage | None) -> str:
    """Tính SHA-256 của payload (text + nội dung file nếu có).

    Sử dụng streaming để không chiếm quá nhiều RAM với file lớn.
    Con trỏ đọc của ``file`` được reset về đầu sau khi băm xong để
    ``save_upload()`` gọi tiếp theo vẫn đọc được đầy đủ nội dung.
    """
    h = hashlib.sha256()
    h.update(text.encode("utf-8"))

    if file is not None and file.filename:
        # Đọc từng khối 64 KB để không chiếm RAM với file lớn
        while True:
            chunk = file.stream.read(65536)
            if not chunk:
                break
            h.update(chunk)
        # Reset con trỏ về đầu để save_upload() đọc lại bình thường
        file.stream.seek(0)

    return h.hexdigest()


# ---------------------------------------------------------------------------
# API chính
# ---------------------------------------------------------------------------


def begin_idempotent_request(
    sess: Session,
    idem_key: str,
    student_id: str,
    resource: str,
    request_hash: str,
) -> tuple[BeginResult, IdempotencyKey | None]:
    """Mở một thao tác idempotent.

    Thực hiện INSERT nguyên tử bản ghi PENDING.  Nếu UNIQUE constraint vi phạm
    (key đã tồn tại), đọc bản ghi hiện có và phân loại trạng thái.

    Args:
        sess:         SQLAlchemy Session đang mở.
        idem_key:     Giá trị Idempotency-Key từ client.
        student_id:   ID sinh viên thực hiện thao tác.
        resource:     Chuỗi định danh nghiệp vụ, ví dụ "assignment:5:submit".
        request_hash: SHA-256 của payload, tính bằng ``compute_request_hash()``.

    Returns:
        (status, record):
          - ``("NEW",      record)``  — key mới, ghi PENDING thành công.
          - ``("PENDING",  record)``  — key đang được xử lý song song → 409.
          - ``("REPLAY",   record)``  — key đã COMPLETED, hash khớp → replay.
          - ``("MISMATCH", record)``  — key đã COMPLETED, hash khác → 422.
          - ``("FAILED",   record)``  — key FAILED, cho phép thử lại.
    """
    now = utcnow()
    new_record = IdempotencyKey(
        idem_key=idem_key,
        student_id=student_id,
        resource=resource,
        request_hash=request_hash,
        status=IDEM_PENDING,
        created_at=now,
        expires_at=now + _KEY_TTL,
    )

    try:
        with sess.begin_nested():
            sess.add(new_record)
            sess.flush()  # Gây UNIQUE constraint violation ngay nếu key đã tồn tại
        return ("NEW", new_record)

    except sa_exc.IntegrityError:
        # Savepoint được rollback tự động bởi begin_nested context manager
        # Đọc bản ghi hiện có
        existing = sess.scalars(
            select(IdempotencyKey).where(
                IdempotencyKey.idem_key == idem_key,
                IdempotencyKey.student_id == student_id,
            )
        ).first()

        if existing is None:
            # Rất hiếm: bản ghi vừa bị xoá bởi TTL cleanup → coi như NEW
            return ("FAILED", None)

        if existing.status == IDEM_PENDING:
            return ("PENDING", existing)

        if existing.status == IDEM_COMPLETED:
            # Chỉ replay khi khớp cả resource nghiệp vụ lẫn hash payload
            if existing.resource == resource and existing.request_hash == request_hash:
                return ("REPLAY", existing)
            return ("MISMATCH", existing)

        # IDEM_FAILED — cho phép thử lại bằng cách xoá bản ghi cũ
        with sess.begin_nested():
            sess.delete(existing)
            sess.flush()
            new_record2 = IdempotencyKey(
                idem_key=idem_key,
                student_id=student_id,
                resource=resource,
                request_hash=request_hash,
                status=IDEM_PENDING,
                created_at=now,
                expires_at=now + _KEY_TTL,
            )
            sess.add(new_record2)
            sess.flush()
        return ("NEW", new_record2)


def complete_idempotent_request(
    sess: Session,
    record: IdempotencyKey,
    response_location: str,
) -> None:
    """Đánh dấu thao tác idempotent hoàn thành.

    Lưu địa chỉ redirect để các request lặp sau này có thể replay.

    Args:
        sess:              SQLAlchemy Session đang mở.
        record:            Bản ghi IdempotencyKey trả về từ ``begin_idempotent_request``.
        response_location: Đường dẫn redirect (ví dụ "/assignments/5").
    """
    record.status = IDEM_COMPLETED
    record.response_location = response_location
    record.completed_at = utcnow()
    sess.flush()


def fail_idempotent_request(sess: Session, record: IdempotencyKey) -> None:
    """Đánh dấu thao tác idempotent thất bại do lỗi hệ thống.

    Giải phóng khoá để client có thể thử lại với cùng key (không phải lỗi
    nghiệp vụ — lỗi nghiệp vụ nên để PENDING → caller xử lý riêng).

    Args:
        sess:   SQLAlchemy Session đang mở.
        record: Bản ghi IdempotencyKey trả về từ ``begin_idempotent_request``.
    """
    record.status = IDEM_FAILED
    record.completed_at = utcnow()
    sess.flush()
