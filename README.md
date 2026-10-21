# miniLMS

Hệ thống quản lý học tập (LMS) viết bằng Python + Flask. Repo gồm hai phần chạy độc lập:

| Phần | Entrypoint | Dữ liệu | Dùng cho |
| --- | --- | --- | --- |
| API `app/` | `flask --app app run` | in-memory từ `seed.json` | Bộ test A1–A19 của đề bài (không dùng DB) |
| Giao diện web `web/` | `flask --app webapp run` | SQLite qua SQLAlchemy | Trang chủ + trang tài khoản (homepage / account) |

## Cài đặt

```bash
uv sync            # tạo .venv và cài đúng phiên bản trong uv.lock
cp .env.example .env   # rồi sửa JWT_SECRET (bắt buộc, >= 32 ký tự)
```

`pip install -r requirements.txt` cũng dùng được nếu không có uv.

## Chạy giao diện web

```bash
flask --app webapp run          # http://127.0.0.1:5000
```

- DB mặc định: `instance/lms.db` (SQLite, đã gitignore). Đổi bằng biến `DATABASE_URL`.
- Lần chạy đầu tự tạo bảng và nạp dữ liệu từ `seed.json`; các lần sau giữ nguyên dữ liệu.
- Mật khẩu demo của mọi tài khoản: `Lms@2026`.

| Trang | Đường dẫn | Vai trò |
| --- | --- | --- |
| Trang chủ (danh sách môn, số liệu) | `/` | cả 4 vai trò, kể cả khách |
| Đăng nhập | `/login` | — |
| Trang tài khoản (hồ sơ + điểm/môn dạy) | `/account` | ADMIN, TEACHER, STUDENT |

### 4 vai trò

`ADMIN` · `TEACHER` · `STUDENT` · `GUEST` (khách chưa đăng nhập).

Giá trị `INSTRUCTOR` trong `seed.json` (bản API chấm thi) được quy đổi thành
`TEACHER` khi nạp vào DB — xem `web/database.py:normalize_role`.

## Chạy API bản thi

```bash
flask --app app run
```

Endpoint: `POST /auth/login`, `GET /me`, `GET /courses/<id>/grades`,
`PUT /courses/<id>/grades/<student_id>` (xem `de-bai.pdf`).

## Kiểm tra chất lượng

```bash
uv run pytest          # 38 test
uv run ruff check .    # lint
uv run ruff format --check .
uv run mypy            # strict: main.py, app/, web/, webapp.py
```
