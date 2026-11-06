"""Test giao diện web miniLMS theo kiến trúc blueprint + SQLAlchemy.

Phủ `lms_spec.md`: 4 vai trò, ma trận phân quyền route, các luồng nghiệp vụ chính.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from web import create_web_app
from web.models import (
    ROLE_ADMIN,
    ROLE_GUEST,
    ROLE_INSTRUCTOR,
    ROLE_STUDENT,
    User,
    normalize_role,
)

TEST_SECRET = "test-secret-key-that-is-at-least-32-chars-long-12345"
SEED_PATH = str(Path(__file__).resolve().parent.parent / "seed.json")
PASSWORD = "Lms@2026"


@pytest.fixture
def webapp():
    return create_web_app(
        {
            "JWT_SECRET": TEST_SECRET,
            "DATABASE_URL": "sqlite://",
            "SEED_PATH": SEED_PATH,
        }
    )


@pytest.fixture
def client(webapp):
    return webapp.test_client()


def login(client: Any, email: str, password: str = PASSWORD) -> Any:
    return client.post("/login", data={"email": email, "password": password})


# ---------- role enum: spec dòng 2 ----------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("ADMIN", ROLE_ADMIN),
        ("admin", ROLE_ADMIN),
        ("INSTRUCTOR", ROLE_INSTRUCTOR),
        ("TEACHER", ROLE_INSTRUCTOR),
        ("teacher", ROLE_INSTRUCTOR),
        ("STUDENT", ROLE_STUDENT),
        ("guest", ROLE_GUEST),
        ("khong-hop-le", ROLE_GUEST),
        (None, ROLE_GUEST),
    ],
)
def test_normalize_role(raw, expected):
    assert normalize_role(raw) == expected


def test_seed_roles(webapp):
    with webapp.extensions["lms_db"].session() as sess:
        assert sess.get(User, "u1").role == ROLE_ADMIN
        assert sess.get(User, "u2").role == ROLE_INSTRUCTOR
        assert sess.get(User, "u4").role == ROLE_STUDENT


# ---------- KHÁCH ----------


@pytest.mark.parametrize(
    "path",
    ["/", "/courses", "/courses/c1", "/instructors", "/login", "/register", "/forgot-password"],
)
def test_guest_pages_public(client, path):
    assert client.get(path).status_code == 200


def test_home_lists_courses(client):
    body = client.get("/").get_data(as_text=True)
    assert "miniLMS" in body
    assert "Lập trình Web" in body
    assert "Cơ sở dữ liệu" in body


def test_guest_private_route_redirects_to_login(client):
    res = client.get("/dashboard")
    assert res.status_code == 302
    assert "/login" in res.headers["Location"]


def test_guest_cannot_reach_student_learn(client):
    res = client.get("/my-courses/c1/learn")
    assert res.status_code == 302
    assert "/login" in res.headers["Location"]


def test_unknown_route_404(client):
    assert client.get("/khong-co-trang-nay").status_code == 404

# ---------- đăng nhập ----------


def test_login_sai_mat_khau(client):
    res = login(client, "chi.sv@lms.test", "sai-mat-khau")
    assert res.status_code == 401
    assert "không đúng" in res.get_data(as_text=True)


def test_login_email_khong_ton_tai_cung_thong_diep(client):
    res = login(client, "khongco@lms.test")
    assert res.status_code == 401
    assert "không đúng" in res.get_data(as_text=True)


def test_login_thieu_thong_tin(client):
    res = client.post("/login", data={"email": "", "password": ""})
    assert res.status_code == 401
    assert "Vui lòng nhập đầy đủ" in res.get_data(as_text=True)


@pytest.mark.parametrize(
    "email",
    ["admin@lms.test", "an.gv@lms.test", "chi.sv@lms.test"],
)
def test_redirect_sau_login_theo_role(client, email):
    """Spec dòng 151: Admin/GV/SV đều về dashboard."""
    res = login(client, email)
    assert res.status_code == 302
    assert "/dashboard" in res.headers["Location"]


def test_login_da_dang_nhap_bi_redirect(client):
    assert login(client, "chi.sv@lms.test").status_code == 302
    assert client.get("/login").status_code == 302


def test_khong_cho_open_redirect(client):
    res = client.post(
        "/login?next=//evil.example.com",
        data={"email": "chi.sv@lms.test", "password": PASSWORD},
    )
    assert res.status_code == 302
    assert "evil.example.com" not in res.headers["Location"]


def test_login_brute_force_lockout(client):
    from app.store import get_store

    email = "chi.sv@lms.test"
    try:
        for _ in range(5):
            assert login(client, email, "sai-mat-khau").status_code == 401
        res = login(client, email, "sai-mat-khau")
        assert res.status_code == 401
        assert "khoá" in res.get_data(as_text=True)
    finally:
        get_store().failed_logins.clear()


def test_logout_xoa_phien(client):
    assert login(client, "chi.sv@lms.test").status_code == 302
    assert client.post("/logout").status_code == 302
    assert client.get("/dashboard").status_code == 302


# ---------- SINH VIÊN ----------


@pytest.mark.parametrize(
    "path",
    [
        "/dashboard",
        "/my-courses",
        "/my-courses/c1/learn",
        "/grades",
        "/progress",
        "/certificates",
        "/leaderboard",
        "/settings",
    ],
)
def test_student_routes(client, path):
    assert login(client, "chi.sv@lms.test").status_code == 302
    assert client.get(path).status_code == 200


def test_student_khong_vao_duoc_instructor(client):
    login(client, "chi.sv@lms.test")
    assert client.get("/instructor/courses").status_code == 403


def test_student_learn_khoa_chua_ghi_danh_bi_403(client):
    """Spec dòng 148: cần enrollment active mới vào /learn."""
    login(client, "chi.sv@lms.test")
    assert client.get("/my-courses/c2/learn").status_code == 403

# ---------- GIẢNG VIÊN ----------


@pytest.mark.parametrize(
    'path',
    [
        '/dashboard',
        '/instructor/courses',
        '/instructor/courses/new',
        '/instructor/courses/c1/edit',
        '/instructor/courses/c1/curriculum',
        '/instructor/courses/c1/students',
        '/instructor/courses/c1/reports',
        '/instructor/quizzes',
        '/instructor/assignments',
        '/instructor/grades',
        '/instructor/certificates',
        '/instructor/forum',
        '/instructor/live',
    ],
)
def test_instructor_routes(client, path):
    assert login(client, 'an.gv@lms.test').status_code == 302
    assert client.get(path).status_code == 200


def test_instructor_chi_sua_duoc_khoa_minh_day(client):
    """Spec dòng 147: ownership check. an.gv dạy c1, không dạy c2."""
    login(client, 'an.gv@lms.test')
    assert client.get('/instructor/courses/c1/edit').status_code == 200
    assert client.get('/instructor/courses/c2/edit').status_code == 403


def test_instructor_khong_vao_duoc_khu_student(client):
    login(client, 'an.gv@lms.test')
    assert client.get('/my-courses').status_code == 403
    assert client.get('/grades').status_code == 403


def test_instructor_tao_khoa_hoc(client, webapp):
    from sqlalchemy import select

    from web.models import Course

    login(client, 'an.gv@lms.test')
    res = client.post(
        '/instructor/courses/new',
        data={
            'title': 'Khoá thử nghiệm',
            'description': 'mô tả',
            'price': '0',
            'status': 'DRAFT',
        },
    )
    assert res.status_code == 302
    with webapp.extensions["lms_db"].session() as sess:
        assert sess.scalars(
            select(Course).where(Course.title == 'Khoá thử nghiệm')
        ).first()


# ---------- ADMIN ----------


def test_admin_dashboard(client):
    login(client, 'admin@lms.test')
    res = client.get('/dashboard')
    assert res.status_code == 200
    body = res.get_data(as_text=True)
    assert 'người dùng' in body
    assert 'lượt ghi danh' in body


def test_admin_khong_vao_khu_instructor(client):
    """Spec: /instructor/* chỉ GV."""
    login(client, 'admin@lms.test')
    assert client.get('/instructor/courses').status_code == 403


def test_admin_bang_diem_hien_thi_du_lieu(client, webapp):
    """Regression: trang /admin/grades phải render được khi có điểm."""
    from sqlalchemy import select

    from web.models import Assignment, Quiz, QuizAttempt, Submission, utcnow

    with webapp.extensions['lms_db'].session() as sess:
        quiz = sess.scalars(select(Quiz).where(Quiz.course_id == 'c1')).first()
        assignment = sess.scalars(
            select(Assignment).where(Assignment.course_id == 'c1')
        ).first()
        sess.add(
            QuizAttempt(
                quiz_id=quiz.id,
                student_id='u4',
                status='SUBMITTED',
                score=7.5,
                passed=True,
                started_at=utcnow(),
                submitted_at=utcnow(),
            )
        )
        sess.add(
            Submission(
                assignment_id=assignment.id,
                student_id='u4',
                text='Bài làm',
                submitted_at=utcnow(),
                score=8.0,
                feedback='Tốt',
                graded_at=utcnow(),
            )
        )

    login(client, 'admin@lms.test')
    res = client.get('/admin/grades')
    assert res.status_code == 200
    body = res.get_data(as_text=True)
    assert 'Bảng điểm toàn hệ thống' in body
    assert 'Chi Nguyễn' in body

# ---------- QUIZ ----------


def test_quiz_intro_cho_sinh_vien_ghi_danh(client, webapp):
    from sqlalchemy import select

    from web.models import Quiz

    with webapp.extensions['lms_db'].session() as sess:
        quiz = sess.scalars(select(Quiz).where(Quiz.course_id == 'c1')).first()
    login(client, 'chi.sv@lms.test')
    assert client.get(f'/quizzes/{quiz.id}').status_code == 200


def test_quiz_luong_lam_bai_va_cham_diem(client, webapp):
    from sqlalchemy import select

    from web.models import Question, Quiz, QuizAttempt, QuizQuestion

    with webapp.extensions['lms_db'].session() as sess:
        quiz = sess.scalars(select(Quiz).where(Quiz.course_id == 'c1')).first()
        questions = sess.scalars(
            select(Question)
            .join(QuizQuestion, QuizQuestion.question_id == Question.id)
            .where(QuizQuestion.quiz_id == quiz.id)
        ).all()
        correct_answers = {
            q.id: q.options[q.answer['index']] for q in questions
        }
        quiz_id = quiz.id

    login(client, 'chi.sv@lms.test')
    res = client.post(f'/quizzes/{quiz_id}/start')
    assert res.status_code == 302

    with webapp.extensions['lms_db'].session() as sess:
        attempt = sess.scalars(
            select(QuizAttempt).where(
                QuizAttempt.quiz_id == quiz_id, QuizAttempt.student_id == 'u4'
            )
        ).first()
        attempt_id = attempt.id

    # Submit answers for all questions
    submit_data = {f'q_{qid}': answer for qid, answer in correct_answers.items()}
    res = client.post(
        f'/quizzes/{quiz_id}/attempts/{attempt_id}/submit', data=submit_data
    )
    assert res.status_code == 302

    with webapp.extensions['lms_db'].session() as sess:
        attempt = sess.get(QuizAttempt, attempt_id)
        assert attempt.status == 'SUBMITTED'
        assert attempt.score == 10.0
        assert attempt.passed is True


def test_quiz_guest_bi_chan(client, webapp):
    from sqlalchemy import select

    from web.models import Quiz

    with webapp.extensions['lms_db'].session() as sess:
        quiz = sess.scalars(select(Quiz)).first()
    assert client.get(f'/quizzes/{quiz.id}').status_code == 302


# ---------- BÀI TẬP ----------


def test_assignment_nop_va_cham_diem(client, webapp):
    from sqlalchemy import select

    from web.models import Assignment, Submission

    with webapp.extensions['lms_db'].session() as sess:
        assignment = sess.scalars(select(Assignment).where(Assignment.course_id == 'c1')).first()
        aid = assignment.id

    login(client, 'chi.sv@lms.test')
    res = client.post(f'/assignments/{aid}/submit', data={'text': 'Bài làm của em'})
    assert res.status_code == 302

    with webapp.extensions['lms_db'].session() as sess:
        submission = sess.scalars(
            select(Submission).where(
                Submission.assignment_id == aid, Submission.student_id == 'u4'
            )
        ).first()
        sid = submission.id

    # GV chấm điểm
    grader = webapp.test_client()
    login(grader, 'an.gv@lms.test')
    res = grader.post(
        f'/assignments/{aid}/submissions/{sid}/grade',
        data={'score': '9', 'feedback': 'Tốt'},
    )
    assert res.status_code == 302
    with webapp.extensions['lms_db'].session() as sess:
        submission = sess.get(Submission, sid)
        assert submission.score == 9.0
        assert submission.feedback == 'Tốt'


# ---------- ĐĂNG KÝ ----------


def test_register_page_get(client):
    res = client.get('/register')
    assert res.status_code == 200
    assert 'Đăng ký tài khoản' in res.get_data(as_text=True)


def test_register_success(client):
    res = client.post(
        '/register',
        data={
            'email': 'newbie@lms.test',
            'password': 'Password@123',
            'confirm_password': 'Password@123',
            'role': 'STUDENT',
        },
    )
    assert res.status_code == 302
    assert client.get('/dashboard').status_code == 200


def test_register_validation_password_yeu(client):
    res = client.post(
        '/register',
        data={'email': 'bad@lms.test', 'password': '123', 'confirm_password': '123'},
    )
    assert res.status_code == 400
    assert 'ít nhất 8 ký tự' in res.get_data(as_text=True)


def test_register_password_khong_khop(client):
    res = client.post(
        '/register',
        data={
            'email': 'mismatch@lms.test',
            'password': 'Password@123',
            'confirm_password': 'DifferentPassword@123',
        },
    )
    assert res.status_code == 400
    assert 'không khớp' in res.get_data(as_text=True)


def test_register_email_trung(client):
    res = client.post(
        '/register',
        data={
            'email': 'chi.sv@lms.test',
            'password': 'Password@123',
            'confirm_password': 'Password@123',
        },
    )
    assert res.status_code == 400
    assert 'đã được sử dụng' in res.get_data(as_text=True)


# ---------- QUÊN / ĐẶT LẠI MẬT KHẨU ----------


def test_forgot_password_page_get(client):
    res = client.get('/forgot-password')
    assert res.status_code == 200
    assert 'Quên mật khẩu' in res.get_data(as_text=True)


def test_forgot_password_gui_lien_ket(client):
    res = client.post('/forgot-password', data={'email': 'chi.sv@lms.test'})
    assert res.status_code == 200
    # Không đổi mật khẩu trực tiếp: chỉ gửi liên kết.
    assert 'liên kết đặt lại mật khẩu' in res.get_data(as_text=True)
    assert login(client, 'chi.sv@lms.test', 'Lms@2026').status_code == 302


def test_forgot_password_email_khong_ton_tai(client):
    res = client.post('/forgot-password', data={'email': 'notfound@lms.test'})
    # Chống liệt kê tài khoản: luôn trả cùng một thông báo.
    assert res.status_code == 200
    assert 'Nếu email tồn tại' in res.get_data(as_text=True)