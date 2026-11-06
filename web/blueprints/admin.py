"""Blueprint quản trị viên — spec mục 4.

Route: /admin/dashboard, /admin/users, /admin/courses, /admin/reports, /admin/settings
"""

from __future__ import annotations

from typing import Any

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session
from werkzeug.wrappers import Response

from web.audit import record as audit_record
from web.auth import admin_required, current_user
from web.database import get_db
from web.grade_service import (
    GradeConflict,
    GradeNotFound,
    GradeValidationError,
    update_quiz_grade,
    update_submission_grade,
)
from web.models import (
    ROLE_ADMIN,
    ROLE_INSTRUCTOR,
    ROLE_STUDENT,
    ROLE_LABELS,
    COURSE_PUBLISHED,
    COURSE_DRAFT,
    COURSE_HIDDEN,
    ENROLL_ACTIVE,
    ENROLL_COMPLETED,
    AuditEvent,
    User,
    Chapter,
    Lesson,
    Course,
    Enrollment,
    Quiz,
    QuizAttempt,
    Assignment,
    Submission,
    Certificate,
    Badge,
    Setting,
    Category,
    ForumTopic,
    ForumPost,
    Notification,
    LiveSession,
    UserBadge,
    utcnow,
)

bp = Blueprint("admin", __name__, url_prefix="/admin")


@bp.get("/dashboard")
@admin_required
def dashboard() -> str:
    """Tổng quan hệ thống."""
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        totals = {
            "users": sess.scalar(select(func.count()).select_from(User)) or 0,
            "courses": sess.scalar(select(func.count()).select_from(Course)) or 0,
            "enrollments": sess.scalar(select(func.count()).select_from(Enrollment)) or 0,
            "published": sess.scalar(
                select(func.count())
                .select_from(Course)
                .where(Course.status == COURSE_PUBLISHED)
            )
            or 0,
        }
        role_counts = [
            {
                "role": role,
                "label": ROLE_LABELS.get(role, role),
                "count": sess.scalar(
                    select(func.count()).select_from(User).where(User.role == role)
                )
                or 0,
            }
            for role in (ROLE_ADMIN, ROLE_INSTRUCTOR, ROLE_STUDENT)
        ]
        recent = sess.execute(
            select(Course, User)
            .join(User, Course.instructor_id == User.id)
            .order_by(Course.created_at.desc())
            .limit(8)
        ).all()
        recent = [{"course": c, "instructor": u} for c, u in recent]

    return render_template("admin/dashboard.html", totals=totals, role_counts=role_counts, recent=recent)


# ---------------------------------------------------------------------------
# Users management
# ---------------------------------------------------------------------------


@bp.get("/users")
@admin_required
def users() -> str:
    """Danh sách người dùng."""
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        users_list = sess.scalars(
            select(User).order_by(User.created_at.desc())
        ).all()

    return render_template("admin/users.html", users=users_list)


@bp.post("/users/<user_id>/lock")
@admin_required
def user_lock(user_id: str) -> Response:
    """Khóa tài khoản."""
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        user = sess.get(User, user_id)
        if not user:
            abort(404)
        if user.id == actor["id"]:
            flash("Không thể khóa chính mình.", "error")
        else:
            user.status = "LOCKED"
            sess.flush()
            audit_record("USER_LOCK", f"user:{user_id}", actor_id=actor["id"])
            flash("Đã khóa tài khoản.", "success")

    return redirect(url_for("admin.users"))


@bp.post("/users/<user_id>/unlock")
@admin_required
def user_unlock(user_id: str) -> Response:
    """Mở khóa tài khoản."""
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        user = sess.get(User, user_id)
        if not user:
            abort(404)
        user.status = "ACTIVE"
        sess.flush()
        audit_record("USER_UNLOCK", f"user:{user_id}", actor_id=actor["id"])
        flash("Đã mở khóa tài khoản.", "success")

    return redirect(url_for("admin.users"))


