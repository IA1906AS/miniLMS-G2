from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Đường dẫn mặc định, create_app() gán lại theo config AUDIT_LOG_PATH để
# services.py ghi audit mà không cần import flask (lớp 4 không phụ thuộc flask).
_default_log_path: str = "audit.log"


def configure(audit_log_path: str) -> None:
    global _default_log_path
    _default_log_path = str(audit_log_path)


def log_event(
    actor_id: str | None,
    action: str,
    resource: str,
    result: str,
    old_score: float | None = None,
    new_score: float | None = None,
    **extra: Any,
) -> None:
    """Ghi audit theo đường dẫn đã cấu hình (dùng từ services.py)."""
    log_audit(
        _default_log_path,
        actor_id,
        action,
        resource,
        result,
        old_score,
        new_score,
        **extra,
    )


def log_audit(
    audit_log_path: str,
    actor_id: str | None,
    action: str,
    resource: str,
    result: str,
    old_score: float | None = None,
    new_score: float | None = None,
    **extra: Any,
) -> None:
    """Write an audit entry in NDJSON format. Never logs passwords or tokens."""
    entry: dict[str, Any] = {
        "ts": datetime.now(UTC).isoformat(),
        "actorId": actor_id,
        "action": action,
        "resource": resource,
        "result": result,
    }
    if old_score is not None:
        entry["oldScore"] = old_score
    if new_score is not None:
        entry["newScore"] = new_score

    # Include any safe extra data if provided, ensuring passwords/tokens are excluded
    for key, val in extra.items():
        if key.lower() not in {"password", "token", "accesstoken", "password_hash"}:
            entry[key] = val

    log_path = Path(audit_log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
