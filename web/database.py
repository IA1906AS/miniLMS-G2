"""Lớp truy cập dữ liệu cho giao diện web LMS: SQLite + SQLAlchemy 2.x.

Tách khỏi ``app/`` (bản API chấm thi vẫn chạy in-memory theo yêu cầu đề bài).
Dùng chung seed.json để dữ liệu hai bên giống nhau.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import (
    Float,
    ForeignKey,
    String,
    UniqueConstraint,
    create_engine,
    func,
    select,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    relationship,
    sessionmaker,
)
from sqlalchemy.pool import StaticPool

from app.auth import hash_password

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

# Bản API chấm thi dùng "INSTRUCTOR" (theo seed.json của đề bài), giao diện web
# dùng "TEACHER". Quy đổi tại biên để hai bên không lệch nhau.
ROLE_ALIASES = {"INSTRUCTOR": ROLE_TEACHER, "TEACHER": ROLE_TEACHER}


def normalize_role(role: str | None) -> str:
    """Đưa mọi biến thể vai trò về 4 giá trị: ADMIN | TEACHER | STUDENT | GUEST."""
    if not role:
        return ROLE_GUEST
    key = str(role).strip().upper()
    key = ROLE_ALIASES.get(key, key)
    return key if key in ROLE_LABELS else ROLE_GUEST


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20))

    enrollments: Mapped[list[Enrollment]] = relationship(
        back_populates="student",
        foreign_keys="Enrollment.student_id",
        cascade="all, delete-orphan",
    )
    teaching: Mapped[list[Course]] = relationship(back_populates="instructor")

    @property
    def role_label(self) -> str:
        return ROLE_LABELS[normalize_role(self.role)]

    @property
    def initials(self) -> str:
        return self.email.split("@", 1)[0][:2].upper()


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    instructor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))

    instructor: Mapped[User] = relationship(
        back_populates="teaching", foreign_keys=[instructor_id]
    )
    enrollments: Mapped[list[Enrollment]] = relationship(
        back_populates="course", cascade="all, delete-orphan"
    )


class Enrollment(Base):
    __tablename__ = "enrollments"
    __table_args__ = (
        UniqueConstraint("course_id", "student_id", name="uq_enrollment"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"))
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    score: Mapped[float] = mapped_column(Float, default=0.0)

    course: Mapped[Course] = relationship(
        back_populates="enrollments", foreign_keys=[course_id]
    )
    student: Mapped[User] = relationship(
        back_populates="enrollments", foreign_keys=[student_id]
    )


def _make_engine(url: str) -> Engine:
    if not url.startswith("sqlite"):
        return create_engine(url, future=True)

    connect_args = {"check_same_thread": False}
    if url in {"sqlite://", "sqlite:///:memory:"}:
        # In-memory + StaticPool: nhiều session dùng lại đúng một kết nối.
        return create_engine(url, connect_args=connect_args, poolclass=StaticPool)
    return create_engine(url, connect_args=connect_args)


class Database:
    """Bọc engine + session factory, kèm seed từ seed.json."""

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

    def seed_if_empty(self, seed_path: str | Path) -> bool:
        """Nạp seed.json khi bảng users còn trống. Trả True nếu có nạp."""
        if not self.is_empty():
            return False

        path = Path(seed_path)
        if not path.is_file():
            path = Path(__file__).resolve().parent.parent / str(seed_path)
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))

        with self.session() as sess:
            for user in data.get("users", []):
                sess.add(
                    User(
                        id=user["id"],
                        email=user["email"].strip().lower(),
                        role=normalize_role(user["role"]),
                        password_hash=hash_password(user["password"]),
                    )
                )
            sess.flush()
            for course in data.get("courses", []):
                sess.add(
                    Course(
                        id=course["id"],
                        title=course["title"],
                        instructor_id=course["instructorId"],
                    )
                )
            sess.flush()
            for row in data.get("enrollments", []):
                sess.add(
                    Enrollment(
                        course_id=row["courseId"],
                        student_id=row["studentId"],
                        score=float(row["score"]),
                    )
                )
        return True


def get_db() -> Database:
    from flask import current_app

    db: Database = current_app.extensions["lms_db"]
    return db


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
        )
        .join(User, Course.instructor_id == User.id)
        .outerjoin(Enrollment, Enrollment.course_id == Course.id)
        .group_by(Course.id, Course.title, User.email, User.id)
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
