"""Lớp 5 - validate body đầu vào.

Chỉ chấp nhận đúng một field ``score`` là số trong [0, 10].
Từ chối chuỗi "10", boolean, và mọi field thừa (ví dụ ``courseId`` trong body).
"""

from __future__ import annotations

from typing import Any

from app.errors import ValidationError

SCORE_MIN = 0
SCORE_MAX = 10
ALLOWED_KEYS = frozenset({"score"})


def _score(value: Any) -> int | float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValidationError("score phải là số")
    if not SCORE_MIN <= value <= SCORE_MAX:  # NaN cũng rơi vào đây
        raise ValidationError("score phải trong [0, 10]")
    return value


def parse_score_update(body: Any) -> dict[str, int | float]:
    if not isinstance(body, dict):
        raise ValidationError("Request body must be a JSON object")
    if set(body) - ALLOWED_KEYS:
        raise ValidationError("Chỉ chấp nhận field score")
    if "score" not in body:
        raise ValidationError("score là bắt buộc")
    return {"score": _score(body["score"])}