@bp.post("/users/<user_id>/role")
@admin_required
def user_change_role(user_id: str) -> Response:
    """Thay đổi vai trò."""
    actor = current_user()
    assert actor is not None

    new_role = (request.form.get("role") or "").strip()
    if new_role not in ("ADMIN", "INSTRUCTOR", "STUDENT"):
        flash("Vai trò không hợp lệ.", "error")
        return redirect(url_for("admin.users"))

    with get_db().session() as sess:
        user = sess.get(User, user_id)
        if not user:
            abort(404)
        if user.id == actor["id"]:
            flash("Không thể thay đổi vai trò chính mình.", "error")
        else:
            old_role = user.role
            user.role = new_role
            sess.flush()
            audit_record(
                "USER_ROLE_CHANGE",
                f"user:{user_id}",
                actor_id=actor["id"],
                old_role=old_role,
                new_role=new_role,
            )
            flash("Đã thay đổi vai trò.", "success")

    return redirect(url_for("admin.users"))


# ---------------------------------------------------------------------------
# Courses management
# ---------------------------------------------------------------------------


@bp.get("/courses")
@admin_required
def courses() -> str:
    """Danh sách tất cả khóa học."""
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        courses_list = sess.execute(
            select(Course, User)
            .join(User, Course.instructor_id == User.id)
            .order_by(Course.created_at.desc())
        ).all()
        courses_list = [{"course": c, "instructor": u} for c, u in courses_list]

    return render_template("admin/courses.html", courses=courses_list)


@bp.post("/courses/<course_id>/status")
@admin_required
def course_status(course_id: str) -> Response:
    """Thay đổi trạng thái khóa học."""
    actor = current_user()
    assert actor is not None

    new_status = (request.form.get("status") or "").strip()
    if new_status not in (COURSE_DRAFT, COURSE_PUBLISHED, COURSE_HIDDEN):
        flash("Trạng thái không hợp lệ.", "error")
        return redirect(url_for("admin.courses"))

    with get_db().session() as sess:
        course = sess.get(Course, course_id)
        if not course:
            abort(404)
        course.status = new_status
        flash("Đã cập nhật trạng thái.", "success")

    return redirect(url_for("admin.courses"))


@bp.post("/courses/<course_id>/delete")
@admin_required
def course_delete(course_id: str) -> Response:
    """Xóa khóa học."""
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        course = sess.get(Course, course_id)
        if not course:
            abort(404)
        sess.delete(course)
        flash("Đã xóa khóa học.", "success")

    return redirect(url_for("admin.courses"))


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------


@bp.get("/reports")
@admin_required
def reports() -> str:
    """Báo cáo hệ thống."""
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        from web.models import QuizAttempt, Submission, Certificate, LessonProgress

        stats = {
            "total_quiz_attempts": sess.scalar(select(func.count()).select_from(QuizAttempt)) or 0,
            "total_submissions": sess.scalar(select(func.count()).select_from(Submission)) or 0,
            "total_certificates": sess.scalar(select(func.count()).select_from(Certificate)) or 0,
            "total_lesson_progress": sess.scalar(select(func.count()).select_from(LessonProgress)) or 0,
        }

        # Top courses by enrollment
        top_courses = sess.execute(
            select(Course, func.count(Enrollment.id))
            .outerjoin(Enrollment, Enrollment.course_id == Course.id)
            .group_by(Course.id)
            .order_by(func.count(Enrollment.id).desc())
            .limit(10)
        ).all()

        # Users by role
        users_by_role = [
            {
                "role": role,
                "count": sess.scalar(select(func.count()).select_from(User).where(User.role == role)) or 0,
            }
            for role in (ROLE_ADMIN, ROLE_INSTRUCTOR, ROLE_STUDENT)
        ]

    return render_template("admin/reports.html", stats=stats, top_courses=top_courses, users_by_role=users_by_role)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


@bp.get("/settings")
@admin_required
def settings() -> str:
    """Cài đặt hệ thống."""
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        from web.models import Setting
        settings_list = sess.scalars(select(Setting).order_by(Setting.key)).all()

    return render_template("admin/settings.html", settings=settings_list)


