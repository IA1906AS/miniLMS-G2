# miniLMS

Hệ thống quản lý học tập (LMS) — **Flask + SQLAlchemy + PostgreSQL**.

Repo gồm hai phần:

| Phần | Entrypoint | Dữ liệu | Dùng cho |
| --- | --- | --- | --- |
| Giao diện web `web/` (FE + BE) | `webapp.py` | PostgreSQL | Toàn bộ tính năng LMS |
| API chấm thi `app/` | `flask --app app run` | in-memory từ `seed.json` | Bộ test A1–A19 của đề bài |

## Chạy nhanh

Bấm đúp **`run.bat`**. Script sẽ:

1. Khởi động PostgreSQL nếu chưa chạy.
2. Kiểm tra `.venv` + cài thiếu thư viện.
3. Chạy migration (idempotent).
4. Mở web tại <http://127.0.0.1:8888> và tự bật trình duyệt.

Dừng web: `Ctrl+C` trong cửa sổ đó (PostgreSQL vẫn chạy).

## Cấu hình

Sao chép `.env.example` → `.env` rồi sửa:

```env
JWT_SECRET=...                                  # bắt buộc, >= 32 ký tự
DATABASE_URL=postgresql+psycopg://lms_dev:lms_dev_2026@127.0.0.1:5432/lms_dev
UPLOAD_DIR=instance/uploads
MAIL_DIR=instance/mail
```

- PostgreSQL mặc định: DB `lms_dev`, user `lms_dev` / `lms_dev_2026` (chỉ dùng cho dev).
- Lần chạy đầu tự tạo bảng và nạp `seed.json`; các lần sau giữ nguyên dữ liệu.
- Email ở chế độ dev được ghi thành tệp `.eml` trong `instance/mail/`.

## Tài khoản demo

Mật khẩu chung: `Lms@2026`

| Vai trò | Email |
| --- | --- |
| Quản trị viên | `admin@lms.test` |
| Giảng viên | `an.gv@lms.test`, `binh.gv@lms.test` |
| Sinh viên | `chi.sv@lms.test`, `dung.sv@lms.test`, … |

## Tính năng chính

- Tài khoản: đăng ký, đăng nhập/out, quên mật khẩu qua email có hạn, đổi mật khẩu.
- Hồ sơ: cập nhật thông tin, ảnh đại diện, xem hồ sơ thành viên.
- Khoá học: tra cứu/tìm kiếm/lọc theo GV, GV tạo–sửa, ghi danh bằng mã, GV thêm SV.
- Bài tập: nộp văn bản + tệp, chặn nộp sau hạn, chấm điểm + nhận xét.
- Quiz: giới hạn lượt, cưỡng chế thời gian, chấm tự động phía server.
- Diễn đàn: đăng chủ đề/bình luận, tự sửa–xoá nội dung của mình.
- Thông báo: GV gửi cả lớp (lưu DB + email).
- Quản trị: khoá user, đổi vai trò, quản lý khoá học, **nhật ký hoạt động**.
- REST API + OpenAPI: `/api/*`, `/api/docs`.

## Defensive pattern #3 — Optimistic Locking (sửa điểm)

Sửa điểm dùng cột `version` trên `submissions` / `quiz_attempts`. Client gửi
kèm version đã đọc; lệch version trả **409 Conflict** và không ghi đè.

- Service: `web/grade_service.py`
- Bản trước khi sửa: `docs/patterns/sua_diem_truoc_khi_sua.py`
- Bằng chứng before/after: `docs/patterns/evidence.txt`
- Báo cáo kiểm thử: `docs/Bao_cao_kiem_thu_sua_diem.docx` / `.pdf`
- Hướng dẫn PoC bằng Burp Suite: `docs/Huong_dan_PoC_Burp_sua_diem.docx` / `.pdf`

## Kiểm tra chất lượng

```bash
.venv\Scripts\python.exe -m pytest -q          # 133 test
.venv\Scripts\python.exe tools\verify_db.py    # đếm bản ghi trong PostgreSQL
.venv\Scripts\python.exe tools\e2e_check.py    # 28 bước kiểm thử end-to-end
```

## Cấu trúc

```
app/            API chấm thi (in-memory)
web/            giao diện web: models, database, auth, mailer, storage, audit, blueprints/
tests/          pytest
tools/          migrate.py, verify_db.py, e2e_check.py
docs/           đặc tả đối chiếu + danh sách tính năng đã bổ sung
run.bat         khởi động PostgreSQL + web + trình duyệt
```
