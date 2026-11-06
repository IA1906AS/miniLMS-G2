"""Sinh báo cáo kiểm thử tính năng sửa điểm (.docx) theo mẫu mau_bao_cao_kiem_thu.pdf."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

from make_spec_docx import (  # noqa: E402
    GRAY,
    NAVY,
    add_page_number,
    add_table,
    body,
    bullet,
    heading,
    set_cell_bg,
    set_run_font,
)

OUT = ROOT / "docs" / "Bao_cao_kiem_thu_sua_diem.docx"
BEFORE_CODE = ROOT / "docs" / "patterns" / "sua_diem_truoc_khi_sua.py"
EVIDENCE = ROOT / "docs" / "patterns" / "evidence.txt"


def code_block(doc: Document, text: str, size: float = 8.5) -> None:
    table = doc.add_table(rows=1, cols=1)
    table.style = "Table Grid"
    cell = table.rows[0].cells[0]
    set_cell_bg(cell, "F5F5F5")
    tr_pr = table.rows[0]._tr.get_or_add_trPr()
    cant_split = OxmlElement("w:cantSplit")
    tr_pr.append(cant_split)
    cell.text = ""
    p = cell.paragraphs[0]
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.line_spacing = 1.0
    lines = text.rstrip("\n").split("\n")
    for idx, line in enumerate(lines):
        run = p.add_run(line)
        run.font.name = "Courier New"
        run._element.rPr.rFonts.set(qn("w:eastAsia"), "Courier New")
        run.font.size = Pt(size)
        if idx < len(lines) - 1:
            run.add_break()
    doc.add_paragraph().paragraph_format.space_after = Pt(2)


def numbered(doc: Document, text: str) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Cm(0.7)
    p.paragraph_format.first_line_indent = Cm(-0.5)
    p.paragraph_format.space_after = Pt(3)
    run = p.add_run(text)
    set_run_font(run, size=10.5)


def label(doc: Document, text: str) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(6)
    p.paragraph_format.space_after = Pt(2)
    p.paragraph_format.keep_with_next = True
    run = p.add_run(text)
    set_run_font(run, size=11, bold=True)


def badge_line(doc: Document, code: str, level: str) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(6)
    run = p.add_run(f"{code}   ·   Mức độ: {level}")
    set_run_font(run, size=10.5, bold=True, color=NAVY)


def info_table(doc: Document, rows: list[tuple[str, str]]) -> None:
    add_table(doc, ["Mục", "Nội dung"], [list(r) for r in rows], [4.0, 13.0], font_size=10)


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

    header_p = section.header.paragraphs[0]
    header_p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    hr = header_p.add_run("Báo cáo kiểm thử — miniLMS")
    set_run_font(hr, size=9, italic=True, color=GRAY)
    add_page_number(section.footer.paragraphs[0])

    # ---------------- Trang bìa ----------------
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(60)
    r = p.add_run("BÁO CÁO KIỂM THỬ")
    set_run_font(r, size=24, bold=True, color=NAVY)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("Tính năng sửa điểm — miniLMS")
    set_run_font(r, size=16, bold=True, color=NAVY)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(40)
    r = p.add_run("Áp dụng defensive pattern #3: Optimistic Locking")
    set_run_font(r, size=12, italic=True, color=GRAY)

    info_table(
        doc,
        [
            ("Hệ thống", "miniLMS — Hệ thống quản lý học tập"),
            ("Nhóm", "Nhóm 02"),
            ("Thành viên", "Sinh viên A (MSSV) — phụ trách sửa điểm\nSinh viên B (MSSV) — phụ trách nộp bài"),
            ("Phiên bản", "v1.0 — nhánh optimistic-locking"),
            ("Môi trường", "http://127.0.0.1:8888"),
            ("Công nghệ", "Python 3.12, Flask, SQLAlchemy, PostgreSQL 18"),
            ("Thời gian", "05/11/2026 – 06/11/2026"),
            ("Phạm vi", "Chức năng sửa điểm bài nộp và điểm bài kiểm tra; phân quyền liên quan"),
            ("Ngoài phạm vi", "Đồng bộ nhiều máy chủ, dịch vụ email, thanh toán, tấn công từ chối dịch vụ"),
            ("Công cụ", "pytest (133 test); script tools/pattern_evidence.py; Flask test client mô phỏng HTTP; PostgreSQL psql"),
        ],
    )

    # ---------------- 1. Thông tin chung ----------------
    heading(doc, "1. Thông tin chung", 1)
    body(
        doc,
        "Báo cáo kiểm thử chức năng sửa điểm của miniLMS sau khi áp dụng Optimistic Locking. "
        "Mục tiêu: xác nhận các lỗi nhân tạo đã được tái hiện ở bản trước khi sửa, được khắc phục "
        "ở bản sau khi sửa và không còn tái diễn.",
    )

    # ---------------- 2. Tóm tắt ----------------
    heading(doc, "2. Tóm tắt kết quả", 1)
    body(
        doc,
        "Kiểm thử được thực hiện trong hai ngày trên môi trường dev với PostgreSQL. "
        "Ba lỗi được phát hiện và đã khắc phục: một lỗi mất cập nhật khi hai người sửa cùng lúc "
        "(mức CAO), một lỗi máy chủ trả 500 khi chỉnh điểm quiz và một lỗi thiếu kiểm tra dữ liệu "
        "khiến điểm ngoài miền được chấp nhận và nhận xét bị xoá (mức TRUNG BÌNH). "
        "Toàn bộ 133 test đều đạt, trong đó 7 test mới bao phủ trực tiếp nghiệp vụ sửa điểm.",
    )

    add_table(
        doc,
        ["Mức độ", "Số lượng"],
        [["CAO", "1"], ["TRUNG BÌNH", "2"], ["THẤP", "0"], ["THÔNG TIN", "0"], ["Tổng", "3"]],
        [6.0, 4.0],
        font_size=10,
    )

    label(doc, "Tiêu chí phân loại mức độ")
    bullet(doc, "CAO: làm sai dữ liệu học vụ hoặc cho phép thay đổi điểm của người khác mà không bị phát hiện.", 10.5)
    bullet(doc, "TRUNG BÌNH: chức năng lỗi/không dùng được hoặc làm mất dữ liệu phụ, cần quyền hợp lệ để khai thác.", 10.5)
    bullet(doc, "THẤP: ảnh hưởng giao diện, khó khai thác hoặc tác động không đáng kể.", 10.5)
    bullet(doc, "THÔNG TIN: không phải lỗ hổng trực tiếp, là điểm cần cải thiện.", 10.5)

    # ---------------- 3. Tổng hợp ----------------
    heading(doc, "3. Tổng hợp lỗi", 1)
    add_table(
        doc,
        ["Mã", "Tên lỗi", "Mức độ", "Vị trí", "Đã sửa", "Kiểm tra lại"],
        [
            ["V01", "Mất cập nhật khi hai người sửa điểm cùng lúc (lost update)", "CAO",
             "POST /assignments/{id}/submissions/{sid}/grade\nPOST /admin/grades/assignment/{sid}/adjust\nPOST /admin/grades/quiz/{aid}/adjust", "⊠", "⊠"],
            ["V02", "Máy chủ trả 500 khi chỉnh điểm quiz", "TRUNG BÌNH",
             "POST /admin/grades/quiz/{aid}/adjust", "⊠", "⊠"],
            ["V03", "Thiếu kiểm tra dữ liệu: nhận điểm ngoài miền, xoá nhận xét", "TRUNG BÌNH",
             "POST /admin/grades/assignment/{sid}/adjust", "⊠", "⊠"],
        ],
        [1.1, 4.4, 1.9, 6.4, 1.3, 1.5],
        font_size=8.5,
        header_size=9,
    )

    # ---------------- 4. Chi tiết ----------------
    heading(doc, "4. Chi tiết lỗi", 1)
    body(doc, "Mỗi lỗi trình bày theo cấu trúc: vị trí, mô tả, bước tái hiện, bằng chứng, tác động, "
              "nguyên nhân trong mã nguồn, biện pháp khắc phục và kết quả kiểm tra lại.", italic=True, size=10)

    # ===== V01 =====
    heading(doc, "V01 — Mất cập nhật khi hai người sửa điểm cùng lúc (lost update)", 2)
    badge_line(doc, "V01", "CAO")
    label(doc, "Vị trí")
    body(doc, "POST /assignments/{id}/submissions/{sid}/grade; POST /admin/grades/assignment/{sid}/adjust; "
              "POST /admin/grades/quiz/{aid}/adjust.")
    label(doc, "Mô tả")
    body(doc, "Máy chủ đọc bản ghi điểm rồi ghi đè mà không kiểm tra bản ghi đã bị người khác sửa kể từ lúc "
              "biểu mẫu được tải hay chưa. Hai giảng viên/quản trị mở cùng một bản ghi, người lưu sau ghi đè "
              "thay đổi của người trước; hệ thống không báo xung đột.")
    label(doc, "Các bước tái hiện")
    numbered(doc, "1. Đăng nhập giảng viên A, mở bài nộp có điểm 5 và nhận xét “Tốt”.")
    numbered(doc, "2. Đăng nhập giảng viên B trên trình duyệt khác, mở cùng bài nộp.")
    numbered(doc, "3. A nhập 9 và lưu. Cơ sở dữ liệu ghi score = 9.")
    numbered(doc, "4. B (vẫn đang thấy điểm 5) nhập 2 và lưu. Cơ sở dữ liệu ghi score = 2.")
    numbered(doc, "5. A tải lại trang: điểm 9 đã biến mất, không có thông báo nào.")
    label(doc, "Bằng chứng")
    code_block(
        doc,
        "POST /admin/grades/assignment/1/adjust\n"
        "score=2&version=1\n\n"
        "TRƯỚC KHI SỬA\n"
        "  HTTP/1.1 302 Found\n"
        "  DB: score=2.0, version=1   <- thay đổi 9 của A bị ghi đè\n\n"
        "SAU KHI SỬA\n"
        "  HTTP/1.1 409 Conflict\n"
        "  {\"conflict\": \"Điểm đã được người khác cập nhật. Vui lòng tải lại trang.\"}\n"
        "  DB: score=9.0, version=2   <- giữ nguyên thay đổi của A",
    )
    label(doc, "Tác động")
    body(doc, "Điểm học vụ có thể sai mà không ai biết; mất nhận xét; ảnh hưởng xếp loại, chứng chỉ và "
              "gây khiếu nại. Mức CAO vì thay đổi dữ liệu học tập của người khác một cách âm thầm.")
    label(doc, "Nguyên nhân trong mã nguồn (bản trước khi sửa)")
    code_block(
        doc,
        "submission = sess.get(Submission, submission_id)\n"
        "old_score = submission.score\n"
        "submission.score = float(new_score)      # không kiểm tra version\n"
        "submission.feedback = feedback\n"
        "sess.flush()                              # last-write-wins",
    )
    label(doc, "Biện pháp khắc phục (bản sau khi sửa)")
    body(doc, "Bổ sung cột version cho submissions và quiz_attempts; biểu mẫu gửi kèm version đã đọc. "
              "Service thực hiện UPDATE có điều kiện version (compare-and-set nguyên tử), kiểm tra số dòng "
              "bị tác động; lệch version trả 409 và ghi nhật ký GRADE_CONFLICT.")
    code_block(
        doc,
        "expected = parse_version(expected_version_raw)\n"
        "...\n"
        "result = sess.execute(\n"
        "    update(Submission)\n"
        "    .where(Submission.id == submission_id,\n"
        "           Submission.version == expected)\n"
        "    .values(score=new_score, version=expected + 1, ...)\n"
        ")\n"
        "if result.rowcount == 0:\n"
        "    audit_record(\"GRADE_CONFLICT\", ...)\n"
        "    raise GradeConflict(current.score, current.version)",
    )
    label(doc, "Kiểm tra lại")
    body(doc, "Lặp lại bước 3–4: A lưu 9 thành công (version 2); B gửi version 1 nhận 409, cơ sở dữ liệu "
              "vẫn là 9. Test tự động test_sua_diem_version_cu_tra_409_va_khong_ghi_de đạt. Đã khắc phục.")

    # ===== V02 =====
    heading(doc, "V02 — Máy chủ trả 500 khi chỉnh điểm quiz", 2)
    badge_line(doc, "V02", "TRUNG BÌNH")
    label(doc, "Vị trí")
    body(doc, "POST /admin/grades/quiz/{attempt_id}/adjust — trang /admin/grades.")
    label(doc, "Mô tả")
    body(doc, "Mã cũ truy cập attempt.quiz.pass_score, nhưng QuizAttempt không khai báo quan hệ quiz. "
              "Mọi lần chỉnh điểm quiz đều ném AttributeError và trả HTTP 500, chức năng không dùng được.")
    label(doc, "Các bước tái hiện")
    numbered(doc, "1. Đăng nhập quản trị, mở /admin/grades.")
    numbered(doc, "2. Ở bảng Quiz Attempts, nhập điểm mới 8 và bấm Lưu.")
    numbered(doc, "3. Máy chủ trả 500 kèm traceback AttributeError.")
    label(doc, "Bằng chứng")
    code_block(
        doc,
        "POST /admin/grades/quiz/4/adjust  score=8\n\n"
        "TRƯỚC: HTTP/1.1 500 Internal Server Error\n"
        "  AttributeError: 'QuizAttempt' object has no attribute 'quiz'\n"
        "  File web/blueprints/admin.py, line 671\n\n"
        "SAU:   HTTP/1.1 302 Found -> /admin/grades\n"
        "  DB: score=8.0, version=2, passed=True",
    )
    label(doc, "Tác động")
    body(doc, "Quản trị viên không thể sửa điểm quiz; trang lộ stack trace khi bật debug, "
              "gây rò rỉ thông tin nội bộ.")
    label(doc, "Nguyên nhân trong mã nguồn (bản trước khi sửa)")
    code_block(
        doc,
        "attempt.score = float(new_score)\n"
        "attempt.passed = attempt.score >= attempt.quiz.pass_score\n"
        "#                            ^^^^^^^^^^^^ không tồn tại",
    )
    label(doc, "Biện pháp khắc phục (bản sau khi sửa)")
    body(doc, "Lấy Quiz theo khoá ngoại quiz_id, kiểm tra tồn tại, rồi tính passed theo pass_score; "
              "đưa toàn bộ logic vào grade_service.update_quiz_grade kèm kiểm tra version và miền điểm.")
    code_block(
        doc,
        "quiz = sess.get(Quiz, attempt.quiz_id)\n"
        "if quiz is None:\n"
        "    raise GradeNotFound(\"Không tìm thấy bài kiểm tra.\")\n"
        "...\n"
        "attempt.passed = new_score >= float(quiz.pass_score)",
    )
    label(doc, "Kiểm tra lại")
    body(doc, "Lưu điểm 8 trả 302; cơ sở dữ liệu score=8, passed=True (pass_score=5), version=2. "
              "Test test_admin_sua_diem_quiz_khong_con_500 đạt. Đã khắc phục.")

    # ===== V03 =====
    heading(doc, "V03 — Thiếu kiểm tra dữ liệu: điểm ngoài miền và xoá nhận xét", 2)
    badge_line(doc, "V03", "TRUNG BÌNH")
    label(doc, "Vị trí")
    body(doc, "POST /admin/grades/assignment/{submission_id}/adjust (và các endpoint chấm điểm bài nộp).")
    label(doc, "Mô tả")
    body(doc, "Điểm được ép kiểu float trực tiếp, không kiểm tra miền [0, max_score] nên chấp nhận 99, -1, NaN. "
              "Đồng thời feedback lấy mặc định chuỗi rỗng và luôn gán, nên yêu cầu không gửi trường feedback "
              "sẽ xoá nhận xét đã có.")
    label(doc, "Các bước tái hiện")
    numbered(doc, "1. Bài nộp có score=8.5, feedback=“Tốt”, mở /admin/grades.")
    numbered(doc, "2. Gửi yêu cầu chỉnh điểm score=99 (không kèm feedback).")
    numbered(doc, "3. Hệ thống lưu score=99 và feedback rỗng; không có lỗi.")
    label(doc, "Bằng chứng")
    code_block(
        doc,
        "POST /admin/grades/assignment/1/adjust\n"
        "score=99\n\n"
        "TRƯỚC: HTTP/1.1 302\n"
        "  DB: score=99.0, feedback=''      <- sai miền, mất nhận xét\n\n"
        "SAU:   HTTP/1.1 302 (flash lỗi), DB không đổi\n"
        "  “Điểm phải nằm trong khoảng 0–10.0.”\n\n"
        "Với score=7 (không gửi feedback):\n"
        "  TRƯỚC: feedback=''\n"
        "  SAU:   feedback='Tốt'  <- giữ nguyên nhận xét",
    )
    label(doc, "Tác động")
    body(doc, "Điểm vượt thang 10 hoặc âm làm sai bảng điểm, xếp hạng, điều kiện cấp chứng chỉ; "
              "mất nhận xét của giảng viên.")
    label(doc, "Nguyên nhân trong mã nguồn (bản trước khi sửa)")
    code_block(
        doc,
        "new_score = request.form.get(\"score\")\n"
        "feedback = request.form.get(\"feedback\", \"\")   # thiếu -> \"\"\n"
        "...\n"
        "submission.score = float(new_score)              # không kiểm tra miền\n"
        "submission.feedback = feedback                   # luôn ghi đè",
    )
    label(doc, "Biện pháp khắc phục (bản sau khi sửa)")
    body(doc, "parse_score chuẩn hoá dấu phẩy thập phân, từ chối NaN/Infinity và giá trị ngoài [0, max_score]. "
              "Chỉ cập nhật feedback khi client thực sự gửi trường này (khác None).")
    code_block(
        doc,
        "value = float(str(raw).strip().replace(\",\", \".\"))\n"
        "if not math.isfinite(value):\n"
        "    raise GradeValidationError(\"Điểm phải là số hữu hạn.\")\n"
        "if value < 0 or value > float(max_score):\n"
        "    raise GradeValidationError(f\"Điểm phải nằm trong khoảng 0–{max_score}.\")\n"
        "...\n"
        "if feedback_raw is not None:          # không gửi thì giữ nguyên\n"
        "    submission.feedback = str(feedback_raw).strip() or None",
    )
    label(doc, "Kiểm tra lại")
    body(doc, "Bốn giá trị 99, -1, abc, nan đều bị từ chối, cơ sở dữ liệu không đổi; "
              "chỉnh điểm không kèm feedback giữ nguyên “Tốt”. Test test_diem_ngoai_mien_bi_tu_choi và "
              "test_sua_diem_dung_version_va_giu_nhan_xet đạt. Đã khắc phục.")

    # ---------------- 5. Danh mục kiểm thử ----------------
    heading(doc, "5. Danh mục kiểm thử", 1)
    body(doc, "Ký hiệu: ⊠ đã kiểm thử, không phát hiện lỗi; LỖI phát hiện lỗi (kèm mã); N/A không áp dụng.",
         italic=True, size=10)
    add_table(
        doc,
        ["Mã", "Nội dung kiểm thử", "Công cụ", "Kết quả"],
        [
            ["G01", "Sửa điểm với version hiện tại thành công, version tăng 1", "pytest", "⊠"],
            ["G02", "Sửa điểm với version cũ trả 409, dữ liệu không đổi", "pytest", "LỖI (V01) → ⊠"],
            ["G03", "Yêu cầu thiếu version bị từ chối", "pytest", "⊠"],
            ["G04", "Chỉnh điểm quiz không còn 500, passed tính đúng", "pytest", "LỖI (V02) → ⊠"],
            ["G05", "Chỉnh điểm quiz với version cũ trả 409", "pytest", "LỖI (V01) → ⊠"],
            ["G06", "Điểm ngoài miền (99, -1) bị từ chối", "pytest, script", "LỖI (V03) → ⊠"],
            ["G07", "Điểm không phải số hoặc NaN bị từ chối", "pytest, script", "LỖI (V03) → ⊠"],
            ["G08", "Không gửi feedback thì nhận xét cũ được giữ", "pytest, script", "LỖI (V03) → ⊠"],
            ["G09", "Bảng điểm admin hiển thị version trên từng biểu mẫu", "pytest", "⊠"],
            ["G10", "Giảng viên không dạy khoá không chấm được điểm", "pytest", "⊠"],
            ["G11", "Sinh viên gọi endpoint chấm/sửa điểm bị chặn 403", "pytest", "⊠"],
            ["G12", "Hai người sửa đồng thời: chỉ một thay đổi được ghi", "script evidence", "LỖI (V01) → ⊠"],
        ],
        [1.1, 9.0, 3.9, 3.0],
        font_size=9,
    )
    body(doc, "Tổng: 133 test đạt (126 test cũ + 7 test mới cho sửa điểm).", italic=True, size=10)

    # ---------------- 6. Đánh giá ----------------
    heading(doc, "6. Đánh giá và bài học", 1)
    body(doc, "Optimistic Locking xử lý đúng lớp lỗi mất cập nhật mà các bài kiểm thử tuần tự không phát hiện được; "
              "version phải đi kèm biểu mẫu và được kiểm tra ở tầng service, không chỉ ở giao diện. "
              "Việc tách grade_service giúp mọi entry point (giảng viên, quản trị, quiz, bài nộp) dùng chung một "
              "quy tắc kiểm tra và ghi nhật ký. Bài học: luôn kiểm tra dữ liệu ở server, không tin giá trị từ form; "
              "với dữ liệu có tranh chấp, cần thiết kế cơ chế phiên bản ngay từ đầu thay vì bổ sung sau.")

    # ---------------- Phụ lục ----------------
    doc.add_page_break()
    heading(doc, "Phụ lục A — Mã nguồn bản trước khi sửa", 1)
    body(doc, "Tệp docs/patterns/sua_diem_truoc_khi_sua.py (trích nguyên trạng logic cũ, chỉ dùng để minh hoạ).",
         italic=True, size=10)
    code_block(doc, BEFORE_CODE.read_text(encoding="utf-8"), size=8)

    doc.add_page_break()
    heading(doc, "Phụ lục B — Bằng chứng before/after", 1)
    body(doc, "Kết quả chạy tools/pattern_evidence.py trên cơ sở dữ liệu tạm (SQLite in-memory).",
         italic=True, size=10)
    code_block(doc, EVIDENCE.read_text(encoding="utf-8"), size=7.5)

    doc.add_page_break()
    heading(doc, "Phụ lục C — Danh sách kiểm thử tự động", 1)
    body(doc, "Tệp tests/test_grade_optimistic.py gồm 7 test:", size=10.5)
    for item in [
        "test_sua_diem_dung_version_va_giu_nhan_xet",
        "test_sua_diem_version_cu_tra_409_va_khong_ghi_de",
        "test_thieu_version_bi_tu_choi",
        "test_diem_ngoai_mien_bi_tu_choi",
        "test_admin_sua_diem_quiz_khong_con_500",
        "test_admin_sua_diem_quiz_version_cu_tra_409",
        "test_bang_diem_hien_thi_version",
    ]:
        bullet(doc, item, size=10.5)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(OUT)
    print(f"saved: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
