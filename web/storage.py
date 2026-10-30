"""Lưu trữ tệp an toàn cho LMS.

Nguyên tắc:
  - Không bao giờ lưu vào ``web/static`` (ai có URL là tải được).
  - Tên lưu trên đĩa do server sinh (uuid), không dùng tên client gửi lên.
  - Kiểm tra magic bytes chứ không tin ``Content-Type`` hay đuôi tệp.
  - Giới hạn dung lượng và chỉ cho phép danh sách định dạng đã khai báo.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import IO

from werkzeug.datastructures import FileStorage

MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB

_SAFE_EXT = re.compile(r"^\.[a-z0-9]{1,8}$")


@dataclass(frozen=True)
class AllowedKind:
    ext: str
    mime: str
    magic: tuple[bytes, ...] = ()


ALLOWED_KINDS: dict[str, AllowedKind] = {
    "pdf": AllowedKind(".pdf", "application/pdf", (b"%PDF",)),
    "png": AllowedKind(".png", "image/png", (b"\x89PNG\r\n\x1a\n",)),
    "jpg": AllowedKind(".jpg", "image/jpeg", (b"\xff\xd8\xff",)),
    "webp": AllowedKind(".webp", "image/webp", (b"RIFF",)),
    "mp4": AllowedKind(".mp4", "video/mp4", (b"\x00\x00\x00", b"ftyp")),
    "webm": AllowedKind(".webm", "video/webm", (b"\x1aE\xdf\xa3",)),
    "mp3": AllowedKind(".mp3", "audio/mpeg", (b"ID3", b"\xff\xfb")),
    "docx": AllowedKind(".docx", "application/vnd.openxmlformats", (b"PK\x03\x04",)),
    "pptx": AllowedKind(".pptx", "application/vnd.openxmlformats", (b"PK\x03\x04",)),
    "xlsx": AllowedKind(".xlsx", "application/vnd.openxmlformats", (b"PK\x03\x04",)),
    "zip": AllowedKind(".zip", "application/zip", (b"PK\x03\x04",)),
    "txt": AllowedKind(".txt", "text/plain"),
    "csv": AllowedKind(".csv", "text/csv"),
}


class UploadRejected(Exception):
    """Tệp không được chấp nhận (đuôi, magic bytes, dung lượng)."""


def _looks_like(kind: AllowedKind, head: bytes) -> bool:
    if not kind.magic:
        return True
    if kind.ext == ".mp4":
        return b"ftyp" in head[:16]
    return any(head.startswith(magic) for magic in kind.magic)


def _kind_for(ext: str) -> AllowedKind | None:
    return ALLOWED_KINDS.get(ext.lstrip(".").lower())


def safe_extension(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if not _SAFE_EXT.match(suffix):
        raise UploadRejected("Định dạng tệp không hợp lệ.")
    return suffix


def save_upload(
    file: FileStorage,
    *,
    root: Path,
    subdir: str = "assets",
    max_bytes: int = MAX_UPLOAD_BYTES,
) -> dict[str, object]:
    """Lưu tệp vào ``root/subdir`` với tên do server sinh.

    Trả về ``{"stored_name", "mime", "size_bytes", "title"}``.
    """
    original = (file.filename or "").strip()
    if not original:
        raise UploadRejected("Chưa chọn tệp.")

    ext = safe_extension(original)
    kind = _kind_for(ext)
    if kind is None:
        raise UploadRejected(f"Không hỗ trợ định dạng {ext}.")

    stream: IO[bytes] = file.stream
    head = stream.read(512)
    stream.seek(0)
    if not _looks_like(kind, head):
        raise UploadRejected("Nội dung tệp không khớp với định dạng khai báo.")

    target_dir = root / subdir
    target_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}{ext}"
    target = target_dir / stored_name

    size = 0
    with target.open("wb") as out:
        while True:
            chunk = stream.read(64 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > max_bytes:
                out.close()
                target.unlink(missing_ok=True)
                raise UploadRejected("Tệp vượt quá dung lượng cho phép.")
            out.write(chunk)

    return {
        "stored_name": f"{subdir}/{stored_name}",
        "mime": kind.mime,
        "size_bytes": size,
        "title": original,
    }


def resolve_upload(root: Path, stored_name: str) -> Path | None:
    """Đổi ``stored_name`` trong DB thành đường dẫn thật, chặn path traversal."""
    root_resolved = root.resolve()
    candidate = (root_resolved / stored_name).resolve()
    if not candidate.is_relative_to(root_resolved) or not candidate.is_file():
        return None
    return candidate
