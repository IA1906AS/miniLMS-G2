"""LƯU TRỮ TỆP (thành phần "LƯU TRỮ TỆP" trong đặc tả).

Quy ước: DB chỉ lưu **đường dẫn tương đối**; tệp thật nằm dưới
``UPLOAD_DIR`` (mặc định ``instance/uploads``). Mọi route tải xuống đều phải
kiểm tra quyền trước khi ``send_file`` — không phục vụ trực tiếp qua static.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from flask import current_app
from werkzeug.utils import secure_filename

#: Đuôi tệp cho phép theo từng loại.
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
DOC_EXT = {
    ".pdf",
    ".doc",
    ".docx",
    ".ppt",
    ".pptx",
    ".xls",
    ".xlsx",
    ".txt",
    ".md",
    ".csv",
    ".zip",
    ".rar",
    ".7z",
}
CODE_EXT = DOC_EXT | {
    ".py",
    ".js",
    ".ts",
    ".java",
    ".c",
    ".cpp",
    ".sql",
    ".html",
    ".css",
}

#: Giới hạn kích thước (byte).
MAX_IMAGE_BYTES = 2 * 1024 * 1024
MAX_DOC_BYTES = 20 * 1024 * 1024


def upload_root() -> Path:
    configured = current_app.config.get("UPLOAD_DIR") or "instance/uploads"
    path = Path(str(configured))
    if not path.is_absolute():
        path = Path(current_app.root_path).parent / path
    path.mkdir(parents=True, exist_ok=True)
    return path


def _check(file_storage: Any, allowed: set[str], max_bytes: int) -> str:
    raw_name = file_storage.filename or ""
    suffix = Path(raw_name).suffix.lower()
    if suffix not in allowed:
        raise ValueError(f"Định dạng tệp không hỗ trợ: {suffix or '(trống)'}")
    file_storage.stream.seek(0, 2)
    size = file_storage.stream.tell()
    file_storage.stream.seek(0)
    if size <= 0:
        raise ValueError("Tệp rỗng")
    if size > max_bytes:
        raise ValueError(f"Tệp quá lớn (>{max_bytes // (1024 * 1024)}MB)")
    return suffix


def save_upload(
    file_storage: Any,
    subdir: str,
    *,
    allowed: set[str] = DOC_EXT,
    max_bytes: int = MAX_DOC_BYTES,
) -> str:
    """Lưu tệp và trả về đường dẫn tương đối dạng ``subdir/<uuid><ext>``."""
    suffix = _check(file_storage, allowed, max_bytes)
    safe_dir = secure_filename(subdir) or "misc"
    target_dir = upload_root() / safe_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}{suffix}"
    file_storage.save(target_dir / name)
    return f"{safe_dir}/{name}"


def abspath(rel_path: str) -> Path:
    """Chuyển đường dẫn tương đối trong DB thành đường dẫn tuyệt đối an toàn."""
    root = upload_root().resolve()
    candidate = (root / rel_path).resolve()
    if root not in candidate.parents and candidate != root:
        raise ValueError("Đường dẫn tệp không hợp lệ")
    return candidate


def delete_file(rel_path: str | None) -> None:
    if not rel_path:
        return
    try:
        path = abspath(rel_path)
    except ValueError:
        return
    if path.is_file():
        path.unlink(missing_ok=True)