@bp.post("/settings")
@admin_required
def settings_update() -> Response:
    """Cập nhật cài đặt."""
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        from web.models import Setting
        for key in request.form:
            if key.startswith("setting_"):
                setting_key = key[8:]  # remove "setting_"
                value = request.form[key]
                setting = sess.get(Setting, setting_key)
                if setting:
                    setting.value = value
                else:
                    sess.add(Setting(key=setting_key, value=value))
        flash("Đã cập nhật cài đặt.", "success")

    return redirect(url_for("admin.settings"))


# ---------------------------------------------------------------------------
# User Detail
# ---------------------------------------------------------------------------


@bp.get("/users/<user_id>")
@admin_required
def user_detail(user_id: str) -> str:
    """Chi tiết người dùng."""
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        user = sess.get(User, user_id)
        if not user:
            abort(404)

        # Enrollments
        enrollments = sess.execute(
            select(Enrollment, Course)
            .join(Course, Enrollment.course_id == Course.id)
            .where(Enrollment.student_id == user_id)
        ).all()

        # Courses taught (if instructor)
        taught = []
        if user.role == ROLE_INSTRUCTOR:
            taught = sess.scalars(
                select(Course).where(Course.instructor_id == user_id)
            ).all()

        # Certificates earned
        certificates = sess.execute(
            select(Certificate, Course)
            .join(Course, Certificate.course_id == Course.id)
            .where(Certificate.user_id == user_id)
        ).all()

        # Quiz attempts
        attempts = sess.execute(
            select(QuizAttempt, Quiz, Course)
            .join(Quiz, QuizAttempt.quiz_id == Quiz.id)
            .join(Course, Quiz.course_id == Course.id)
            .where(QuizAttempt.student_id == user_id)
            .order_by(QuizAttempt.started_at.desc())
            .limit(20)
        ).all()

    return render_template("admin/user_detail.html", 
                           user=user, enrollments=enrollments, 
                           taught=taught, certificates=certificates, attempts=attempts)


# ---------------------------------------------------------------------------
# Course Detail (Admin)
# ---------------------------------------------------------------------------


@bp.get("/courses/<course_id>")
@admin_required
def course_detail(course_id: str) -> str:
    """Chi tiết khóa học (admin view)."""
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        course = sess.get(Course, course_id)
        if not course:
            abort(404)

        instructor = sess.get(User, course.instructor_id)
        instructors = sess.scalars(
            select(User).where(User.role == ROLE_INSTRUCTOR)
        ).all()
        
        # Enrollments
        enrollments = sess.execute(
            select(Enrollment, User)
            .join(User, Enrollment.student_id == User.id)
            .where(Enrollment.course_id == course_id)
        ).all()

        # Curriculum
        chapters = sess.execute(
            select(Chapter, func.count(Lesson.id))
            .outerjoin(Lesson, Lesson.chapter_id == Chapter.id)
            .where(Chapter.course_id == course_id)
            .group_by(Chapter.id)
            .order_by(Chapter.position)
        ).all()

        # Quizzes
        quizzes = sess.scalars(
            select(Quiz).where(Quiz.course_id == course_id)
        ).all()

        # Assignments
        assignments = sess.scalars(
            select(Assignment).where(Assignment.course_id == course_id)
        ).all()

        # Certificates issued
        certificates = sess.execute(
            select(Certificate, User)
            .join(User, Certificate.user_id == User.id)
            .where(Certificate.course_id == course_id)
        ).all()

    return render_template("admin/course_detail.html",
                           course=course, instructor=instructor,
                           enrollments=enrollments, chapters=chapters,
                           quizzes=quizzes, assignments=assignments,
                           certificates=certificates)


@bp.post("/courses/<course_id>/reassign")
@admin_required
def course_reassign(course_id: str) -> Response:
    """Chuyển GV phụ trách."""
    actor = current_user()
    assert actor is not None

    new_instructor_id = (request.form.get("instructor_id") or "").strip()
    if not new_instructor_id:
        flash("Chọn giảng viên mới.", "error")
        return redirect(url_for("admin.course_detail", course_id=course_id))

    with get_db().session() as sess:
        course = sess.get(Course, course_id)
        new_instructor = sess.get(User, new_instructor_id)
        if not course or not new_instructor or new_instructor.role != ROLE_INSTRUCTOR:
            abort(404)
        course.instructor_id = new_instructor_id
        flash("Đã chuyển giảng viên.", "success")

    return redirect(url_for("admin.course_detail", course_id=course_id))


