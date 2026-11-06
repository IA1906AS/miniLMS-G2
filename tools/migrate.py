"""Migration nhẹ (idempotent) cho các cột/bảng mới.

Chạy: .venv\\Scripts\\python.exe tools\\migrate.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import text

from web import create_web_app
from web.database import get_db


def main() -> int:
    app = create_web_app()
    with app.app_context():
        db = get_db()
        db.create_all()  # tạo bảng mới (password_reset_tokens, ...)
        with db.engine.begin() as conn:
            dialect = conn.dialect.name
            if dialect == "postgresql":
                conn.execute(
                    text(
                        "ALTER TABLE courses ADD COLUMN IF NOT EXISTS "
                        "enroll_code VARCHAR(20)"
                    )
                )
                conn.execute(
                    text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS ix_courses_enroll_code "
                        "ON courses (enroll_code)"
                    )
                )
                conn.execute(
                    text(
                        "UPDATE courses SET enroll_code = upper(id) || '-2026' "
                        "WHERE enroll_code IS NULL"
                    )
                )
                conn.execute(
                    text(
                        "ALTER TABLE notifications ADD COLUMN IF NOT EXISTS "
                        "sender_id VARCHAR(16) REFERENCES users(id)"
                    )
                )
                conn.execute(
                    text(
                        "ALTER TABLE notifications ADD COLUMN IF NOT EXISTS "
                        "course_id VARCHAR(16) REFERENCES courses(id)"
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_notifications_sender_id "
                        "ON notifications (sender_id)"
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_notifications_course_id "
                        "ON notifications (course_id)"
                    )
                )
            elif dialect == "sqlite":
                cols = [
                    r[1]
                    for r in conn.execute(text("PRAGMA table_info(courses)")).fetchall()
                ]
                if "enroll_code" not in cols:
                    conn.execute(text("ALTER TABLE courses ADD COLUMN enroll_code VARCHAR(20)"))
                conn.execute(
                    text(
                        "UPDATE courses SET enroll_code = upper(id) || '-2026' "
                        "WHERE enroll_code IS NULL"
                    )
                )
            print(f"migrated ({dialect})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
