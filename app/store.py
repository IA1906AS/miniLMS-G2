from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import bcrypt


class Store:
    def __init__(self) -> None:
        self.users: dict[str, dict[str, Any]] = {}
        self.users_by_email: dict[str, str] = {}
        self.courses: dict[str, dict[str, Any]] = {}
        self.enrollments: list[dict[str, Any]] = []
        # email -> {"count": int, "locked_until": float}
        self.failed_logins: dict[str, dict[str, Any]] = {}
        # token -> {"email": str, "expires_at": float}
        self.reset_tokens: dict[str, dict[str, Any]] = {}
        # Counter for auto-generating user IDs
        self._user_counter: int = 0

    def load_seed(self, seed_path: str = "seed.json") -> None:
        path = Path(seed_path)
        if not path.is_file():
            # If relative path not found, try searching from workspace root
            alt_path = Path(__file__).resolve().parent.parent / seed_path
            if alt_path.is_file():
                path = alt_path
            else:
                raise FileNotFoundError(f"Seed file not found: {seed_path}")

        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        # 1. Users: hash passwords immediately, never keep plain text!
        self.users.clear()
        self.users_by_email.clear()
        for u in data.get("users", []):
            raw_password = u.get("password", "")
            # bcrypt cost >= 10
            hashed = bcrypt.hashpw(
                raw_password.encode("utf-8"), bcrypt.gensalt(rounds=10)
            ).decode("utf-8")
            user_entry = {
                "id": u["id"],
                "email": u["email"],
                "role": u["role"],
                "password_hash": hashed,
            }
            self.users[u["id"]] = user_entry
            self.users_by_email[u["email"].strip().lower()] = u["id"]
            # Track max numeric suffix for ID generation
            if u["id"].startswith("u"):
                try:
                    num = int(u["id"][1:])
                    if num > self._user_counter:
                        self._user_counter = num
                except ValueError:
                    pass

        # 2. Courses
        self.courses.clear()
        for c in data.get("courses", []):
            self.courses[c["id"]] = {
                "id": c["id"],
                "title": c["title"],
                "instructorId": c["instructorId"],
            }

        # 3. Enrollments
        self.enrollments.clear()
        for e in data.get("enrollments", []):
            self.enrollments.append(
                {
                    "courseId": e["courseId"],
                    "studentId": e["studentId"],
                    "score": float(e["score"]),
                }
            )

    def get_user_by_id(self, user_id: str) -> dict[str, Any] | None:
        user = self.users.get(user_id)
        return dict(user) if user else None

    def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        uid = self.users_by_email.get(email.strip().lower())
        if not uid:
            return None
        return self.get_user_by_id(uid)

    def get_actor(self, user_id: str) -> dict[str, Any] | None:
        """Return actor dict containing only {"id", "email", "role"}."""
        user = self.users.get(user_id)
        if not user:
            return None
        return {
            "id": user["id"],
            "email": user["email"],
            "role": user["role"],
        }

    def get_course(self, course_id: str) -> dict[str, Any] | None:
        course = self.courses.get(course_id)
        return dict(course) if course else None

    def get_enrollment(self, course_id: str, student_id: str) -> dict[str, Any] | None:
        for e in self.enrollments:
            if e["courseId"] == course_id and e["studentId"] == student_id:
                return dict(e)
        return None

    def get_course_enrollments(self, course_id: str) -> list[dict[str, Any]]:
        return [dict(e) for e in self.enrollments if e["courseId"] == course_id]

    def update_score(self, course_id: str, student_id: str, score: float) -> float:
        for e in self.enrollments:
            if e["courseId"] == course_id and e["studentId"] == student_id:
                old_score = float(e["score"])
                e["score"] = float(score)
                return old_score
        raise KeyError(
            f"Enrollment not found for course {course_id} and student {student_id}"
        )

    # Brute-force helpers
    def is_account_locked(self, email: str, now: float) -> bool:
        normalized = email.strip().lower()
        record = self.failed_logins.get(normalized)
        if not record:
            return False
        locked_until = record.get("locked_until", 0.0)
        if now < locked_until:
            return True
        # If lock expired, reset
        if locked_until > 0 and now >= locked_until:
            self.failed_logins.pop(normalized, None)
        return False

    def record_login_failure(self, email: str, now: float) -> tuple[int, bool]:
        normalized = email.strip().lower()
        record = self.failed_logins.setdefault(
            normalized, {"count": 0, "locked_until": 0.0}
        )
        record["count"] += 1
        is_locked = False
        if record["count"] >= 5:
            record["locked_until"] = now + 15 * 60  # Lock for 15 minutes
            is_locked = True
        return record["count"], is_locked

    def record_login_success(self, email: str) -> None:
        normalized = email.strip().lower()
        self.failed_logins.pop(normalized, None)

    # -----------------------------------------------------------------
    # User registration & management
    # -----------------------------------------------------------------

    def create_user(self, email: str, password_hash: str, role: str) -> dict[str, Any]:
        """Create a new user and return the actor dict (without password_hash)."""
        self._user_counter += 1
        new_id = f"u{self._user_counter}"
        # Guard against collision (edge case if seed used non-standard IDs)
        while new_id in self.users:
            self._user_counter += 1
            new_id = f"u{self._user_counter}"

        user_entry: dict[str, Any] = {
            "id": new_id,
            "email": email.strip().lower(),
            "role": role,
            "password_hash": password_hash,
        }
        self.users[new_id] = user_entry
        self.users_by_email[email.strip().lower()] = new_id
        return {
            "id": new_id,
            "email": user_entry["email"],
            "role": role,
        }

    def update_password(self, user_id: str, new_password_hash: str) -> None:
        """Update password_hash for an existing user."""
        user = self.users.get(user_id)
        if user is None:
            raise KeyError(f"User not found: {user_id}")
        user["password_hash"] = new_password_hash

    # -----------------------------------------------------------------
    # Password reset token management
    # -----------------------------------------------------------------

    def store_reset_token(self, token: str, email: str, expires_at: float) -> None:
        """Save a password-reset token (in-memory, TTL-based)."""
        self.reset_tokens[token] = {
            "email": email.strip().lower(),
            "expires_at": expires_at,
        }

    def consume_reset_token(self, token: str, now: float) -> str:
        """Validate and consume a reset token; returns the associated email.

        Raises TokenInvalidError if not found, TokenExpiredError if expired.
        """
        from app.errors import TokenExpiredError, TokenInvalidError

        record = self.reset_tokens.get(token)
        if record is None:
            raise TokenInvalidError("Reset token is invalid or already used")
        if now >= record["expires_at"]:
            self.reset_tokens.pop(token, None)
            raise TokenExpiredError("Reset token has expired")
        # Consume (one-time use)
        self.reset_tokens.pop(token, None)
        return str(record["email"])


_current_store: Store | None = None


def init_store(seed_path: str = "seed.json") -> Store:
    global _current_store
    store = Store()
    store.load_seed(seed_path)
    _current_store = store
    return store


def get_store() -> Store:
    global _current_store
    if _current_store is None:
        return init_store()
    return _current_store