# ---------------------------------------------------------------------------
# Categories Management
# ---------------------------------------------------------------------------


@bp.get("/categories")
@admin_required
def categories() -> str:
    """Quản lý danh mục."""
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        cats = sess.scalars(select(Category).order_by(Category.name)).all()

    return render_template("admin/categories.html", categories=cats)


@bp.post("/categories/new")
@admin_required
def category_create() -> Response:
    """Tạo danh mục mới."""
    actor = current_user()
    assert actor is not None

    name = (request.form.get("name") or "").strip()
    if not name:
        flash("Tên danh mục là bắt buộc.", "error")
    else:
        with get_db().session() as sess:
            if sess.scalars(select(Category).where(Category.name == name)).first():
                flash("Danh mục đã tồn tại.", "error")
            else:
                sess.add(Category(name=name))
                flash("Đã tạo danh mục.", "success")

    return redirect(url_for("admin.categories"))


@bp.post("/categories/<int:cat_id>/delete")
@admin_required
def category_delete(cat_id: int) -> Response:
    """Xóa danh mục."""
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        cat = sess.get(Category, cat_id)
        if not cat:
            abort(404)
        sess.delete(cat)
        flash("Đã xóa danh mục.", "success")

    return redirect(url_for("admin.categories"))


# ---------------------------------------------------------------------------
# System-wide Quizzes
# ---------------------------------------------------------------------------


@bp.get("/quizzes")
@admin_required
def quizzes() -> str:
    """Toàn bộ bài kiểm tra."""
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        quizzes_list = sess.execute(
            select(Quiz, Course, User)
            .join(Course, Quiz.course_id == Course.id)
            .join(User, Course.instructor_id == User.id)
            .order_by(Quiz.created_at.desc())
        ).all()

    return render_template("admin/quizzes.html", quizzes=quizzes_list)


@bp.post("/quizzes/<int:quiz_id>/delete")
@admin_required
def quiz_delete(quiz_id: int) -> Response:
    """Xóa bài kiểm tra."""
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        quiz = sess.get(Quiz, quiz_id)
        if not quiz:
            abort(404)
        sess.delete(quiz)
        flash("Đã xóa bài kiểm tra.", "success")

    return redirect(url_for("admin.quizzes"))


# ---------------------------------------------------------------------------
# System-wide Assignments
# ---------------------------------------------------------------------------


@bp.get("/assignments")
@admin_required
def assignments() -> str:
    """Toàn bộ bài tập."""
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        assignments_list = sess.execute(
            select(Assignment, Course, User)
            .join(Course, Assignment.course_id == Course.id)
            .join(User, Course.instructor_id == User.id)
            .order_by(Assignment.created_at.desc())
        ).all()

    return render_template("admin/assignments.html", assignments=assignments_list)


@bp.post("/assignments/<int:assignment_id>/delete")
@admin_required
def assignment_delete(assignment_id: int) -> Response:
    """Xóa bài tập."""
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        assignment = sess.get(Assignment, assignment_id)
        if not assignment:
            abort(404)
        sess.delete(assignment)
        flash("Đã xóa bài tập.", "success")

    return redirect(url_for("admin.assignments"))


# ---------------------------------------------------------------------------
# System-wide Grades
# ---------------------------------------------------------------------------


@bp.get("/grades")
@admin_required
def grades() -> str:
    """Bảng điểm toàn hệ thống."""
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        context = _grades_context(sess)

    return render_template("admin/grades.html", **context)


