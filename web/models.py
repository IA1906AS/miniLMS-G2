"""Mô hình dữ liệu LMS (SQLAlchemy 2.x).

Schema đầy đủ cho 7 nhóm chức năng:
  1. user / session / audit / group
  2. term / section / course / category / tag / learning path / unlock
  3. module / lesson / attachment / version
  4. question / quiz / attempt / assignment / submission
  5. activity event / completion / grade item
  6. forum / comment / announcement / notification / live session
  7. certificate / badge / points

Quy ước: thời gian lưu dạng naive UTC (``utcnow()``) để so sánh được trên
SQLite và Postgres mà không cần xử lý timezone ở mọi chỗ.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# ---------------------------------------------------------------------------
# Vai trò
# ---------------------------------------------------------------------------

ROLE_ADMIN = "ADMIN"
ROLE_TEACHER = "TEACHER"
ROLE_STUDENT = "STUDENT"
ROLE_GUEST = "GUEST"

ROLE_LABELS = {
    ROLE_ADMIN: "Quản trị viên",
    ROLE_TEACHER: "Giảng viên",
    ROLE_STUDENT: "Sinh viên",
    ROLE_GUEST: "Khách",
}

# Bản API chấm thi dùng "INSTRUCTOR" (theo seed.json của đề bài).
ROLE_ALIASES = {"INSTRUCTOR": ROLE_TEACHER, "TEACHER": ROLE_TEACHER}

USER_STATUS_ACTIVE = "ACTIVE"
USER_STATUS_LOCKED = "LOCKED"
USER_STATUSES = (USER_STATUS_ACTIVE, USER_STATUS_LOCKED)

COURSE_DRAFT = "DRAFT"
COURSE_PUBLISHED = "PUBLISHED"

LESSON_KINDS = ("video", "pdf", "text", "link", "slide")

QUESTION_KINDS = ("MCQ", "TRUE_FALSE", "SHORT")

UNLOCK_LESSON_COMPLETED = "LESSON_COMPLETED"
UNLOCK_QUIZ_PASSED = "QUIZ_PASSED"
UNLOCK_DATE_REACHED = "DATE_REACHED"
UNLOCK_MANUAL = "MANUAL"
UNLOCK_RULE_TYPES = (
    UNLOCK_LESSON_COMPLETED,
    UNLOCK_QUIZ_PASSED,
    UNLOCK_DATE_REACHED,
    UNLOCK_MANUAL,
)


def normalize_role(role: str | None) -> str:
    """Đưa mọi biến thể vai trò về 4 giá trị: ADMIN | TEACHER | STUDENT | GUEST."""
    if not role:
        return ROLE_GUEST
    key = str(role).strip().upper()
    key = ROLE_ALIASES.get(key, key)
    return key if key in ROLE_LABELS else ROLE_GUEST


def utcnow() -> datetime:
    """Thời gian UTC dạng naive để lưu và so sánh thống nhất mọi backend."""
    return datetime.now(UTC).replace(tzinfo=None)


def as_utc(value: datetime | None) -> datetime | None:
    """Chuẩn hoá datetime đọc từ DB (Postgres có thể trả aware)."""
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(UTC).replace(tzinfo=None)
    return value


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(), default=utcnow, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(),
        default=utcnow,
        onupdate=utcnow,
        server_default=func.now(),
        nullable=False,
    )


# ---------------------------------------------------------------------------
# 1. Người dùng
# ---------------------------------------------------------------------------


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), index=True)
    full_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    avatar_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default=USER_STATUS_ACTIVE)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)

    enrollments: Mapped[list[Enrollment]] = relationship(
        back_populates="student",
        foreign_keys="Enrollment.student_id",
        cascade="all, delete-orphan",
    )
    teaching: Mapped[list[Course]] = relationship(
        back_populates="instructor", foreign_keys="Course.instructor_id"
    )

    @property
    def role_label(self) -> str:
        return ROLE_LABELS[normalize_role(self.role)]

    @property
    def initials(self) -> str:
        base = self.full_name or self.email.split("@", 1)[0]
        parts = [p for p in base.replace(".", " ").split() if p]
        if len(parts) >= 2:
            return (parts[0][0] + parts[1][0]).upper()
        return base[:2].upper()

    @property
    def is_locked(self) -> bool:
        return self.status == USER_STATUS_LOCKED


class AuthSession(Base):
    """Phiên đăng nhập để thu hồi được JWT (logout / đổi mật khẩu)."""

    __tablename__ = "auth_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # jti
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)


class AuditEvent(Base):
    """Audit log truy vấn được (thay cho chỉ ghi file)."""

    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_events_actor_ts", "actor_id", "ts"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(), default=utcnow, index=True)
    actor_id: Mapped[str | None] = mapped_column(String(16), nullable=True)
    action: Mapped[str] = mapped_column(String(60))
    resource: Mapped[str] = mapped_column(String(255))
    result: Mapped[str] = mapped_column(String(20))
    detail: Mapped[Any] = mapped_column(JSON, default=dict)


class Group(TimestampMixin, Base):
    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120))
    section_id: Mapped[int | None] = mapped_column(
        ForeignKey("course_sections.id"), nullable=True, index=True
    )


class GroupMember(Base):
    __tablename__ = "group_members"
    __table_args__ = (UniqueConstraint("group_id", "user_id", name="uq_group_member"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))


# ---------------------------------------------------------------------------
# 2. Khoá học: term -> course -> section
# ---------------------------------------------------------------------------


class Term(TimestampMixin, Base):
    __tablename__ = "terms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    starts_on: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    ends_on: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    slug: Mapped[str] = mapped_column(String(140), unique=True)


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(60), unique=True)


class CourseTag(Base):
    __tablename__ = "course_tags"
    __table_args__ = (UniqueConstraint("course_id", "tag_id", name="uq_course_tag"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"))
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id"))


class Course(TimestampMixin, Base):
    __tablename__ = "courses"
    __table_args__ = (CheckConstraint("price >= 0", name="ck_courses_price"),)

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    instructor_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    slug: Mapped[str | None] = mapped_column(String(280), unique=True, nullable=True)
    description: Mapped[str | None] = mapped_column(Text(), nullable=True)
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id"), nullable=True
    )
    price: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(16), default=COURSE_PUBLISHED)
    cover_path: Mapped[str | None] = mapped_column(String(255), nullable=True)

    instructor: Mapped[User] = relationship(
        back_populates="teaching", foreign_keys=[instructor_id]
    )
    enrollments: Mapped[list[Enrollment]] = relationship(
        back_populates="course", cascade="all, delete-orphan"
    )
    sections: Mapped[list[CourseSection]] = relationship(
        back_populates="course", cascade="all, delete-orphan"
    )


class CourseSection(TimestampMixin, Base):
    """Lớp mở của một môn trong một học kỳ."""

    __tablename__ = "course_sections"
    __table_args__ = (
        UniqueConstraint("course_id", "term_id", "code", name="uq_section"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), index=True)
    term_id: Mapped[int | None] = mapped_column(ForeignKey("terms.id"), nullable=True)
    code: Mapped[str] = mapped_column(String(40), default="01")
    capacity: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="OPEN")

    course: Mapped[Course] = relationship(back_populates="sections")
    modules: Mapped[list[Module]] = relationship(
        back_populates="section", cascade="all, delete-orphan"
    )


class Enrollment(TimestampMixin, Base):
    __tablename__ = "enrollments"
    __table_args__ = (
        UniqueConstraint("course_id", "student_id", name="uq_enrollment"),
        CheckConstraint("score >= 0 AND score <= 10", name="ck_enroll_score"),
        Index("ix_enrollments_student", "student_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"))
    section_id: Mapped[int | None] = mapped_column(
        ForeignKey("course_sections.id"), nullable=True, index=True
    )
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    score: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(16), default="APPROVED")

    course: Mapped[Course] = relationship(
        back_populates="enrollments", foreign_keys=[course_id]
    )
    student: Mapped[User] = relationship(
        back_populates="enrollments", foreign_keys=[student_id]
    )


class LearningPath(TimestampMixin, Base):
    __tablename__ = "learning_paths"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(Text(), nullable=True)


class LearningPathItem(Base):
    __tablename__ = "learning_path_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    path_id: Mapped[int] = mapped_column(ForeignKey("learning_paths.id"))
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"))
    position: Mapped[int] = mapped_column(Integer, default=0)


# ---------------------------------------------------------------------------
# 3. Nội dung: module -> lesson -> attachment / version
# ---------------------------------------------------------------------------


class Module(TimestampMixin, Base):
    __tablename__ = "modules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    section_id: Mapped[int] = mapped_column(
        ForeignKey("course_sections.id"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    position: Mapped[int] = mapped_column(Integer, default=0)

    section: Mapped[CourseSection] = relationship(back_populates="modules")
    lessons: Mapped[list[Lesson]] = relationship(
        back_populates="module", cascade="all, delete-orphan"
    )


class Lesson(TimestampMixin, Base):
    __tablename__ = "lessons"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('video', 'pdf', 'text', 'link', 'slide')", name="ck_lessons_kind"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    module_id: Mapped[int] = mapped_column(ForeignKey("modules.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(10), default="text")
    content: Mapped[str | None] = mapped_column(Text(), nullable=True)
    media_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    duration_min: Mapped[int] = mapped_column(Integer, default=0)
    position: Mapped[int] = mapped_column(Integer, default=0)
    is_preview: Mapped[bool] = mapped_column(Boolean, default=False)

    module: Mapped[Module] = relationship(back_populates="lessons")


class Attachment(Base):
    """Thư viện tài nguyên tập trung + file đính kèm bài học."""

    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    lesson_id: Mapped[int | None] = mapped_column(
        ForeignKey("lessons.id"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    stored_name: Mapped[str] = mapped_column(String(200))
    mime: Mapped[str] = mapped_column(String(120))
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)


class LessonVersion(Base):
    __tablename__ = "lesson_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lessons.id"), index=True)
    editor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str | None] = mapped_column(Text(), nullable=True)
    media_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)


class UnlockRule(Base):
    """Điều kiện mở khoá bài học — khai báo, không hard-code."""

    __tablename__ = "unlock_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lessons.id"), index=True)
    rule_type: Mapped[str] = mapped_column(String(24))
    ref_lesson_id: Mapped[int | None] = mapped_column(
        ForeignKey("lessons.id"), nullable=True
    )
    ref_quiz_id: Mapped[int | None] = mapped_column(
        ForeignKey("quizzes.id"), nullable=True
    )
    threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    available_from: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)


# ---------------------------------------------------------------------------
# 4. Kiểm tra & đánh giá
# ---------------------------------------------------------------------------


class Question(TimestampMixin, Base):
    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_id: Mapped[str | None] = mapped_column(
        ForeignKey("courses.id"), nullable=True, index=True
    )
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(16), default="MCQ")
    prompt: Mapped[str] = mapped_column(Text())
    options: Mapped[Any] = mapped_column(JSON, default=list)
    answer: Mapped[Any] = mapped_column(JSON, default=dict)
    points: Mapped[float] = mapped_column(Float, default=1.0)
    tags: Mapped[str | None] = mapped_column(String(200), nullable=True)


class Quiz(TimestampMixin, Base):
    __tablename__ = "quizzes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    section_id: Mapped[int | None] = mapped_column(
        ForeignKey("course_sections.id"), nullable=True, index=True
    )
    lesson_id: Mapped[int | None] = mapped_column(
        ForeignKey("lessons.id"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text(), nullable=True)
    time_limit_min: Mapped[int] = mapped_column(Integer, default=0)
    pass_score: Mapped[float] = mapped_column(Float, default=5.0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default=COURSE_PUBLISHED)


class QuizQuestion(Base):
    __tablename__ = "quiz_questions"
    __table_args__ = (
        UniqueConstraint("quiz_id", "question_id", name="uq_quiz_question"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    quiz_id: Mapped[int] = mapped_column(ForeignKey("quizzes.id"))
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"))
    position: Mapped[int] = mapped_column(Integer, default=0)


class QuizAttempt(Base):
    __tablename__ = "quiz_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    quiz_id: Mapped[int] = mapped_column(ForeignKey("quizzes.id"), index=True)
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    passed: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16), default="IN_PROGRESS")


class QuizAnswer(Base):
    __tablename__ = "quiz_answers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    attempt_id: Mapped[int] = mapped_column(ForeignKey("quiz_attempts.id"), index=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"))
    response: Mapped[Any] = mapped_column(JSON, default=dict)
    is_correct: Mapped[bool] = mapped_column(Boolean, default=False)
    points: Mapped[float] = mapped_column(Float, default=0.0)


class Assignment(TimestampMixin, Base):
    __tablename__ = "assignments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    section_id: Mapped[int] = mapped_column(
        ForeignKey("course_sections.id"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text(), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    max_score: Mapped[float] = mapped_column(Float, default=10.0)
    allow_file: Mapped[bool] = mapped_column(Boolean, default=True)


class Submission(Base):
    __tablename__ = "submissions"
    __table_args__ = (
        UniqueConstraint("assignment_id", "student_id", name="uq_submission"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    assignment_id: Mapped[int] = mapped_column(ForeignKey("assignments.id"))
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    text: Mapped[str | None] = mapped_column(Text(), nullable=True)
    file_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    feedback: Mapped[str | None] = mapped_column(Text(), nullable=True)
    graded_by: Mapped[str | None] = mapped_column(String(16), nullable=True)
    graded_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="SUBMITTED")


# ---------------------------------------------------------------------------
# 5. Tiến độ & báo cáo
# ---------------------------------------------------------------------------


class ActivityEvent(Base):
    """Một bảng sự kiện phục vụ progress, streak, leaderboard, báo cáo."""

    __tablename__ = "activity_events"
    __table_args__ = (Index("ix_activity_user_verb", "user_id", "verb"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(), default=utcnow, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    section_id: Mapped[int | None] = mapped_column(
        ForeignKey("course_sections.id"), nullable=True, index=True
    )
    verb: Mapped[str] = mapped_column(String(40))
    object_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    object_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    payload: Mapped[Any] = mapped_column(JSON, default=dict)


class LessonCompletion(Base):
    __tablename__ = "lesson_completions"
    __table_args__ = (
        UniqueConstraint("lesson_id", "student_id", name="uq_lesson_completion"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lessons.id"), index=True)
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    completed_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)


class GradeItem(TimestampMixin, Base):
    __tablename__ = "grade_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    section_id: Mapped[int] = mapped_column(
        ForeignKey("course_sections.id"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    max_score: Mapped[float] = mapped_column(Float, default=10.0)


class GradeScore(Base):
    __tablename__ = "grade_scores"
    __table_args__ = (
        UniqueConstraint("grade_item_id", "student_id", name="uq_grade_score"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    grade_item_id: Mapped[int] = mapped_column(ForeignKey("grade_items.id"))
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    graded_by: Mapped[str | None] = mapped_column(String(16), nullable=True)


# ---------------------------------------------------------------------------
# 6. Tương tác & cộng đồng
# ---------------------------------------------------------------------------


class ForumTopic(TimestampMixin, Base):
    __tablename__ = "forum_topics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    section_id: Mapped[int] = mapped_column(
        ForeignKey("course_sections.id"), index=True
    )
    author_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text())
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)


class ForumPost(TimestampMixin, Base):
    __tablename__ = "forum_posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("forum_topics.id"), index=True)
    author_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text())


class LessonComment(TimestampMixin, Base):
    __tablename__ = "lesson_comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lessons.id"), index=True)
    author_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text())


class Announcement(TimestampMixin, Base):
    __tablename__ = "announcements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    section_id: Mapped[int] = mapped_column(
        ForeignKey("course_sections.id"), index=True
    )
    author_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text())


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(40), default="INFO")
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str | None] = mapped_column(Text(), nullable=True)
    link: Mapped[str | None] = mapped_column(String(255), nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)


class LiveSession(Base):
    __tablename__ = "live_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    section_id: Mapped[int] = mapped_column(
        ForeignKey("course_sections.id"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    meeting_url: Mapped[str] = mapped_column(String(500))
    start_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    end_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))


# ---------------------------------------------------------------------------
# 7. Chứng chỉ & gamification
# ---------------------------------------------------------------------------


class Certificate(Base):
    __tablename__ = "certificates"
    __table_args__ = (UniqueConstraint("code", name="uq_certificate_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(40), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    section_id: Mapped[int] = mapped_column(ForeignKey("course_sections.id"))
    final_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)


class Badge(Base):
    __tablename__ = "badges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text(), nullable=True)
    icon: Mapped[str | None] = mapped_column(String(40), nullable=True)
    rule: Mapped[Any] = mapped_column(JSON, default=dict)


class UserBadge(Base):
    __tablename__ = "user_badges"
    __table_args__ = (UniqueConstraint("user_id", "badge_id", name="uq_user_badge"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    badge_id: Mapped[int] = mapped_column(ForeignKey("badges.id"))
    awarded_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)


class PointsLedger(Base):
    __tablename__ = "points_ledger"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    points: Mapped[int] = mapped_column(Integer, default=0)
    reason: Mapped[str] = mapped_column(String(120))
    ref_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    ref_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)
