"""Mô hình dữ liệu cho miniLMS — bám theo ``lms_spec.md``.

Vai trò dùng đúng enum của spec: ``ADMIN | INSTRUCTOR | STUDENT | GUEST``.

Nhóm bảng:
  1. Người dùng / phiên / audit
  2. Danh mục, khoá học, chương, bài học, tài liệu
  3. Ghi danh, tiến độ
  4. Quiz, ngân hàng câu hỏi, bài tập, bài nộp, điểm
  5. Diễn đàn, thông báo, tin nhắn, live session
  6. Chứng chỉ, huy hiệu
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
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
# Vai trò — đúng như spec mục "Ghi chú kỹ thuật", dòng 2
# ---------------------------------------------------------------------------

ROLE_ADMIN = "ADMIN"
ROLE_INSTRUCTOR = "INSTRUCTOR"
ROLE_STUDENT = "STUDENT"
ROLE_GUEST = "GUEST"

ROLE_LABELS = {
    ROLE_ADMIN: "Quản trị viên",
    ROLE_INSTRUCTOR: "Giảng viên",
    ROLE_STUDENT: "Sinh viên",
    ROLE_GUEST: "Khách",
}

#: Bí danh cũ (TEACHER) để dữ liệu/seed cũ vẫn đọc được.
ROLE_ALIASES = {"TEACHER": ROLE_INSTRUCTOR, "GV": ROLE_INSTRUCTOR}

USER_STATUS_ACTIVE = "ACTIVE"
USER_STATUS_LOCKED = "LOCKED"

COURSE_DRAFT = "DRAFT"
COURSE_PUBLISHED = "PUBLISHED"
COURSE_HIDDEN = "HIDDEN"

ENROLL_ACTIVE = "ACTIVE"
ENROLL_PENDING = "PENDING"
ENROLL_COMPLETED = "COMPLETED"

LESSON_KINDS = ("video", "pdf", "text", "slide", "link")


def normalize_role(role: str | None) -> str:
    """Đưa mọi biến thể vai trò về 4 giá trị chuẩn của spec."""
    if not role:
        return ROLE_GUEST
    key = str(role).strip().upper()
    key = ROLE_ALIASES.get(key, key)
    return key if key in ROLE_LABELS else ROLE_GUEST


def utcnow() -> datetime:
    """Thời gian UTC naive — so sánh được trên mọi backend."""
    return datetime.now(UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow, onupdate=utcnow, server_default=func.now())


# ---------------------------------------------------------------------------
# 1. Người dùng
# ---------------------------------------------------------------------------


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), index=True, default=ROLE_STUDENT)
    full_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    bio: Mapped[str | None] = mapped_column(Text(), nullable=True)
    avatar_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default=USER_STATUS_ACTIVE)
    email_notifications: Mapped[bool] = mapped_column(Boolean, default=True)

    courses: Mapped[list[Course]] = relationship(back_populates="instructor", foreign_keys="Course.instructor_id")

    @property
    def role_label(self) -> str:
        return ROLE_LABELS[normalize_role(self.role)]

    @property
    def is_locked(self) -> bool:
        return self.status == USER_STATUS_LOCKED

    @property
    def display_name(self) -> str:
        return self.full_name or self.email.split("@", 1)[0]


class AuthSession(Base):
    """Phiên đăng nhập để thu hồi được JWT."""

    __tablename__ = "auth_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # jti
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(), default=utcnow, index=True)
    actor_id: Mapped[str | None] = mapped_column(String(16), nullable=True)
    action: Mapped[str] = mapped_column(String(60))
    resource: Mapped[str] = mapped_column(String(255))
    detail: Mapped[Any] = mapped_column(JSON, default=dict)


class PasswordResetToken(Base):
    """Token khôi phục mật khẩu gửi qua email (spec mục 1)."""

    __tablename__ = "password_reset_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime())
    used_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)


# ---------------------------------------------------------------------------
# 2. Danh mục, khoá học, nội dung
# ---------------------------------------------------------------------------


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

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    instructor_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    slug: Mapped[str | None] = mapped_column(String(280), unique=True, nullable=True)
    description: Mapped[str | None] = mapped_column(Text(), nullable=True)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"), nullable=True)
    price: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(16), default=COURSE_DRAFT)
    cover_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    #: Mã ghi danh công khai (spec mục 3: "ghi danh bằng mã khoá học").
    enroll_code: Mapped[str | None] = mapped_column(String(20), unique=True, nullable=True, index=True)
    #: Spec dòng 46: "/leaderboard — Bảng xếp hạng (nếu công khai)".
    leaderboard_public: Mapped[bool] = mapped_column(Boolean, default=False)

    instructor: Mapped[User] = relationship(back_populates="courses", foreign_keys=[instructor_id])
    chapters: Mapped[list[Chapter]] = relationship(back_populates="course", cascade="all, delete-orphan")
    enrollments: Mapped[list[Enrollment]] = relationship(back_populates="course", cascade="all, delete-orphan")

    @property
    def is_public(self) -> bool:
        return self.status == COURSE_PUBLISHED


class Chapter(TimestampMixin, Base):
    """Chương trong cấu trúc khoá học (spec: /instructor/courses/:id/curriculum)."""

    __tablename__ = "chapters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    position: Mapped[int] = mapped_column(Integer, default=0)

    course: Mapped[Course] = relationship(back_populates="chapters")
    lessons: Mapped[list[Lesson]] = relationship(back_populates="chapter", cascade="all, delete-orphan")


class Lesson(TimestampMixin, Base):
    __tablename__ = "lessons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chapter_id: Mapped[int] = mapped_column(ForeignKey("chapters.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(10), default="text")
    content: Mapped[str | None] = mapped_column(Text(), nullable=True)
    media_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    duration_min: Mapped[int] = mapped_column(Integer, default=0)
    position: Mapped[int] = mapped_column(Integer, default=0)
    #: Spec dòng 149: bài có flag này thì GUEST xem được.
    is_free_preview: Mapped[bool] = mapped_column(Boolean, default=False)

    chapter: Mapped[Chapter] = relationship(back_populates="lessons")
    attachments: Mapped[list[Attachment]] = relationship(back_populates="lesson", cascade="all, delete-orphan")


class Attachment(Base):
    """Tài liệu đính kèm bài học / thư viện tài nguyên."""

    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    lesson_id: Mapped[int | None] = mapped_column(ForeignKey("lessons.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(200))
    stored_name: Mapped[str] = mapped_column(String(200))
    mime: Mapped[str] = mapped_column(String(120))
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)

    lesson: Mapped[Lesson | None] = relationship(back_populates="attachments")


# ---------------------------------------------------------------------------
# 3. Ghi danh & tiến độ
# ---------------------------------------------------------------------------


class Enrollment(TimestampMixin, Base):
    __tablename__ = "enrollments"
    __table_args__ = (UniqueConstraint("course_id", "student_id", name="uq_enrollment"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), index=True)
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default=ENROLL_ACTIVE)

    course: Mapped[Course] = relationship(back_populates="enrollments")
    student: Mapped[User] = relationship(foreign_keys=[student_id])


class LessonProgress(Base):
    __tablename__ = "lesson_progress"
    __table_args__ = (UniqueConstraint("lesson_id", "student_id", name="uq_lesson_progress"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lessons.id"), index=True)
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    completed_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)


class ActivityEvent(Base):
    """Một bảng sự kiện dùng cho progress, streak, leaderboard, báo cáo."""

    __tablename__ = "activity_events"
    __table_args__ = (Index("ix_activity_user_verb", "user_id", "verb"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(), default=utcnow, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    course_id: Mapped[str | None] = mapped_column(ForeignKey("courses.id"), nullable=True, index=True)
    verb: Mapped[str] = mapped_column(String(40))
    object_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    object_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    payload: Mapped[Any] = mapped_column(JSON, default=dict)


# ---------------------------------------------------------------------------
# 4. Quiz, bài tập, điểm
# ---------------------------------------------------------------------------


class Question(TimestampMixin, Base):
    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_id: Mapped[str | None] = mapped_column(ForeignKey("courses.id"), nullable=True, index=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(16), default="MCQ")
    prompt: Mapped[str] = mapped_column(Text())
    options: Mapped[Any] = mapped_column(JSON, default=list)
    answer: Mapped[Any] = mapped_column(JSON, default=dict)
    points: Mapped[float] = mapped_column(Float, default=1.0)


class Quiz(TimestampMixin, Base):
    __tablename__ = "quizzes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text(), nullable=True)
    time_limit_min: Mapped[int] = mapped_column(Integer, default=0)
    pass_score: Mapped[float] = mapped_column(Float, default=5.0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=0)
    #: Spec dòng 41: chỉ hiện đáp án sau khi nộp "nếu GV cho phép".
    show_answers: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16), default=COURSE_PUBLISHED)


class QuizQuestion(Base):
    __tablename__ = "quiz_questions"
    __table_args__ = (UniqueConstraint("quiz_id", "question_id", name="uq_quiz_question"),)

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
    # V01 — Optimistic Locking:
    # Client đọc version này, gửi lại khi sửa điểm. Service chỉ UPDATE khi
    # version còn khớp; lệch version => 409, không ghi đè (xem grade_service.py).
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


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
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text(), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    max_score: Mapped[float] = mapped_column(Float, default=10.0)


class Submission(Base):
    __tablename__ = "submissions"
    __table_args__ = (UniqueConstraint("assignment_id", "student_id", name="uq_submission"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    assignment_id: Mapped[int] = mapped_column(ForeignKey("assignments.id"))
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    text: Mapped[str | None] = mapped_column(Text(), nullable=True)
    file_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    feedback: Mapped[str | None] = mapped_column(Text(), nullable=True)
    graded_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    # V01 — Optimistic Locking:
    # Form chấm bài gửi kèm version. Service UPDATE có điều kiện version,
    # rowcount = 0 nghĩa là đã có người sửa trước => 409 Conflict.
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


# ---------------------------------------------------------------------------
# 5. Diễn đàn, thông báo, tin nhắn, live
# ---------------------------------------------------------------------------


class ForumTopic(TimestampMixin, Base):
    __tablename__ = "forum_topics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), index=True)
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


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    #: Người gửi (GV/Admin) và khoá học liên quan — spec mục 6.
    sender_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    course_id: Mapped[str | None] = mapped_column(ForeignKey("courses.id"), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(40), default="INFO")
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str | None] = mapped_column(Text(), nullable=True)
    link: Mapped[str | None] = mapped_column(String(255), nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow, index=True)


class DirectMessage(Base):
    __tablename__ = "direct_messages"
    __table_args__ = (Index("ix_dm_pair", "sender_id", "recipient_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sender_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    recipient_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    body: Mapped[str] = mapped_column(Text())
    read_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow, index=True)


class LiveSession(Base):
    __tablename__ = "live_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    meeting_url: Mapped[str] = mapped_column(String(500))
    start_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    end_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))


# ---------------------------------------------------------------------------
# 6. Chứng chỉ & huy hiệu
# ---------------------------------------------------------------------------


class Certificate(Base):
    __tablename__ = "certificates"
    __table_args__ = (UniqueConstraint("code", name="uq_certificate_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(40), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"))
    final_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)


class Badge(Base):
    __tablename__ = "badges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text(), nullable=True)
    icon: Mapped[str | None] = mapped_column(String(40), nullable=True)
    #: {"type": "LESSON_COMPLETED", "count": 1} — spec: "gán điều kiện nhận huy hiệu"
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
    ref_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)


# ---------------------------------------------------------------------------
# 7. Cài đặt hệ thống (spec: /admin/settings)
# ---------------------------------------------------------------------------


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text(), nullable=True)


# ---------------------------------------------------------------------------
# 8. Idempotency Key — Defensive Pattern #2 (spec: nộp bài tập)
# ---------------------------------------------------------------------------

#: Trạng thái khoá idempotency đang được xử lý — chống race condition song song.
IDEM_PENDING = "PENDING"
#: Trạng thái khoá idempotency đã hoàn thành — phục vụ replay an toàn.
IDEM_COMPLETED = "COMPLETED"
#: Trạng thái khoá idempotency thất bại — cho phép thử lại.
IDEM_FAILED = "FAILED"


class IdempotencyKey(Base):
    """Lưu trữ khoá idempotency cho nghiệp vụ nộp bài tập.

    Luồng:
      1. Request đến → chèn bản ghi trạng thái PENDING (atomic INSERT).
      2. Nếu chèn bị khoá (UNIQUE conflict) → đọc bản ghi hiện có.
         - Nếu PENDING  → 409 Conflict (đang xử lý song song).
         - Nếu COMPLETED và hash khớp → replay phản hồi cũ (I01 fix).
         - Nếu COMPLETED nhưng hash khác → 422 Payload Mismatch.
         - Nếu FAILED → cho phép retry.
      3. Sau khi xử lý xong → cập nhật COMPLETED + lưu redirect target.
    """

    __tablename__ = "idempotency_keys"
    __table_args__ = (
        UniqueConstraint("idem_key", "student_id", name="uq_idem_key_student"),
        Index("ix_idem_expires", "expires_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    #: Giá trị key do client cung cấp (UUID v4 hoặc chuỗi ngẫu nhiên).
    idem_key: Mapped[str] = mapped_column(String(128), nullable=False)
    #: Sinh viên sở hữu key này — ngăn key của người khác bị dùng chung.
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    #: Định danh nghiệp vụ, ví dụ "assignment:5:submit".
    resource: Mapped[str] = mapped_column(String(200), nullable=False)
    #: SHA-256 của payload (text + nội dung file) để phát hiện payload mismatch (I03).
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    #: Trạng thái xử lý: PENDING | COMPLETED | FAILED.
    status: Mapped[str] = mapped_column(String(16), default=IDEM_PENDING, nullable=False)
    #: HTTP redirect location khi replay (ví dụ: "/assignments/5").
    response_location: Mapped[str | None] = mapped_column(String(500), nullable=True)
    #: Thời điểm tạo key.
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow, nullable=False)
    #: Thời điểm hoàn thành (COMPLETED/FAILED).
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    #: Hạn sống của key — sau thời điểm này key có thể bị xoá (mặc định 24 giờ).
    expires_at: Mapped[datetime] = mapped_column(DateTime(), nullable=False)