def _grades_context(sess: Session) -> dict[str, Any]:
    # All quiz attempts with scores
    attempts = sess.execute(
        select(QuizAttempt, Quiz, Course, User)
        .join(Quiz, QuizAttempt.quiz_id == Quiz.id)
        .join(Course, Quiz.course_id == Course.id)
        .join(User, QuizAttempt.student_id == User.id)
        .where(QuizAttempt.status == "SUBMITTED")
        .order_by(QuizAttempt.submitted_at.desc())
    ).all()

    # All assignment submissions
    submissions = sess.execute(
        select(Submission, Assignment, Course, User)
        .join(Assignment, Submission.assignment_id == Assignment.id)
        .join(Course, Assignment.course_id == Course.id)
        .join(User, Submission.student_id == User.id)
        .order_by(Submission.submitted_at.desc())
    ).all()

    return {"attempts": attempts, "submissions": submissions}


@bp.post("/grades/quiz/<int:attempt_id>/adjust")
@admin_required
def grade_quiz_adjust(attempt_id: int) -> Response:
    """Chỉnh sửa điểm quiz (có kiểm tra version)."""
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        try:
            update_quiz_grade(
                sess,
                actor,
                attempt_id,
                request.form.get("score"),
                request.form.get("version"),
            )
        except GradeValidationError as exc:
            flash(str(exc), "error")
            return redirect(url_for("admin.grades"))
        except GradeNotFound:
            abort(404)
        except GradeConflict as exc:
            context = _grades_context(sess)
            context["conflict"] = str(exc)
            return render_template("admin/grades.html", **context), 409
        flash("Đã cập nhật điểm.", "success")

    return redirect(url_for("admin.grades"))


@bp.post("/grades/assignment/<int:submission_id>/adjust")
@admin_required
def grade_assignment_adjust(submission_id: int) -> Response:
    """Chỉnh sửa điểm assignment (có kiểm tra version)."""
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        try:
            update_submission_grade(
                sess,
                actor,
                submission_id,
                request.form.get("score"),
                request.form.get("feedback"),
                request.form.get("version"),
            )
        except GradeValidationError as exc:
            flash(str(exc), "error")
            return redirect(url_for("admin.grades"))
        except GradeNotFound:
            abort(404)
        except GradeConflict as exc:
            context = _grades_context(sess)
            context["conflict"] = str(exc)
            return render_template("admin/grades.html", **context), 409
        flash("Đã cập nhật điểm.", "success")

    return redirect(url_for("admin.grades"))


# ---------------------------------------------------------------------------
# System-wide Certificates
# ---------------------------------------------------------------------------


@bp.get("/certificates")
@admin_required
def certificates() -> str:
    """Quản lý chứng chỉ toàn hệ thống."""
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        certs = sess.execute(
            select(Certificate, User, Course)
            .join(User, Certificate.user_id == User.id)
            .join(Course, Certificate.course_id == Course.id)
            .order_by(Certificate.issued_at.desc())
        ).all()
        students = sess.scalars(select(User).where(User.role == ROLE_STUDENT)).all()
        courses = sess.scalars(select(Course).where(Course.status == COURSE_PUBLISHED)).all()

    return render_template("admin/certificates.html", certificates=certs, students=students, courses=courses)


@bp.post("/certificates/<int:cert_id>/revoke")
@admin_required
def certificate_revoke(cert_id: int) -> Response:
    """Thu hồi chứng chỉ."""
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        cert = sess.get(Certificate, cert_id)
        if not cert:
            abort(404)
        sess.delete(cert)
        flash("Đã thu hồi chứng chỉ.", "success")

    return redirect(url_for("admin.certificates"))


@bp.post("/certificates/issue")
@admin_required
def certificate_issue() -> Response:
    """Cấp chứng chỉ mới."""
    actor = current_user()
    assert actor is not None

    user_id = (request.form.get("user_id") or "").strip()
    course_id = (request.form.get("course_id") or "").strip()
    final_score = request.form.get("final_score")

    if not user_id or not course_id or final_score is None:
        flash("Thiếu thông tin.", "error")
        return redirect(url_for("admin.certificates"))

    with get_db().session() as sess:
        user = sess.get(User, user_id)
        course = sess.get(Course, course_id)
        if not user or not course:
            abort(404)
        
        existing = sess.scalars(
            select(Certificate).where(
                Certificate.user_id == user_id,
                Certificate.course_id == course_id,
            )
        ).first()
        if existing:
            flash("Người dùng đã có chứng chỉ khóa này.", "error")
        else:
            sess.add(Certificate(
                code=f"CERT-{course.id.upper()}-{user_id.upper()}-{int(utcnow().timestamp())}",
                user_id=user_id,
                course_id=course_id,
                final_score=float(final_score),
            ))
            flash("Đã cấp chứng chỉ.", "success")

    return redirect(url_for("admin.certificates"))


