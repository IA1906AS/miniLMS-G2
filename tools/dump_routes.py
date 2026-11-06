"""Liệt kê toàn bộ route của app web ra JSON (dùng để làm phụ lục đặc tả)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from web import create_web_app


def main() -> int:
    app = create_web_app()
    rows = []
    for rule in sorted(app.url_map.iter_rules(), key=lambda r: (r.rule, r.endpoint)):
        if rule.endpoint == "static":
            continue
        methods = sorted(m for m in rule.methods if m not in {"HEAD", "OPTIONS"})
        rows.append(
            {
                "rule": rule.rule,
                "methods": methods,
                "endpoint": rule.endpoint,
                "blueprint": rule.endpoint.split(".", 1)[0],
            }
        )
    out = Path(__file__).with_name("routes.json")
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(rows)} routes -> {out}")
    for row in rows:
        print(f"{','.join(row['methods']):14} {row['rule']:60} {row['endpoint']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
