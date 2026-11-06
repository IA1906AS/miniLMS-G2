"""Sinh hướng dẫn PoC bằng Burp Suite cho tính năng sửa điểm."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm, Pt

from make_report_docx import code_block, label, numbered  # noqa: E402
from make_spec_docx import (  # noqa: E402
    GRAY,
    NAVY,
    add_page_number,
    add_table,
    body,
    bullet,
    heading,
    set_run_font,
)

OUT = ROOT / "docs" / "Huong_dan_PoC_Burp_sua_diem.docx"


def main() -> int:
    doc = Document()
    section = doc.sections[0]
    section.page_width = Cm(21)
    section.page_height = Cm(29.7)
    section.top_margin = Cm(2)
    section.bottom_margin = Cm(2)
    section.left_margin = Cm(2)
    section.right_margin = Cm(2)

    normal = doc.styles["Normal"]
    normal.font.name = "Times New Roman"
    normal.font.size = Pt(11)

    hp = section.header.paragraphs[0]
    hp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    run = hp.add_run("Hướng dẫn PoC bằng Burp Suite — miniLMS")
    set_run_font(run, size=9, italic=True, color=GRAY)
    add_page_number(section.footer.paragraphs[0])

    # ---------------- Bìa ----------------
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(60)
    run = p.add_run("HƯỚNG DẪN TÁI HIỆN PoC")
    set_run_font(run, size=24, bold=True, color=NAVY)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run("Tính năng sửa điểm — miniLMS")
    set_run_font(run, size=16, bold=True, color=NAVY)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(36)
    run = p.add_run("Thực hiện bằng Burp Suite · So sánh nhánh lỗi và nhánh đã sửa")
    set_run_font(run, size=12, italic=True, color=GRAY)

    add_table(
        doc,
        ["Mục", "Nội dung"],
        [
            ["Hệ thống", "miniLMS — http://127.0.0.1:8888"],
            ["Nhánh lỗi", "sua-diem-vuln"],
            ["Nhánh đã sửa", "sua-diem-fixed"],
            ["Tài khoản", "admin@lms.test / an.gv@lms.test — mật khẩu Lms@2026"],
            ["Công cụ", "Burp Suite (Proxy + Repeater), trình duyệt của Burp, psql"],
            ["Mục tiêu", "Chụp ảnh PoC cho V01 (lost update), V02 (500), V03 (dữ liệu sai)"],
        ],
        [4.0, 13.0],
        font_size=10,
    )

    # ---------------- 1. Chuẩn bị ----------------
    heading(doc, "1. Chuẩn bị môi trường", 1)
    numbered(doc, "1. Mở terminal tại thư mục dự án, chạy: git checkout sua-diem-vuln")
    numbered(doc, "2. Chạy run.bat (PostgreSQL + web) và đăng nhập thử một tài khoản.")
    numbered(doc, "3. Mở Burp Suite → Proxy → Intercept is off; bật trình duyệt của Burp.")
    numbered(doc, "4. Truy cập http://127.0.0.1:8888, đăng nhập admin@lms.test / Lms@2026.")
    numbered(doc, "5. Chụp lại màn hình terminal + trình duyệt làm ảnh môi trường.")

    label(doc, "Lấy ID bản ghi để tấn công")
    body(doc, "Mở terminal thứ hai và chạy (mật khẩu PostgreSQL chỉ dùng cho dev):")
    code_block(
        doc,
        "$env:PGPASSWORD='lms_dev_2026'\n"
        "& 'D:\\Setup\\Postgre SQL\\bin\\psql.exe' -U lms_dev -d lms_dev -c \"\n"
        "  select id, assignment_id, student_id, score, feedback from submissions order by id;\n"
        "  select id, quiz_id, student_id, score, passed, status from quiz_attempts order by id;\"",
    )
    body(doc, "Ghi lại submission_id và attempt_id; các bước dưới dùng <sid>, <aid>.")

    label(doc, "Tạo dữ liệu mẫu nếu DB trống")
    code_block(
        doc,
        "insert into submissions (assignment_id, student_id, text, submitted_at, score, feedback, graded_at)\n"
        "values (1, 'u4', 'Bài làm mẫu', now(), 5, 'Tốt', now());\n\n"
        "insert into quiz_attempts (quiz_id, student_id, started_at, submitted_at, score, passed, status)\n"
        "values (1, 'u5', now(), now(), 5, false, 'SUBMITTED');",
    )

    # ---------------- 2. Cấu hình Burp ----------------
    heading(doc, "2. Cấu hình Burp Suite", 1)
    numbered(doc, "1. Proxy → Options → Proxy listeners: thêm 127.0.0.1:8080 (nếu chưa có).")
    numbered(doc, "2. Proxy → Intercept: để Off trong lúc thao tác, dùng HTTP history để bắt request.")
    numbered(doc, "3. Mở trình duyệt Burp: tab Proxy → Open browser.")
    numbered(doc, "4. Trong trình duyệt Burp, truy cập http://127.0.0.1:8888/login và đăng nhập.")
    numbered(doc, "5. Thao tác bình thường trên web; mọi request hiện ở Proxy → HTTP history.")
    numbered(doc, "6. Chuột phải request cần phân tích → Send to Repeater (Ctrl+R).")
    numbered(doc, "7. Ở Repeater, bấm Send (Ctrl+Space hoặc nút Send) và chụp tab này.")
    body(doc, "Vì web chạy HTTP nội bộ nên không cần cài CA certificate cho các bước này.",
         italic=True, size=10)

    # ---------------- 3. V01 ----------------
    heading(doc, "3. PoC V01 — Hai người sửa điểm, người sau ghi đè", 1)
    add_table(doc, ["Mục", "Nội dung"], [
        ["Endpoint", "POST /admin/grades/assignment/<sid>/adjust"],
        ["Body", "score=<điểm>&feedback=<nhận xét>  (nhánh lỗi không có version)"],
        ["Kỳ vọng lỗi", "Cả hai lần gửi đều 302; DB chỉ còn điểm của lần sau"],
        ["Kỳ vọng sau sửa", "Lần 1: 302; lần 2: 409 Conflict; DB giữ điểm lần 1"],
    ], [4.0, 12.4], font_size=9.5)

    label(doc, "Các bước tạo PoC")
    numbered(doc, "1. Đăng nhập admin, mở /admin/grades, cuộn tới Assignment Submissions.")
    numbered(doc, "2. Ở dòng của <sid>, nhập điểm 9 và bấm Lưu (để Burp bắt request).")
    numbered(doc, "3. Vào Proxy → HTTP history, tìm POST /admin/grades/assignment/<sid>/adjust.")
    numbered(doc, "4. Chuột phải → Send to Repeater. Đây là request của “người A”.")
    numbered(doc, "5. Bấm Send lần 1 → chụp ảnh (302). Kiểm tra DB: score = 9.")
    numbered(doc, "6. Không sửa gì, bấm Send lần 2 (mô phỏng “người B” giữ dữ liệu cũ).")
    numbered(doc, "7. Nhánh lỗi: vẫn 302 và DB thành điểm mới. Chụp ảnh mâu thuẫn.")
    numbered(doc, "8. Chuyển sang nhánh sua-diem-fixed, lặp lại: lần 2 phải trả 409.")
    body(doc, "Trên nhánh đã sửa, request có thêm trường version (hidden input); Repeater giữ nguyên "
              "version cũ nên lần gửi thứ hai bị từ chối.", italic=True, size=10)

    label(doc, "Request mẫu (nhánh lỗi)")
    code_block(
        doc,
        "POST /admin/grades/assignment/<sid>/adjust HTTP/1.1\n"
        "Host: 127.0.0.1:8888\n"
        "Cookie: lms_token=<token>\n"
        "Content-Type: application/x-www-form-urlencoded\n\n"
        "score=9&feedback=T%E1%BB%91t",
    )
    label(doc, "Request mẫu (nhánh đã sửa)")
    code_block(
        doc,
        "POST /admin/grades/assignment/<sid>/adjust HTTP/1.1\n"
        "Host: 127.0.0.1:8888\n"
        "Cookie: lms_token=<token>\n"
        "Content-Type: application/x-www-form-urlencoded\n\n"
        "score=9&feedback=T%E1%BB%91t&version=1",
    )
    label(doc, "Response cần chụp")
    code_block(
        doc,
        "NHÁNH LỖI (cả 2 lần):  HTTP/1.1 302 FOUND\n"
        "  Location: /admin/grades\n\n"
        "NHÁNH ĐÃ SỬA:\n"
        "  Lần 1: HTTP/1.1 302 FOUND\n"
        "  Lần 2: HTTP/1.1 409 CONFLICT\n"
        "  Body chứa: “Điểm đã được người khác cập nhật. Vui lòng tải lại trang.”",
    )
    label(doc, "Kiểm tra DB để chụp kèm")
    code_block(
        doc,
        "select id, score, feedback from submissions where id = <sid>;\n"
        "-- Nhánh lỗi sau 2 lần: score = 9 (không phân biệt ai thắng)\n"
        "-- Nhánh sửa: score = 9, version = 2",
    )

    label(doc, "Cách 2 — hai trình duyệt (nếu muốn minh hoạ 2 người)")
    bullet(doc, "Đăng nhập cùng tài khoản ở cửa sổ thường và cửa sổ ẩn danh (2 cookie khác nhau).", 10.5)
    bullet(doc, "Cả hai mở /admin/grades; A lưu 9; B lưu 2. Trên nhánh lỗi, A tải lại thấy 2.", 10.5)
    bullet(doc, "Trên nhánh sửa, B nhận trang 409 và điểm vẫn là 9.", 10.5)

    # ---------------- 4. V02 ----------------
    heading(doc, "4. PoC V02 — Chỉnh điểm quiz làm máy chủ trả 500", 1)
    add_table(doc, ["Mục", "Nội dung"], [
        ["Endpoint", "POST /admin/grades/quiz/<aid>/adjust"],
        ["Body", "score=8  (nhánh sửa thêm &version=1)"],
        ["Kỳ vọng lỗi", "HTTP 500, traceback AttributeError: 'QuizAttempt' object has no attribute 'quiz'"],
        ["Kỳ vọng sau sửa", "HTTP 302, DB score=8, passed=True"],
    ], [4.0, 12.4], font_size=9.5)

    numbered(doc, "1. Mở /admin/grades, cuộn tới Quiz Attempts.")
    numbered(doc, "2. Nhập điểm 8 ở dòng <aid> và bấm Lưu.")
    numbered(doc, "3. Burp bắt POST /admin/grades/quiz/<aid>/adjust → Send to Repeater.")
    numbered(doc, "4. Bấm Send; nhánh lỗi trả 500 kèm traceback (debug đang bật).")
    numbered(doc, "5. Chụp toàn bộ trang 500, đặc biệt dòng AttributeError và tên tệp admin.py.")
    numbered(doc, "6. Chuyển nhánh fixed, lặp lại: 302, DB cập nhật đúng.")

    code_block(
        doc,
        "POST /admin/grades/quiz/<aid>/adjust HTTP/1.1\n"
        "Host: 127.0.0.1:8888\n"
        "Cookie: lms_token=<token>\n"
        "Content-Type: application/x-www-form-urlencoded\n\n"
        "score=8",
    )
    label(doc, "Ảnh cần chụp")
    bullet(doc, "Response 500 + traceback (nhánh lỗi).", 10.5)
    bullet(doc, "Response 302 + DB score=8, passed=True (nhánh sửa).", 10.5)
    bullet(doc, "psql: select id, score, passed from quiz_attempts where id=<aid>;", 10.5)

    # ---------------- 5. V03 ----------------
    heading(doc, "5. PoC V03 — Điểm ngoài miền và mất nhận xét", 1)
    add_table(doc, ["Mục", "Nội dung"], [
        ["Endpoint", "POST /admin/grades/assignment/<sid>/adjust"],
        ["Body", "score=99 (không gửi feedback)"],
        ["Kỳ vọng lỗi", "302; DB score=99, feedback bị xoá thành rỗng"],
        ["Kỳ vọng sau sửa", "302 kèm flash lỗi; DB không đổi, feedback giữ nguyên"],
    ], [4.0, 12.4], font_size=9.5)

    numbered(doc, "1. Đảm bảo bài nộp <sid> có score=5, feedback=“Tốt” (xem mục 1).")
    numbered(doc, "2. Bắt request chỉnh điểm ở /admin/grades → Send to Repeater.")
    numbered(doc, "3. Sửa body thành score=99, xoá dòng feedback; bấm Send.")
    numbered(doc, "4. Nhánh lỗi: 302, DB score=99 và feedback rỗng. Chụp psql + response.")
    numbered(doc, "5. Nhánh sửa: 302 nhưng DB vẫn 5/“Tốt”; mở lại /admin/grades thấy banner lỗi.")
    numbered(doc, "6. Gửi tiếp score=7 (không feedback): nhánh sửa giữ “Tốt”, nhánh lỗi xoá tiếp.")

    code_block(
        doc,
        "POST /admin/grades/assignment/<sid>/adjust HTTP/1.1\n"
        "Host: 127.0.0.1:8888\n"
        "Cookie: lms_token=<token>\n"
        "Content-Type: application/x-www-form-urlencoded\n\n"
        "score=99",
    )
    label(doc, "Ảnh cần chụp")
    bullet(doc, "Repeater body score=99 và response 302 (nhánh lỗi).", 10.5)
    bullet(doc, "psql: score=99, feedback='' (nhánh lỗi).", 10.5)
    bullet(doc, "Trang /admin/grades hiện “Điểm phải nằm trong khoảng 0–10.0.” (nhánh sửa).", 10.5)
    bullet(doc, "psql: score=5, feedback='Tốt' (nhánh sửa).", 10.5)

    # ---------------- 6. Checklist ----------------
    heading(doc, "6. Checklist ảnh PoC", 1)
    add_table(
        doc,
        ["STT", "Ảnh", "Nhánh", "Nội dung"],
        [
            ["1", "Môi trường", "vuln", "Terminal run.bat + Burp + trang login"],
            ["2", "HTTP history", "vuln", "Danh sách request POST sửa điểm"],
            ["3", "Repeater lần 1", "vuln", "Request/response 302"],
            ["4", "Repeater lần 2", "vuln", "Vẫn 302, DB bị ghi đè"],
            ["5", "psql trước/sau", "vuln", "score thay đổi, feedback rỗng"],
            ["6", "Repeater 500", "vuln", "V02 traceback AttributeError"],
            ["7", "Repeater lần 2", "fixed", "409 Conflict, body thông báo"],
            ["8", "psql sau", "fixed", "score giữ 9, version=2"],
            ["9", "Trang lỗi", "fixed", "Banner “Điểm đã được người khác cập nhật”"],
            ["10", "Repeater V02", "fixed", "302 thay vì 500"],
            ["11", "psql V03", "fixed", "score=5, feedback='Tốt'"],
        ],
        [1.0, 3.6, 2.0, 9.8],
        font_size=9,
    )
    body(doc, "Mỗi ảnh nên thấy rõ: URL, request body, status code, và (nếu được) kết quả psql cùng màn hình.",
         italic=True, size=10)

    # ---------------- 7. Mẹo ----------------
    heading(doc, "7. Mẹo chụp PoC rõ ràng", 1)
    bullet(doc, "Bật “Follow redirects” khi cần xem thông báo flash ở trang đích; tắt khi cần chụp 302/409.", 10.5)
    bullet(doc, "Trong Repeater, bôi đậm/đánh dấu dòng score và version; chụp cả tab Response.", 10.5)
    bullet(doc, "Đặt psql cạnh Burp và chụp chung một ảnh để thấy request ↔ dữ liệu.", 10.5)
    bullet(doc, "Ghi rõ tên nhánh trong ảnh (tiêu đề cửa sổ terminal hoặc chú thích).", 10.5)
    bullet(doc, "Với V01, chụp thêm tab HTTP history chứng minh hai request giống nhau.", 10.5)

    # ---------------- 8. Phụ lục ----------------
    doc.add_page_break()
    heading(doc, "Phụ lục — Lệnh reset dữ liệu giữa các lần demo", 1)
    code_block(
        doc,
        "update submissions set score=5, feedback='Tốt'\n"
        "where assignment_id=1 and student_id='u4';\n\n"
        "update quiz_attempts set score=5, passed=false, status='SUBMITTED'\n"
        "where id=<aid>;\n\n"
        "-- Xem lại\n"
        "select id, score, feedback from submissions order by id;\n"
        "select id, score, passed, status from quiz_attempts order by id;",
    )
    body(doc, "Lưu ý: nhánh sua-diem-vuln không có cột version trong model; DB có thể vẫn còn cột này "
              "từ lần chạy nhánh fixed — không ảnh hưởng PoC.", italic=True, size=10)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(OUT)
    print(f"saved: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