# ---------------------------------------------------------------------------
# Badges Management
# ---------------------------------------------------------------------------


@bp.get("/badges")
@admin_required
def badges() -> str:
    """Quản lý huy hiệu."""
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        badges_list = sess.scalars(select(Badge).order_by(Badge.name)).all()

    return render_template("admin/badges.html", badges=badges_list)


@bp.post("/badges/new")
@admin_required
def badge_create() -> Response:
    """Tạo huy hiệu mới."""
    actor = current_user()
    assert actor is not None

    name = (request.form.get("name") or "").strip()
    description = (request.form.get("description") or "").strip()
    icon = (request.form.get("icon") or "").strip()
    condition_type = (request.form.get("condition_type") or "").strip()
    condition_value = (request.form.get("condition_value") or "").strip()

    if not name:
        flash("Tên huy hiệu là bắt buộc.", "error")
    else:
        with get_db().session() as sess:
            sess.add(Badge(
                name=name,
                description=description,
                icon=icon,
                condition_type=condition_type or None,
                condition_value=condition_value or None,
            ))
            flash("Đã tạo huy hiệu.", "success")

    return redirect(url_for("admin.badges"))


@bp.post("/badges/<int:badge_id>/delete")
@admin_required
def badge_delete(badge_id: int) -> Response:
    """Xóa huy hiệu."""
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        badge = sess.get(Badge, badge_id)
        if not badge:
            abort(404)
        sess.delete(badge)
        flash("Đã xóa huy hiệu.", "success")

    return redirect(url_for("admin.badges"))


# ---------------------------------------------------------------------------
# Reports - Courses
# ---------------------------------------------------------------------------


@bp.get("/reports/courses")
@admin_required
def reports_courses() -> str:
    """Báo cáo theo khóa học."""
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        courses_data = sess.execute(
            select(
                Course,
                User,
                func.count(Enrollment.id).label("enrollments"),
                func.count(case((Enrollment.status == ENROLL_COMPLETED, 1))).label("completed"),
                func.avg(case((Enrollment.status == ENROLL_COMPLETED, 100), else_=0)).label("completion_rate"),
                func.sum(Course.price).label("revenue"),
            )
            .outerjoin(Enrollment, Enrollment.course_id == Course.id)
            .join(User, Course.instructor_id == User.id)
            .group_by(Course.id, User.id)
            .order_by(func.count(Enrollment.id).desc())
        ).all()

    return render_template("admin/reports_courses.html", courses_data=courses_data)


# ---------------------------------------------------------------------------
# Reports - Users
# ---------------------------------------------------------------------------


@bp.get("/reports/users")
@admin_required
def reports_users() -> str:
    """Báo cáo theo người dùng."""
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        users_data = sess.execute(
            select(
                User,
                func.count(Enrollment.id).label("enrollments"),
                func.count(case((Enrollment.status == ENROLL_COMPLETED, 1))).label("completed"),
                func.count(QuizAttempt.id).label("quiz_attempts"),
                func.avg(QuizAttempt.score).label("avg_quiz_score"),
                func.count(Certificate.id).label("certificates"),
            )
            .outerjoin(Enrollment, Enrollment.student_id == User.id)
            .outerjoin(QuizAttempt, QuizAttempt.student_id == User.id)
            .outerjoin(Certificate, Certificate.user_id == User.id)
            .where(User.role == ROLE_STUDENT)
            .group_by(User.id)
            .order_by(func.count(Enrollment.id).desc())
        ).all()

    return render_template("admin/reports_users.html", users_data=users_data)


# ---------------------------------------------------------------------------
# System-wide Forum
# ---------------------------------------------------------------------------


