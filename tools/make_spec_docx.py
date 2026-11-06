"""Sinh file đặc tả tính năng miniLMS (.docx) theo mẫu dac_ta_tinh_nang_lms.pdf.

Chạy bằng Python có python-docx:
  <bundled-python> tools\\make_spec_docx.py
"""

from __future__ import annotations

import json
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "Dac_ta_tinh_nang_miniLMS.docx"
ROUTES = ROOT / "tools" / "routes.json"

NAVY = RGBColor(0x1F, 0x3A, 0x5F)
GRAY = RGBColor(0x44, 0x44, 0x44)
HEAD_FILL = "DCE6F1"
ALT_FILL = "F5F8FC"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def set_run_font(run, size: float | None = None, bold: bool | None = None,
                 italic: bool | None = None, color: RGBColor | None = None) -> None:
    run.font.name = "Times New Roman"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "Times New Roman")
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.bold = bold
    if italic is not None:
        run.italic = italic
    if color is not None:
        run.font.color.rgb = color


def set_cell_bg(cell, hex_color: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_color)
    tc_pr.append(shd)


def set_cell_margins(table, top=40, bottom=40, left=70, right=70) -> None:
    tbl_pr = table._tbl.tblPr
    mar = OxmlElement("w:tblCellMar")
    for side, val in (("top", top), ("left", left), ("bottom", bottom), ("right", right)):
        node = OxmlElement(f"w:{side}")
        node.set(qn("w:w"), str(val))
        node.set(qn("w:type"), "dxa")
        mar.append(node)
    tbl_pr.append(mar)


def add_table(
    doc: Document,
    headers: list[str],
    rows: list[list[str]],
    widths_cm: list[float],
    *,
    font_size: float = 10,
    header_size: float = 10,
) -> None:
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    set_cell_margins(table)

    # Bắt buộc layout cố định để LibreOffice/Word tôn trọng độ rộng cột.
    tbl_pr = table._tbl.tblPr
    layout = OxmlElement("w:tblLayout")
    layout.set(qn("w:type"), "fixed")
    tbl_pr.append(layout)

    hdr = table.rows[0].cells
    for idx, text in enumerate(headers):
        hdr[idx].text = ""
        p = hdr[idx].paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run(text)
        set_run_font(run, size=header_size, bold=True, color=NAVY)
        set_cell_bg(hdr[idx], HEAD_FILL)

    for r_idx, row in enumerate(rows):
        cells = table.add_row().cells
        for c_idx, text in enumerate(row):
            cells[c_idx].text = ""
            p = cells[c_idx].paragraphs[0]
            p.paragraph_format.space_after = Pt(0)
            run = p.add_run(str(text))
            set_run_font(run, size=font_size)
            if c_idx == 0:
                run.bold = True
            if r_idx % 2 == 1:
                set_cell_bg(cells[c_idx], ALT_FILL)

    for row in table.rows:
        for idx, width in enumerate(widths_cm):
            row.cells[idx].width = Cm(width)
    # gridCol quyết định độ rộng thực tế khi render.
    for idx, width in enumerate(widths_cm):
        table.columns[idx].width = Cm(width)
    return table


def add_page_number(paragraph) -> None:
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = paragraph.add_run()
    fld_begin = OxmlElement("w:fldChar")
    fld_begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = "PAGE"
    fld_end = OxmlElement("w:fldChar")
    fld_end.set(qn("w:fldCharType"), "end")
    run._r.append(fld_begin)
    run._r.append(instr)
    run._r.append(fld_end)
    set_run_font(run, size=9, color=GRAY)


def heading(doc: Document, text: str, level: int = 1) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(14 if level == 1 else 10)
    p.paragraph_format.space_after = Pt(6)
    p.paragraph_format.keep_with_next = True
    run = p.add_run(text)
    set_run_font(run, size=14 if level == 1 else 12, bold=True, color=NAVY)
    # outline level để Word hiểu là heading
    p_pr = p._p.get_or_add_pPr()
    outline = OxmlElement("w:outlineLvl")
    outline.set(qn("w:val"), str(level - 1))
    p_pr.append(outline)


def body(doc: Document, text: str, *, italic: bool = False, size: float = 11) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(6)
    p.paragraph_format.line_spacing = 1.2
    run = p.add_run(text)
    set_run_font(run, size=size, italic=italic)


def bullet(doc: Document, text: str, size: float = 11) -> None:
    p = doc.add_paragraph(style="List Bullet")
    p.paragraph_format.space_after = Pt(3)
    run = p.add_run(text)
    set_run_font(run, size=size)


