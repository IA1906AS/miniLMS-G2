"""Kiểm tra kết nối DB + liệt kê bảng + đếm bản ghi.

Chạy: .venv\\Scripts\\python.exe tools\\verify_db.py
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
    print("DATABASE_URL:", app.config["DATABASE_URL"])
    with app.app_context():
        db = get_db()
        with db.engine.connect() as conn:
            version = conn.execute(text("select version()")).scalar()
            print("server:", version)
            rows = conn.execute(text("select tablename from pg_tables where schemaname='public' order by 1")).fetchall()
            print("tables:", len(rows))
            for (name,) in rows:
                count = conn.execute(text(f'select count(*) from "{name}"')).scalar()
                print(f"  {name}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
