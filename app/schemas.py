"""Lớp 5 - validate body đầu vào.

Chỉ chấp nhận đúng một field ``score`` là số thực/int trong [0, 10].
Từ chối chuỗi "10", boolean, và mọi field thừa (ví dụ ``courseId`` trong body).
"""

from typing import Any

from .errors import ValidationError

SCORE_MIN = 0
SCORE_MAX = 10
ALLOWED_KEYS = frozenset({"score"})


def _score(value: Any) -> int | float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValidationError()
    if not SCORE_MIN <= value <= SCORE_MAX:  # NaN cũng rơi vào đây
        raise ValidationError()
    return value


def parse_score_update(body: Any) -> dict[str, int | float]:
    if not isinstance(body, dict):
        raise ValidationError()
    if set(body) - ALLOWED_KEYS:
        raise ValidationError()
    if "score" not in body:
        raise ValidationError()
    return {"score": _score(body["score"])}