# ---------------------------------------------------------------------------
# Nội dung
# ---------------------------------------------------------------------------

COMPONENTS = [
    ("CLIENT", "Tầng giao diện chạy trên trình duyệt (Jinja2 + HTML/CSS), nhận dữ liệu đầu vào và hiển thị kết quả."),
    ("SERVER", "Tầng xử lý nghiệp vụ Flask: blueprint theo vai trò, kiểm soát truy cập, REST API."),
    ("DATABASE", "PostgreSQL 18 lưu người dùng, khoá học, bài nộp, điểm, thông báo, nhật ký."),
    ("LƯU TRỮ TỆP", "Thư mục instance/uploads: ảnh đại diện, tài liệu bài giảng, tệp bài nộp."),
    ("EMAIL", "Dịch vụ gửi thư: khôi phục mật khẩu và thông báo lớp. Chế độ dev ghi ra instance/mail/*.eml."),
    ("SESSION/TOKEN", "JWT ký HS256 trong cookie httpOnly, kèm bản ghi AuthSession để thu hồi phiên."),
]

ROLES_LINE = "Vai trò người dùng: SV – Sinh viên; GV – Giảng viên; QT – Quản trị viên."

SECTIONS: list[tuple[str, list[tuple[str, str, str, str]]]] = [
    (
        "1. Quản lý tài khoản và xác thực",
        [
            ("Đăng ký tài khoản", "Tạo tài khoản bằng email và mật khẩu; mật khẩu băm bcrypt (cost 10) trước khi lưu; chặn trùng email.", "SV", "CLIENT, SERVER, DATABASE"),
            ("Đăng nhập", "Xác thực thông tin, cấp JWT và tạo phiên AuthSession; khoá tạm 15 phút sau 5 lần sai.", "Tất cả", "CLIENT, SERVER, DATABASE, SESSION/TOKEN"),
            ("Đăng xuất", "Thu hồi phiên phía server (revoked_at) và xoá cookie.", "Tất cả", "SERVER, SESSION/TOKEN"),
            ("Khôi phục mật khẩu", "Gửi email chứa liên kết một lần, hiệu lực 30 phút; token lưu dạng SHA-256, dùng xong vô hiệu.", "Tất cả", "SERVER, DATABASE, EMAIL"),
            ("Đổi mật khẩu", "Yêu cầu xác nhận mật khẩu hiện tại; thu hồi mọi phiên cũ sau khi đổi.", "Tất cả", "CLIENT, SERVER, DATABASE"),
            ("Nhật ký đăng nhập", "Ghi LOGIN / LOGIN_FAILED / LOGOUT vào bảng audit_events.", "QT (xem)", "SERVER, DATABASE"),
        ],
    ),
    (
        "2. Hồ sơ người dùng",
        [
            ("Cập nhật hồ sơ", "Xem và chỉnh sửa họ tên, giới thiệu của chính mình.", "Tất cả", "CLIENT, SERVER, DATABASE"),
            ("Ảnh đại diện", "Tải lên PNG/JPG/WEBP ≤ 2MB; tệp lưu ngoài static và chỉ phục vụ qua route kiểm tra đăng nhập.", "Tất cả", "CLIENT, SERVER, LƯU TRỮ TỆP"),
            ("Xem hồ sơ thành viên", "Hiển thị thông tin công khai, khoá đang dạy/học và khoá học chung.", "Tất cả", "CLIENT, SERVER, DATABASE"),
            ("Cài đặt nhận email", "Bật/tắt nhận thông báo qua email cho tài khoản.", "SV", "CLIENT, SERVER, DATABASE"),
        ],
    ),
    (
        "3. Quản lý khoá học",
        [
            ("Tra cứu khoá học", "Liệt kê khoá đã xuất bản; tìm theo tên/mô tả, lọc theo danh mục, tag và giảng viên.", "Tất cả", "CLIENT, SERVER, DATABASE"),
            ("Xem chi tiết khoá", "Mô tả, chương trình, giảng viên, bài kiểm tra, bài tập và số học viên.", "Tất cả", "CLIENT, SERVER, DATABASE"),
            ("Học thử", "Bài có cờ is_free_preview cho phép khách xem trước nội dung.", "Khách", "CLIENT, SERVER, DATABASE"),
            ("Tạo khoá học", "GV khởi tạo khoá thuộc quyền mình, kèm mô tả, danh mục, giá, trạng thái.", "GV", "CLIENT, SERVER, DATABASE"),
            ("Cập nhật khoá học", "GV chỉ sửa khoá do mình phụ trách (kiểm tra ownership).", "GV", "CLIENT, SERVER, DATABASE"),
            ("Quản lý chương trình", "Thêm/xoá chương và bài học trong khoá.", "GV", "CLIENT, SERVER, DATABASE"),
            ("Tài liệu bài giảng", "GV tải tài liệu lên; SV phải ghi danh mới tải xuống được.", "GV, SV", "CLIENT, SERVER, LƯU TRỮ TỆP"),
            ("Ghi danh bằng mã", "SV nhập mã ghi danh duy nhất của khoá để vào lớp.", "SV", "CLIENT, SERVER, DATABASE"),
            ("Quản lý danh sách lớp", "GV thêm SV theo email hoặc xoá SV khỏi khoá.", "GV", "CLIENT, SERVER, DATABASE"),
            ("Báo cáo khoá học", "Tỷ lệ hoàn thành, điểm trung bình; xuất CSV.", "GV", "SERVER, DATABASE"),
        ],
    ),
    (
        "4. Bài tập và đánh giá",
        [
            ("Tạo bài tập", "GV tạo bài tập kèm mô tả, điểm tối đa và thời hạn nộp.", "GV", "CLIENT, SERVER, DATABASE"),
            ("Nộp bài", "SV nộp văn bản và/hoặc tệp ≤ 20MB; hệ thống chặn nộp sau hạn.", "SV", "CLIENT, SERVER, DATABASE, LƯU TRỮ TỆP"),
            ("Truy xuất bài nộp", "SV chỉ xem bài của mình; GV xem bài của lớp mình phụ trách.", "SV, GV", "SERVER, DATABASE, LƯU TRỮ TỆP"),
            ("Chấm điểm và nhận xét", "GV ghi điểm trong [0, max_score] kèm nhận xét; lưu thời điểm chấm.", "GV", "CLIENT, SERVER, DATABASE"),
            ("Tra cứu điểm", "SV chỉ xem kết quả học tập của chính mình.", "SV", "CLIENT, SERVER, DATABASE"),
            ("Chỉnh sửa điểm", "QT chỉnh điểm quiz/bài nộp toàn hệ thống; mọi thay đổi ghi nhật ký.", "QT", "CLIENT, SERVER, DATABASE"),
        ],
    ),
    (
        "5. Bài kiểm tra trắc nghiệm",
        [
            ("Tạo bài kiểm tra", "GV thiết lập thời lượng, điểm đạt, số lần làm tối đa, có hiện đáp án hay không.", "GV", "CLIENT, SERVER, DATABASE"),
            ("Ngân hàng câu hỏi", "Thêm/xoá câu hỏi trắc nghiệm, gán vào bài kiểm tra.", "GV", "CLIENT, SERVER, DATABASE"),
            ("Làm bài kiểm tra", "SV làm bài trong thời lượng quy định, bị giới hạn số lần.", "SV", "CLIENT, SERVER, DATABASE, SESSION/TOKEN"),
            ("Cưỡng chế thời gian", "Server tính hạn từ started_at; quá hạn đánh dấu EXPIRED, không chấm điểm.", "SV", "SERVER, DATABASE"),
            ("Chấm điểm tự động", "Đối chiếu đáp án và tính điểm hoàn toàn ở phía server.", "Hệ thống", "SERVER, DATABASE"),
            ("Xem kết quả", "SV xem điểm; đáp án chỉ hiện khi GV cho phép.", "SV, GV", "CLIENT, SERVER, DATABASE"),
        ],
    ),
    (
        "6. Trao đổi và thông báo",
        [
            ("Diễn đàn khoá học", "Đăng chủ đề và bình luận trong khoá đã ghi danh.", "SV, GV", "CLIENT, SERVER, DATABASE"),
            ("Tự sửa/xoá nội dung", "Người dùng chỉ được sửa hoặc xoá chủ đề/bình luận của chính mình.", "SV, GV", "CLIENT, SERVER, DATABASE"),
            ("Kiểm duyệt diễn đàn", "GV/QT ghim, khoá hoặc xoá chủ đề vi phạm.", "GV, QT", "CLIENT, SERVER, DATABASE"),
            ("Thông báo lớp học", "GV phát thông báo tới toàn bộ SV trong khoá; lưu DB và gửi email.", "GV", "CLIENT, SERVER, DATABASE, EMAIL"),
            ("Thông báo hệ thống", "QT gửi thông báo tới tất cả hoặc theo nhóm vai trò.", "QT", "CLIENT, SERVER, DATABASE, EMAIL"),
            ("Xem thông báo", "SV xem danh sách và đánh dấu đã đọc.", "SV", "CLIENT, SERVER, DATABASE"),
            ("Tin nhắn trực tiếp", "SV nhắn tin với GV của khoá; GV phản hồi trong hộp thư.", "SV, GV", "CLIENT, SERVER, DATABASE"),
            ("Live session", "GV tạo/lên lịch/xoá buổi học trực tuyến; QT quản lý toàn bộ.", "GV, QT", "CLIENT, SERVER, DATABASE"),
        ],
    ),
    (
        "7. Quản trị hệ thống",
        [
            ("Quản lý người dùng", "Tra cứu, lọc, khoá/mở tài khoản và đổi vai trò.", "QT", "CLIENT, SERVER, DATABASE"),
            ("Quản lý khoá học", "Xem toàn bộ khoá, đổi trạng thái, xoá, chuyển GV phụ trách.", "QT", "CLIENT, SERVER, DATABASE"),
            ("Quản lý danh mục", "Tạo và xoá danh mục khoá học.", "QT", "CLIENT, SERVER, DATABASE"),
            ("Quản lý bài kiểm tra/bài tập", "Xem và xoá bài kiểm tra, bài tập toàn hệ thống.", "QT", "CLIENT, SERVER, DATABASE"),
            ("Bảng điểm toàn hệ thống", "Tổng hợp điểm quiz và bài nộp; chỉnh điểm trực tiếp.", "QT", "CLIENT, SERVER, DATABASE"),
            ("Quản lý chứng chỉ", "Cấp và thu hồi chứng chỉ cho từng SV.", "QT", "CLIENT, SERVER, DATABASE"),
            ("Quản lý huy hiệu", "Tạo/xoá huy hiệu và điều kiện nhận.", "QT", "CLIENT, SERVER, DATABASE"),
            ("Báo cáo", "Báo cáo tổng hợp, theo khoá học và theo người dùng.", "QT", "CLIENT, SERVER, DATABASE"),
            ("Nhật ký hoạt động", "Ghi nhận đăng nhập, đổi điểm, thao tác quản trị; lọc theo hành động/người thực hiện.", "QT", "SERVER, DATABASE"),
            ("Cài đặt hệ thống", "Cấu hình chung, phân quyền và thanh toán.", "QT", "CLIENT, SERVER, DATABASE"),
        ],
    ),
    (
        "8. Giao diện lập trình ứng dụng (REST API)",
        [
            ("Thông tin người dùng", "GET /api/me trả hồ sơ người đang đăng nhập.", "Tất cả", "SERVER, SESSION/TOKEN"),
            ("Danh sách khoá học", "GET /api/courses hỗ trợ tìm kiếm và lọc theo danh mục/giảng viên.", "Tất cả", "SERVER, DATABASE"),
            ("Chi tiết khoá học", "GET /api/courses/{id} trả chương, bài, quiz và bài tập.", "Tất cả", "SERVER, DATABASE"),
            ("Điểm theo khoá", "GET /api/courses/{id}/grades; SV chỉ thấy điểm của mình.", "SV, GV, QT", "SERVER, DATABASE, SESSION/TOKEN"),
            ("Chi tiết bài tập", "GET /api/assignments/{id} cho SV đã ghi danh hoặc GV/QT.", "SV, GV, QT", "SERVER, DATABASE"),
            ("Tài liệu API", "GET /api/openapi.json (OpenAPI 3.0) và /api/docs (Swagger UI).", "Tất cả", "SERVER"),
        ],
    ),
    (
        "9. Tính năng mở rộng ngoài đặc tả gốc",
        [
            ("Chứng chỉ", "SV xem và tải chứng chỉ đã đạt; GV/QT cấp hoặc thu hồi.", "SV, GV, QT", "CLIENT, SERVER, DATABASE"),
            ("Huy hiệu", "Gán huy hiệu theo điều kiện hoạt động học tập.", "QT", "SERVER, DATABASE"),
            ("Bảng xếp hạng", "Xếp hạng SV theo điểm/hoạt động khi khoá cho phép công khai.", "SV", "CLIENT, SERVER, DATABASE"),
            ("Cài đặt thanh toán", "Cấu hình cổng thanh toán và hoa hồng giảng viên.", "QT", "CLIENT, SERVER, DATABASE"),
        ],
    ),
]

