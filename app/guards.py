from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any

from flask import g

from app.errors import Forbidden


def require_role(*roles: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Role-based access control decorator (Lớp 3: Vai trò).

    Checks whether g.current_user has one of the allowed roles.
    Raises Forbidden (403) on failure.
    """

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            user = getattr(g, "current_user", None)
            if not user or user.get("role") not in roles:
                raise Forbidden("Insufficient role permissions")
            return fn(*args, **kwargs)

        return wrapper

    return decorator
