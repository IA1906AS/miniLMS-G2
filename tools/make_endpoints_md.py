"""Sinh docs/endpoints.md từ tools/routes.json (dùng chung nhãn với file DOCX)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from make_spec_docx import EP_LABEL, ep_roles  # noqa: E402


def main() -> int:
    routes = json.loads((ROOT / "tools" / "routes.json").read_text(encoding="utf-8"))
    groups = {
        "main": "Trang công khai & dashboard",
        "auth": "Xác thực",
        "student": "Sinh viên",
        "quiz": "Quiz & bài tập",
        "files": "Tệp & ảnh",
        "instructor": "Giảng viên",
        "admin": "Quản trị",
        "api": "REST API",
    }
    lines = [
        "# Danh sách endpoint — miniLMS",
        "",
        f"Tổng cộng **{len(routes)}** route (sinh tự động từ `url_map`, "
        "khớp Phụ lục A của file đặc tả).",
        "",
    ]
    for bp, title in groups.items():
        rows = [r for r in routes if r["blueprint"] == bp]
        if not rows:
            continue
        lines += [f"## {title} ({len(rows)})", "", "| Method | Endpoint | Chức năng | Vai trò |", "|---|---|---|---|"]
        for row in rows:
            ep = row["endpoint"]
            methods = ", ".join(row["methods"])
            lines.append(
                f"| `{methods}` | `{row['rule']}` | {EP_LABEL.get(ep, ep)} | "
                f"{ep_roles(row['rule'], ep, row['methods'])} |"
            )
        lines.append("")

    out = ROOT / "docs" / "endpoints.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"saved: {out} ({len(routes)} routes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