TECH_NOTES = [
    "Auth middleware: mọi route private kiểm tra JWT trong cookie httpOnly, đối chiếu AuthSession còn hiệu lực; thiếu quyền trả 403, chưa đăng nhập chuyển /login.",
    "Role enum: ADMIN | INSTRUCTOR | STUDENT | GUEST (chuẩn hoá từ dữ liệu seed).",
    "Course ownership: GV chỉ CRUD khoá có instructor_id trùng id của mình; QT bỏ qua kiểm tra sở hữu.",
    "Enrollment check: SV chỉ vào /my-courses/<id>/learn khi có bản ghi enrollment ACTIVE.",
    "Preview lesson: bài có is_free_preview cho phép GUEST xem nội dung.",
    "Mật khẩu: băm bcrypt cost ≥ 10; không lưu plaintext; đổi mật khẩu thu hồi phiên cũ.",
    "Tệp tải lên: giới hạn loại và dung lượng (ảnh 2MB, tài liệu/bài nộp 20MB); không phục vụ qua static.",
    "Email: chế độ dev ghi .eml vào instance/mail; cấu hình SMTP_HOST để gửi thật.",
    "Nhật ký: mọi thay đổi điểm và thao tác quản trị ghi vào audit_events.",
    "Cơ sở dữ liệu: PostgreSQL, schema tạo tự động; migration idempotent ở tools/migrate.py.",
]