@bp.get("/forum")
@admin_required
def forum() -> str:
    """Toàn bộ diễn đàn."""
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        topics = sess.execute(
            select(ForumTopic, Course, User)
            .join(Course, ForumTopic.course_id == Course.id)
            .join(User, ForumTopic.author_id == User.id)
            .order_by(ForumTopic.created_at.desc())
        ).all()

    return render_template("admin/forum.html", topics=topics)


@bp.post("/forum/<int:topic_id>/moderate")
@admin_required
def forum_moderate(topic_id: int) -> Response:
    """Moderate diễn đàn (pin/lock/delete)."""
    actor = current_user()
    assert actor is not None

    action = (request.form.get("action") or "").strip()
    with get_db().session() as sess:
        topic = sess.get(ForumTopic, topic_id)
        if not topic:
            abort(404)
        if action == "pin":
            topic.pinned = not topic.pinned
            flash("Đã " + ("ghim" if topic.pinned else "bỏ ghim") + " chủ đề.", "success")
        elif action == "lock":
            topic.locked = not topic.locked
            flash("Đã " + ("khoá" if topic.locked else "mở khoá") + " chủ đề.", "success")
        elif action == "delete":
            sess.delete(topic)
            flash("Đã xóa chủ đề.", "success")

    return redirect(url_for("admin.forum"))


# ---------------------------------------------------------------------------
# System-wide Notifications
# ---------------------------------------------------------------------------


@bp.get("/notifications")
@admin_required
def notifications() -> str:
    """Gửi thông báo hệ thống."""
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        # Recent notifications sent
        recent = sess.execute(
            select(Notification, User)
            .join(User, Notification.user_id == User.id)
            .order_by(Notification.created_at.desc())
            .limit(50)
        ).all()

    return render_template("admin/notifications.html", recent=recent)


@bp.post("/notifications/send")
@admin_required
def notification_send() -> Response:
    """Gửi thông báo."""
    actor = current_user()
    assert actor is not None

    target = (request.form.get("target") or "all").strip()  # all, role, user
    title = (request.form.get("title") or "").strip()
    body = (request.form.get("body") or "").strip()
    link = (request.form.get("link") or "").strip()

    if not title or not body:
        flash("Tiêu đề và nội dung là bắt buộc.", "error")
        return redirect(url_for("admin.notifications"))

    with get_db().session() as sess:
        if target == "all":
            users = sess.scalars(select(User.id).where(User.status == "ACTIVE")).all()
        elif target.startswith("role:"):
            role = target[5:]
            users = sess.scalars(select(User.id).where(User.role == role, User.status == "ACTIVE")).all()
        else:
            users = [target] if sess.get(User, target) else []

        for uid in users:
            sess.add(Notification(
                user_id=uid,
                kind="SYSTEM",
                title=title,
                body=body,
                link=link or None,
            ))
        flash(f"Đã gửi thông báo đến {len(users)} người dùng.", "success")

    return redirect(url_for("admin.notifications"))


# ---------------------------------------------------------------------------
# System-wide Live Sessions
# ---------------------------------------------------------------------------


@bp.get("/live")
@admin_required
def live() -> str:
    """Quản lý live session toàn hệ thống."""
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        sessions = sess.execute(
            select(LiveSession, Course, User)
            .join(Course, LiveSession.course_id == Course.id)
            .join(User, Course.instructor_id == User.id)
            .order_by(LiveSession.start_at.desc())
        ).all()

    return render_template("admin/live.html", sessions=sessions)


@bp.post("/live/<int:session_id>/delete")
@admin_required
def live_delete(session_id: int) -> Response:
    """Xóa live session."""
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        session = sess.get(LiveSession, session_id)
        if not session:
            abort(404)
        sess.delete(session)
        flash("Đã xóa buổi học.", "success")

    return redirect(url_for("admin.live"))


# ---------------------------------------------------------------------------
# Settings - Roles
# ---------------------------------------------------------------------------


