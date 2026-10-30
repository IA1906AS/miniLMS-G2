"""Tầng dữ liệu: engine/session + seed + các query dùng cho giao diện.

Mô hình bảng nằm ở ``web.models`` và được re-export tại đây để mọi module cũ
(``from web.database import User, ROLE_ADMIN, ...``) tiếp tục chạy.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import hash_password
from web.models import (
    ROLE_ADMIN,
    ROLE_ALIASES,
    ROLE_GUEST,
    ROLE_LABELS,
    ROLE_STUDENT,
    ROLE_TEACHER,
    Assignment,
    Badge,
    Base,
    Category,
    Certificate,
    Course,
    CourseSection,
    CourseTag,
    Enrollment,
    GradeItem,
    Group,
    GroupMember,
    LearningPath,
    LearningPathItem,
    Lesson,
    LessonComment,
    LessonCompletion,
    LiveSession,
    Module,
    Notification,
    PointsLedger,
    Question,
    Quiz,
    QuizAttempt,
    QuizQuestion,
    Submission,
    Tag,
    Term,
    User,
    UserBadge,
    normalize_role,
    utcnow,
)

__all__ = [
    "DEFAULT_SEED",
    "ROLE_ADMIN",
    "ROLE_ALIASES",
    "ROLE_GUEST",
    "ROLE_LABELS",
    "ROLE_STUDENT",
    "ROLE_TEACHER",
    "Assignment",
    "Badge",
    "Base",
    "Category",
    "Certificate",
    "Course",
    "CourseSection",
    "CourseTag",
    "Database",
    "Enrollment",
    "GradeItem",
    "Group",
    "GroupMember",
    "LearningPath",
    "LearningPathItem",
    "Lesson",
    "LessonComment",
    "LessonCompletion",
    "LiveSession",
    "Module",
    "Notification",
    "PointsLedger",
    "Question",
    "Quiz",
    "QuizAttempt",
    "QuizQuestion",
    "Submission",
    "Tag",
    "Term",
    "User",
    "UserBadge",
    "course_overview",
    "get_db",
    "normalize_role",
    "platform_stats",
    "student_grades",
    "teaching_courses",
    "utcnow",
]

DEFAULT_SEED = "seed.json"


def _make_engine(url: str) -> Engine:
    if not url.startswith("sqlite"):
        return create_engine(url, future=True)

    connect_args = {"check_same_thread": False}
    if url in {"sqlite://", "sqlite:///:memory:"}:
        # In-memory + StaticPool: nhiều session dùng lại đúng một kết nối.
        return create_engine(url, connect_args=connect_args, poolclass=StaticPool)
    return create_engine(url, connect_args=connect_args)


class Database:
    """Bọc engine + session factory, kèm seed dữ liệu demo."""

    def __init__(self, url: str) -> None:
        self.url = url
        self.engine = _make_engine(url)
        self._session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)

    @contextmanager
    def session(self) -> Iterator[Session]:
        sess = self._session_factory()
        try:
            yield sess
            sess.commit()
        except Exception:
            sess.rollback()
            raise
        finally:
            sess.close()

    def create_all(self) -> None:
        Base.metadata.create_all(self.engine)

    def is_empty(self) -> bool:
        with self.session() as sess:
            return not sess.scalar(select(func.count()).select_from(User))

    # -- seed ---------------------------------------------------------------
    def seed_if_empty(self, seed_path: str | Path = DEFAULT_SEED) -> bool:
        if not self.is_empty():
            return False

        path = Path(seed_path)
        if not path.is_file():
            path = Path(__file__).resolve().parent.parent / str(seed_path)
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))

        with self.session() as sess:
            _seed_users(sess, data)
            _seed_courses(sess, data)
            _seed_enrollments(sess, data)
            _seed_demo_content(sess)
        return True


def _seed_users(sess: Session, data: dict[str, Any]) -> None:
    for user in data.get("users", []):
        sess.add(
            User(
                id=user["id"],
                email=user["email"].strip().lower(),
                role=normalize_role(user["role"]),
                password_hash=hash_password(user["password"]),
                full_name=user.get("fullName") or user["email"].split("@")[0],
            )
        )
    sess.flush()


def _seed_courses(sess: Session, data: dict[str, Any]) -> None:
    term = Term(name="HK1 2026-2027", is_active=True)
    sess.add(term)
    category = Category(name="Công nghệ thông tin", slug="cntt")
    sess.add(category)
    sess.flush()

    for course in data.get("courses", []):
        cid = course["id"]
        sess.add(
            Course(
                id=cid,
                title=course["title"],
                instructor_id=course["instructorId"],
                slug=cid,
                description=f"Môn {course['title']} — lớp mở trong {term.name}.",
                category_id=category.id,
                price=0.0,
                status="PUBLISHED",
            )
        )
        sess.flush()
        sess.add(
            CourseSection(
                course_id=cid,
                term_id=term.id,
                code="01",
                capacity=40,
                status="OPEN",
            )
        )
    sess.flush()


def _seed_enrollments(sess: Session, data: dict[str, Any]) -> None:
    sections = {s.course_id: s.id for s in sess.scalars(select(CourseSection)).all()}
    for row in data.get("enrollments", []):
        sess.add(
            Enrollment(
                course_id=row["courseId"],
                section_id=sections.get(row["courseId"]),
                student_id=row["studentId"],
                score=float(row["score"]),
                status="APPROVED",
            )
        )
    sess.flush()


def _seed_demo_content(sess: Session) -> None:
    """Nội dung mẫu: module + bài học + quiz + badge để giao diện có dữ liệu."""
    sections = sess.scalars(select(CourseSection).order_by(CourseSection.id)).all()
    teacher = sess.scalars(select(User).where(User.role == ROLE_TEACHER)).first()
    teacher_id = teacher.id if teacher else "u2"

    for index, section in enumerate(sections, start=1):
        module = Module(
            section_id=section.id, title=f"Chương {index}: Nhập môn", position=1
        )
        sess.add(module)
        sess.flush()

        lessons = [
            Lesson(
                module_id=module.id,
                title="Giới thiệu môn học",
                kind="text",
                content="Nội dung bài giới thiệu (có thể soạn rich-text).",
                duration_min=10,
                position=1,
                is_preview=True,
            ),
            Lesson(
                module_id=module.id,
                title="Bài giảng video",
                kind="video",
                media_url="https://example.com/video.mp4",
                duration_min=25,
                position=2,
            ),
            Lesson(
                module_id=module.id,
                title="Tài liệu PDF",
                kind="pdf",
                media_url="https://example.com/slide.pdf",
                duration_min=15,
                position=3,
            ),
        ]
        sess.add_all(lessons)
        sess.flush()

        question = Question(
            course_id=section.course_id,
            created_by=teacher_id,
            kind="MCQ",
            prompt="HTTP status nào là 403?",
            options=["200", "403", "404", "500"],
            answer={"index": 1},
            points=2.0,
            tags="web,http",
        )
        sess.add(question)
        sess.flush()

        quiz = Quiz(
            section_id=section.id,
            lesson_id=lessons[0].id,
            title=f"Quiz chương {index}",
            time_limit_min=15,
            pass_score=5.0,
            max_attempts=3,
        )
        sess.add(quiz)
        sess.flush()
        sess.add(QuizQuestion(quiz_id=quiz.id, question_id=question.id, position=1))
        sess.add(
            GradeItem(
                section_id=section.id, name="Quiz chương 1", weight=1.0, max_score=10.0
            )
        )

    sess.add_all(
        [
            Badge(
                code="first_lesson",
                name="Bước đầu tiên",
                description="Hoàn thành bài học đầu tiên",
                icon="🌱",
                rule={"type": "LESSON_COMPLETED", "count": 1},
            ),
            Badge(
                code="quiz_master",
                name="Cao thủ quiz",
                description="Đạt điểm tuyệt đối một quiz",
                icon="🎯",
                rule={"type": "QUIZ_PASSED", "count": 1},
            ),
            Badge(
                code="streak_3",
                name="Chuỗi 3 ngày",
                description="Học 3 ngày liên tiếp",
                icon="🔥",
                rule={"type": "STREAK", "count": 3},
            ),
        ]
    )
    sess.flush()


def get_db() -> Database:
    from flask import current_app

    db: Database = current_app.extensions["lms_db"]
    return db


# ---------------------------------------------------------------------------
# Query dùng bởi các trang hiện có
# ---------------------------------------------------------------------------


def course_overview(sess: Session) -> list[dict[str, Any]]:
    """Mọi môn học kèm giảng viên, sĩ số và điểm trung bình."""
    rows = sess.execute(
        select(
            Course.id,
            Course.title,
            User.email,
            User.id,
            func.count(Enrollment.id),
            func.avg(Enrollment.score),
            Course.price,
            Course.status,
        )
        .join(User, Course.instructor_id == User.id)
        .outerjoin(Enrollment, Enrollment.course_id == Course.id)
        .group_by(
            Course.id, Course.title, User.email, User.id, Course.price, Course.status
        )
        .order_by(Course.id)
    ).all()

    return [
        {
            "id": row[0],
            "title": row[1],
            "instructor_email": row[2],
            "instructor_id": row[3],
            "students": row[4],
            "avg_score": round(row[5], 2) if row[5] is not None else None,
            "price": row[6],
            "status": row[7],
        }
        for row in rows
    ]


def student_grades(sess: Session, student_id: str) -> list[dict[str, Any]]:
    rows = sess.execute(
        select(Course.id, Course.title, Enrollment.score, User.email)
        .join(Enrollment, Enrollment.course_id == Course.id)
        .join(User, Course.instructor_id == User.id)
        .where(Enrollment.student_id == student_id)
        .order_by(Course.id)
    ).all()
    return [
        {"id": row[0], "title": row[1], "score": row[2], "instructor_email": row[3]}
        for row in rows
    ]


def teaching_courses(sess: Session, instructor_id: str) -> list[dict[str, Any]]:
    return [
        card for card in course_overview(sess) if card["instructor_id"] == instructor_id
    ]


def platform_stats(sess: Session) -> dict[str, int]:
    return {
        "users": sess.scalar(select(func.count()).select_from(User)) or 0,
        "students": sess.scalar(
            select(func.count()).select_from(User).where(User.role == ROLE_STUDENT)
        )
        or 0,
        "teachers": sess.scalar(
            select(func.count())
            .select_from(User)
            .where(User.role.in_([ROLE_TEACHER, "INSTRUCTOR"]))
        )
        or 0,
        "courses": sess.scalar(select(func.count()).select_from(Course)) or 0,
        "enrollments": sess.scalar(select(func.count()).select_from(Enrollment)) or 0,
    }