# ---------------------------------------------------------------------------
# Phụ lục endpoint
# ---------------------------------------------------------------------------

EP_LABEL: dict[str, str] = {
    # admin
    "admin.dashboard": "Dashboard quản trị",
    "admin.users": "Danh sách & lọc người dùng",
    "admin.user_detail": "Chi tiết người dùng",
    "admin.user_lock": "Khoá tài khoản",
    "admin.user_unlock": "Mở khoá tài khoản",
    "admin.user_change_role": "Đổi vai trò",
    "admin.courses": "Danh sách toàn bộ khoá học",
    "admin.course_detail": "Chi tiết khoá học (admin)",
    "admin.course_status": "Đổi trạng thái khoá",
    "admin.course_delete": "Xoá khoá học",
    "admin.course_reassign": "Chuyển giảng viên phụ trách",
    "admin.categories": "Quản lý danh mục",
    "admin.category_create": "Tạo danh mục",
    "admin.category_delete": "Xoá danh mục",
    "admin.quizzes": "Bài kiểm tra toàn hệ thống",
    "admin.quiz_delete": "Xoá bài kiểm tra",
    "admin.assignments": "Bài tập toàn hệ thống",
    "admin.assignment_delete": "Xoá bài tập",
    "admin.grades": "Bảng điểm toàn hệ thống",
    "admin.grade_quiz_adjust": "Chỉnh điểm quiz",
    "admin.grade_assignment_adjust": "Chỉnh điểm bài tập",
    "admin.certificates": "Quản lý chứng chỉ",
    "admin.certificate_issue": "Cấp chứng chỉ",
    "admin.certificate_revoke": "Thu hồi chứng chỉ",
    "admin.badges": "Quản lý huy hiệu",
    "admin.badge_create": "Tạo huy hiệu",
    "admin.badge_delete": "Xoá huy hiệu",
    "admin.reports": "Báo cáo tổng hợp",
    "admin.reports_courses": "Báo cáo theo khoá học",
    "admin.reports_users": "Báo cáo theo người dùng",
    "admin.forum": "Kiểm duyệt diễn đàn",
    "admin.forum_moderate": "Ghim/khoá/xoá chủ đề",
    "admin.notifications": "Gửi thông báo hệ thống",
    "admin.notification_send": "Gửi thông báo (form)",
    "admin.live": "Quản lý live session",
    "admin.live_delete": "Xoá live session",
    "admin.audit": "Nhật ký hoạt động",
    "admin.settings": "Cài đặt hệ thống",
    "admin.settings_update": "Lưu cài đặt hệ thống",
    "admin.settings_roles": "Cấu hình phân quyền",
    "admin.settings_roles_save": "Lưu phân quyền",
    "admin.settings_payments": "Cài đặt thanh toán",
    "admin.settings_payments_save": "Lưu thanh toán",
    # api
    "api.me": "Thông tin người dùng hiện tại",
    "api.list_courses": "Danh sách khoá công khai",
    "api.get_course": "Chi tiết khoá học",
    "api.get_grades": "Điểm theo khoá học",
    "api.get_assignment": "Chi tiết bài tập",
    "api.openapi": "Đặc tả OpenAPI",
    "api.docs": "Swagger UI",
    # quiz
    "quiz.intro": "Giới thiệu bài kiểm tra",
    "quiz.start": "Bắt đầu lượt làm bài",
    "quiz.take": "Làm bài (đếm ngược)",
    "quiz.submit": "Nộp bài kiểm tra",
    "quiz.result": "Xem kết quả bài kiểm tra",
    "quiz.assignment_detail": "Chi tiết bài tập",
    "quiz.assignment_submit": "Nộp bài tập (văn bản + tệp)",
    "quiz.assignment_grade": "Chấm điểm bài nộp",
    # files
    "files.upload_avatar": "Tải ảnh đại diện",
    "files.serve_avatar": "Hiển thị ảnh đại diện",
    "files.upload_attachment": "Tải tài liệu bài giảng",
    "files.delete_attachment": "Xoá tài liệu bài giảng",
    "files.download_attachment": "Tải tài liệu (kiểm quyền)",
    "files.download_submission": "Tải tệp bài nộp",
    # main
    "main.home": "Trang chủ",
    "main.courses": "Tra cứu khoá học + bộ lọc",
    "main.course_detail": "Chi tiết khoá / đăng ký",
    "main.course_preview": "Học thử bài free preview",
    "main.dashboard": "Dashboard theo vai trò",
    "main.instructors": "Danh sách giảng viên",
    "main.member_profile": "Hồ sơ thành viên",
    # auth
    "auth.login": "Đăng nhập",
    "auth.logout": "Đăng xuất",
    "auth.register": "Đăng ký tài khoản",
    "auth.forgot_password": "Yêu cầu khôi phục mật khẩu",
    "auth.reset_password": "Đặt mật khẩu mới từ token",
    # student
    "student.my_courses": "Khoá đã ghi danh + tiến độ",
    "student.enroll_by_code": "Ghi danh bằng mã",
    "student.learn": "Giao diện học khoá",
    "student.learn_lesson": "Nội dung bài học + tài liệu",
    "student.complete_lesson": "Đánh dấu hoàn thành bài",
    "student.grades": "Bảng điểm cá nhân",
    "student.progress": "Tiến độ học tập",
    "student.certificates": "Danh sách chứng chỉ",
    "student.certificate_detail": "Chi tiết chứng chỉ",
    "student.leaderboard": "Bảng xếp hạng",
    "student.forum_index": "Diễn đàn các khoá",
    "student.forum_course": "Diễn đàn một khoá",
    "student.forum_topic": "Chi tiết chủ đề",
    "student.forum_topic_create": "Tạo chủ đề",
    "student.forum_reply": "Trả lời chủ đề",
    "student.forum_topic_edit": "Sửa chủ đề của mình",
    "student.forum_topic_delete": "Xoá chủ đề của mình",
    "student.forum_post_edit": "Sửa bình luận của mình",
    "student.forum_post_delete": "Xoá bình luận của mình",
    "student.messages_index": "Hộp thư",
    "student.messages_conversation": "Hội thoại với giảng viên",
    "student.messages_send": "Gửi tin nhắn",
    "student.notifications": "Danh sách thông báo",
    "student.notification_read": "Đánh dấu đã đọc",
    "student.profile": "Hồ sơ cá nhân",
    "student.profile_edit": "Sửa hồ sơ",
    "student.profile_password": "Đổi mật khẩu",
    "student.settings": "Cài đặt nhận email",
    # instructor
    "instructor.courses": "Khoá học phụ trách",
    "instructor.course_new": "Tạo khoá học",
    "instructor.course_edit": "Sửa khoá học",
    "instructor.course_curriculum": "Chương trình khoá",
    "instructor.chapter_create": "Thêm chương",
    "instructor.lesson_create": "Thêm bài học",
    "instructor.lesson_delete": "Xoá bài học",
    "instructor.course_students_view": "Danh sách SV trong khoá",
    "instructor.student_add": "Thêm SV theo email",
    "instructor.student_remove": "Xoá SV khỏi khoá",
    "instructor.course_reports": "Báo cáo khoá học",
    "instructor.course_reports_export": "Xuất CSV báo cáo khoá",
    "instructor.quizzes": "Bài kiểm tra của giảng viên",
    "instructor.quiz_new": "Tạo bài kiểm tra",
    "instructor.quiz_questions": "Quản lý câu hỏi",
    "instructor.question_delete": "Xoá câu hỏi",
    "instructor.assignments": "Bài tập của giảng viên",
    "instructor.assignment_create": "Tạo bài tập",
    "instructor.grades": "Bảng điểm lớp",
    "instructor.certificates": "Chứng chỉ của khoá",
    "instructor.certificate_issue": "Cấp chứng chỉ",
    "instructor.certificate_revoke": "Thu hồi chứng chỉ",
    "instructor.forum": "Diễn đàn khoá",
    "instructor.forum_moderate": "Kiểm duyệt chủ đề",
    "instructor.live": "Live session",
    "instructor.live_create": "Tạo live session",
    "instructor.live_delete": "Xoá live session",
    "instructor.messages_index": "Hộp thư giảng viên",
    "instructor.messages_conversation": "Hội thoại với sinh viên",
    "instructor.messages_send": "Gửi tin nhắn",
    "instructor.notifications": "Thông báo lớp học",
    "instructor.notification_send": "Gửi thông báo lớp",
    "instructor.profile": "Hồ sơ giảng viên",
    "instructor.profile_edit": "Sửa hồ sơ giảng viên",
    "instructor.profile_password": "Đổi mật khẩu",
    "instructor.reports_export": "Xuất báo cáo tổng hợp",
}