@bp.get("/settings/roles")
@admin_required
def settings_roles() -> str:
    """Cấu hình phân quyền."""
    actor = current_user()
    assert actor is not None

    # Define all available permissions
    all_permissions = [
        "view_dashboard", "view_courses", "manage_courses",
        "view_quizzes", "manage_quizzes", "take_quizzes",
        "view_assignments", "manage_assignments", "submit_assignments",
        "view_grades", "manage_grades",
        "view_certificates", "manage_certificates",
        "view_forum", "manage_forum", "post_forum",
        "view_messages", "send_messages",
        "view_notifications", "send_notifications",
        "view_profile", "edit_profile",
        "view_reports", "manage_users",
        "manage_categories", "manage_badges",
        "manage_live", "manage_settings",
    ]

    with get_db().session() as sess:
        settings_list = sess.scalars(select(Setting).where(Setting.key.startswith("role_perms_"))).all()
        current_perms = {s.key[11:]: s.value for s in settings_list}

    return render_template("admin/settings_roles.html", 
                           all_permissions=all_permissions, current_perms=current_perms)


@bp.post("/settings/roles")
@admin_required
def settings_roles_save() -> Response:
    """Lưu cấu hình phân quyền."""
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        for key, value in request.form.items():
            if key.startswith("perm_"):
                role = key[5:]  # remove "perm_"
                perms = value if isinstance(value, list) else [value]
                setting_key = f"role_perms_{role}"
                setting = sess.get(Setting, setting_key)
                if setting:
                    setting.value = ",".join(perms)
                else:
                    sess.add(Setting(key=setting_key, value=",".join(perms)))
        flash("Đã lưu phân quyền.", "success")

    return redirect(url_for("admin.settings_roles"))


# ---------------------------------------------------------------------------
# Settings - Payments
# ---------------------------------------------------------------------------


@bp.get("/settings/payments")
@admin_required
def settings_payments() -> str:
    """Cài đặt thanh toán."""
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        settings_list = sess.scalars(select(Setting).where(Setting.key.like("payment_%"))).all()
        current_settings = {s.key: s.value for s in settings_list}

    return render_template("admin/settings_payments.html", settings=current_settings)


@bp.post("/settings/payments")
@admin_required
def settings_payments_save() -> Response:
    """Lưu cài đặt thanh toán."""
    actor = current_user()
    assert actor is not None

    with get_db().session() as sess:
        for key, value in request.form.items():
            if key.startswith("payment_"):
                setting = sess.get(Setting, key)
                if setting:
                    setting.value = value
                else:
                    sess.add(Setting(key=key, value=value))
        flash("Đã lưu cài đặt thanh toán.", "success")

    audit_record("SETTINGS_UPDATED", "settings:payments", actor_id=actor["id"])
    return redirect(url_for("admin.settings_payments"))


# ---------------------------------------------------------------------------
# Nhật ký hoạt động (spec mục 7)
# ---------------------------------------------------------------------------


@bp.get("/audit")
@admin_required
def audit() -> str:
    """Nhật ký hoạt động: đăng nhập, đổi điểm, thao tác quản trị."""
    action = (request.args.get("action") or "").strip()
    actor_filter = (request.args.get("actor") or "").strip()
    page = max(1, request.args.get("page", type=int) or 1)
    per_page = 50

    with get_db().session() as sess:
        stmt = select(AuditEvent).order_by(AuditEvent.ts.desc())
        if action:
            stmt = stmt.where(AuditEvent.action == action)
        if actor_filter:
            stmt = stmt.where(AuditEvent.actor_id == actor_filter)
        total = sess.scalar(
            select(func.count()).select_from(stmt.subquery())
        ) or 0
        rows = sess.scalars(
            stmt.offset((page - 1) * per_page).limit(per_page)
        ).all()
        actors = sess.scalars(
            select(User).where(User.id.in_(select(AuditEvent.actor_id).distinct()))
        ).all()
        actions = sess.scalars(
            select(AuditEvent.action).distinct().order_by(AuditEvent.action)
        ).all()

    return render_template(
        "admin/audit.html",
        rows=rows,
        actors=actors,
        actions=actions,
        action=action,
        actor_filter=actor_filter,
        page=page,
        per_page=per_page,
        total=total,
    )

