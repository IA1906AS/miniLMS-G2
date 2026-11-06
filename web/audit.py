"""Nhật ký hoạt động (spec mục 7: "Nhật ký hoạt động").

Ghi các sự kiện quan trọng vào bảng ``audit_events``: đăng nhập, đổi điểm,
thao tác quản trị... Hàm ``record`` không bao giờ làm hỏng request nghiệp vụ.
"""

from __future__ import annotations

from typing import Any

from flask import has_app_context

from web.database import get_db
from web.models import AuditEvent


def record(
    action: str,
    resource: str,
    *,
    actor_id: str | None = None,
    **detail: Any,
) -> None:
    """Ghi một sự kiện audit. Bỏ qua an toàn nếu không có app context."""
    if not has_app_context():
        return
    try:
        with get_db().session() as sess:
            sess.add(
                AuditEvent(
                    actor_id=actor_id,
                    action=action,
                    resource=resource,
                    detail=detail or {},
                )
            )
    except Exception:  # pragma: no cover - audit không được chặn nghiệp vụ
        pass