def ep_roles(rule: str, endpoint: str, methods: list[str]) -> str:
    special = {
        "main.home": "Tất cả",
        "main.courses": "Tất cả",
        "main.instructors": "Tất cả",
        "main.course_detail": "Tất cả (POST: SV)",
        "main.course_preview": "Tất cả",
        "main.member_profile": "Đã đăng nhập",
        "main.dashboard": "SV, GV, QT",
        "auth.login": "Khách",
        "auth.register": "Khách",
        "auth.forgot_password": "Khách",
        "auth.reset_password": "Khách",
        "auth.logout": "Đã đăng nhập",
        "files.upload_avatar": "SV, GV, QT",
        "files.serve_avatar": "Đã đăng nhập",
        "files.upload_attachment": "GV, QT",
        "files.delete_attachment": "GV, QT",
        "files.download_attachment": "SV (ghi danh), GV, QT",
        "files.download_submission": "SV (chủ bài), GV, QT",
        "quiz.result": "SV, GV, QT",
        "quiz.assignment_detail": "SV, GV, QT",
        "quiz.assignment_grade": "GV, QT",
        "api.me": "Đã đăng nhập",
        "api.list_courses": "Tất cả",
        "api.get_course": "Tất cả",
        "api.get_grades": "SV, GV, QT",
        "api.get_assignment": "SV, GV, QT",
        "api.openapi": "Tất cả",
        "api.docs": "Tất cả",
    }
    if endpoint in special:
        return special[endpoint]
    if endpoint.startswith("admin."):
        return "QT"
    if endpoint.startswith("instructor."):
        return "GV"
    if endpoint.startswith("student."):
        return "SV"
    if endpoint.startswith("quiz."):
        return "SV"
    if endpoint.startswith("files."):
        return "Đã đăng nhập"
    return "Tất cả"


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


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
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), "Times New Roman")

    # header / footer
    header_p = section.header.paragraphs[0]
    header_p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    hr = header_p.add_run("Đặc tả tính năng — miniLMS")
    set_run_font(hr, size=9, italic=True, color=GRAY)
    footer_p = section.footer.paragraphs[0]
    add_page_number(footer_p)

    # ---- Tiêu đề ----
    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title.paragraph_format.space_before = Pt(24)
    title.paragraph_format.space_after = Pt(4)
    r = title.add_run("ĐẶC TẢ TÍNH NĂNG")
    set_run_font(r, size=22, bold=True, color=NAVY)

    subtitle = doc.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    subtitle.paragraph_format.space_after = Pt(2)
    r = subtitle.add_run("Hệ thống quản lý học tập (Learning Management System – LMS)")
    set_run_font(r, size=14, bold=True, color=NAVY)

    meta = doc.add_paragraph()
    meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
    meta.paragraph_format.space_after = Pt(18)
    r = meta.add_run("miniLMS · Phiên bản 1.0 · Flask + SQLAlchemy + PostgreSQL")
    set_run_font(r, size=10.5, italic=True, color=GRAY)

    body(
        doc,
        "Tài liệu mô tả các tính năng đề xuất của website miniLMS, đối chiếu với "
        "đặc tả hệ thống LMS và mã nguồn hiện hành. Mỗi tính năng nêu rõ mô tả, "
        "vai trò được phép sử dụng và các thành phần hệ thống liên quan. Phụ lục A "
        "liệt kê toàn bộ endpoint tương ứng.",
    )

    # ---- Các thành phần hệ thống ----
    heading(doc, "Các thành phần hệ thống", 1)
    add_table(
        doc,
        ["Thành phần", "Trách nhiệm"],
        [[name, desc] for name, desc in COMPONENTS],
        [3.4, 14.0],
        font_size=10,
    )

    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(10)
    p.paragraph_format.space_after = Pt(4)
    r = p.add_run(ROLES_LINE)
    set_run_font(r, size=11, bold=True)

    # ---- Các mục tính năng ----
    for title_text, rows in SECTIONS:
        heading(doc, title_text, 1)
        add_table(
            doc,
            ["Tính năng", "Mô tả", "Vai trò", "Thành phần liên quan"],
            [list(row) for row in rows],
            [3.6, 7.6, 2.2, 4.0],
            font_size=9.5,
            header_size=9.5,
        )
        doc.add_paragraph().paragraph_format.space_after = Pt(2)

    # ---- Ghi chú kỹ thuật ----
    heading(doc, "Ghi chú kỹ thuật", 1)
    for idx, note in enumerate(TECH_NOTES, start=1):
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(3)
        p.paragraph_format.left_indent = Cm(0.6)
        p.paragraph_format.first_line_indent = Cm(-0.6)
        r = p.add_run(f"{idx}. ")
        set_run_font(r, size=11, bold=True)
        r = p.add_run(note)
        set_run_font(r, size=11)

    # ---- Phụ lục A ----
    doc.add_page_break()
    heading(doc, "Phụ lục A — Danh sách endpoint", 1)
    body(
        doc,
        "Toàn bộ route do Flask đăng ký, trích trực tiếp từ url_map của ứng dụng. "
        "Cột Vai trò là mức quyền tối thiểu để gọi thành công.",
        italic=True,
        size=10,
    )

    routes = json.loads(ROUTES.read_text(encoding="utf-8"))
    ep_rows = []
    for idx, row in enumerate(routes, start=1):
        ep = row["endpoint"]
        ep_rows.append(
            [
                str(idx),
                ", ".join(row["methods"]),
                row["rule"],
                EP_LABEL.get(ep, ep),
                ep_roles(row["rule"], ep, row["methods"]),
            ]
        )

    add_table(
        doc,
        ["STT", "Method", "Endpoint", "Chức năng", "Vai trò"],
        ep_rows,
        [1.0, 1.5, 7.0, 5.9, 2.6],
        font_size=8,
        header_size=8,
    )

    # ---- Phụ lục B ----
    doc.add_page_break()
    heading(doc, "Phụ lục B — Ma trận quyền truy cập", 1)
    matrix = [
        ["/", "✓", "✓", "✓", "✓"],
        ["/courses", "✓", "✓", "✓", "✓"],
        ["/courses/:id", "✓", "✓", "✓", "✓ (giới hạn)"],
        ["/dashboard", "✓", "✓", "✓", "—"],
        ["/my-courses", "—", "—", "✓", "—"],
        ["/grades", "—", "—", "✓", "—"],
        ["/instructor/*", "—", "✓", "—", "—"],
        ["/admin/*", "✓", "—", "—", "—"],
        ["/api/courses", "✓", "✓", "✓", "✓"],
        ["/api/courses/:id/grades", "✓", "✓", "✓ (của mình)", "—"],
    ]
    add_table(
        doc,
        ["Route", "QT", "GV", "SV", "Khách"],
        matrix,
        [7.4, 2.4, 2.4, 3.0, 2.6],
        font_size=10,
    )

    # ---- Phụ lục C ----
    heading(doc, "Phụ lục C — Bảng dữ liệu chính", 1)
    tables = [
        ("users", "Tài khoản, vai trò, trạng thái, avatar, tuỳ chọn email"),
        ("auth_sessions", "Phiên JWT có thể thu hồi"),
        ("password_reset_tokens", "Token khôi phục mật khẩu (SHA-256, TTL)"),
        ("courses / chapters / lessons", "Khoá học, chương, bài học"),
        ("enrollments / lesson_progress", "Ghi danh và tiến độ học"),
        ("assignments / submissions", "Bài tập, bài nộp, điểm, tệp"),
        ("quizzes / questions / quiz_attempts", "Bài kiểm tra, câu hỏi, lượt làm bài"),
        ("attachments", "Tài liệu bài giảng"),
        ("forum_topics / forum_posts", "Diễn đàn"),
        ("notifications / direct_messages", "Thông báo và tin nhắn"),
        ("audit_events", "Nhật ký hoạt động"),
        ("certificates / badges / user_badges", "Chứng chỉ và huy hiệu"),
        ("settings", "Cấu hình hệ thống"),
    ]
    add_table(doc, ["Bảng", "Mục đích"], [list(t) for t in tables], [7.0, 10.4], font_size=10)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(OUT)
    print(f"saved: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
