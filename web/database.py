"""Tầng dữ liệu: engine, session, seed demo.

Mô hình bảng nằm ở ``web.models``. Module này chỉ lo kết nối + nạp dữ liệu mẫu
từ ``seed.json`` và mở rộng thêm dữ liệu để mọi trang trong spec có nội dung.
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
    ROLE_INSTRUCTOR,
    ROLE_LABELS,
    ROLE_STUDENT,
    COURSE_DRAFT,
    COURSE_PUBLISHED,
    COURSE_HIDDEN,
    ENROLL_ACTIVE,
    ENROLL_COMPLETED,
    ENROLL_PENDING,
    Assignment,
    Badge,
    Base,
    Category,
    Certificate,
    Chapter,
    Course,
    CourseTag,
    Enrollment,
    ForumPost,
    ForumTopic,
    Lesson,
    LiveSession,
    Notification,
    Question,
    Quiz,
    QuizQuestion,
    Tag,
    User,
    normalize_role,
)

#: Bí danh tương thích ngược cho code/test cũ dùng tên khác.
ROLE_TEACHER = ROLE_INSTRUCTOR

__all__ = [
    "DEFAULT_SEED",
    "Database",
    "ROLE_ADMIN",
    "ROLE_ALIASES",
    "ROLE_GUEST",
    "ROLE_INSTRUCTOR",
    "ROLE_LABELS",
    "ROLE_STUDENT",
    "ROLE_TEACHER",
    "User",
    "get_db",
    "normalize_role",
]

DEFAULT_SEED = "seed.json"


def _make_engine(url: str) -> Engine:
    if not url.startswith("sqlite"):
        return create_engine(url, future=True)
    connect_args = {"check_same_thread": False}
    if url in {"sqlite://", "sqlite:///:memory:"}:
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

    def seed_if_empty(self, seed_path: str | Path = DEFAULT_SEED) -> bool:
        if not self.is_empty():
            return False

        path = Path(seed_path)
        if not path.is_file():
            path = Path(__file__).resolve().parent.parent / str(seed_path)
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))

        with self.session() as sess:
            _seed_users(sess, data)
            _seed_taxonomy(sess, data)
            _seed_courses(sess, data)
            _seed_enrollments(sess, data)
            _seed_content(sess, data)
            _seed_assessments(sess, data)
            _seed_community(sess)
            _seed_rewards(sess)
        return True


# ---------------------------------------------------------------------------
# Seed
# ---------------------------------------------------------------------------


def _seed_users(sess: Session, data: dict[str, Any]) -> None:
    for user in data.get("users", []):
        sess.add(
            User(
                id=user["id"],
                email=user["email"].strip().lower(),
                role=normalize_role(user["role"]),
                password_hash=hash_password(user["password"]),
                full_name=user.get("full_name") or user.get("fullName") or user["email"].split("@")[0],
                bio=(
                    "Giảng viên bộ môn."
                    if normalize_role(user["role"]) == ROLE_INSTRUCTOR
                    else None
                ),
            )
        )
    sess.flush()


def _seed_taxonomy(sess: Session, data: dict[str, Any] | None = None) -> None:
    import re
    def make_slug(text: str) -> str:
        text = text.lower().strip()
        text = re.sub(r'[àáạảãâầấậẩẫăằắặẳẵ]', 'a', text)
        text = re.sub(r'[èéẹẻẽêềếệểễ]', 'e', text)
        text = re.sub(r'[ìíịỉĩ]', 'i', text)
        text = re.sub(r'[òóọỏõôồốộổỗơờớợởỡ]', 'o', text)
        text = re.sub(r'[ùúụủũưừứựửữ]', 'u', text)
        text = re.sub(r'[ỳýỵỷỹ]', 'y', text)
        text = re.sub(r'[đ]', 'd', text)
        text = re.sub(r'[^a-z0-9]+', '-', text)
        return text.strip('-')

    if data and "categories" in data:
        for cat in data["categories"]:
            slug = cat.get("slug") or make_slug(cat["name"])
            sess.add(Category(id=cat["id"], name=cat["name"], slug=slug))
    else:
        for name, slug in (
            ("Công nghệ thông tin", "cntt"),
            ("Khoa học dữ liệu", "khdl"),
            ("Thiết kế", "thiet-ke"),
        ):
            sess.add(Category(name=name, slug=slug))
    if data and "tags" in data:
        for tag in data["tags"]:
            sess.add(Tag(name=tag))
    else:
        for tag in ("web", "python", "sql", "cơ bản", "nâng cao"):
            sess.add(Tag(name=tag))
    sess.flush()


def _seed_courses(sess: Session, data: dict[str, Any]) -> None:
    for course in data.get("courses", []):
        cid = course["id"]
        sess.add(
            Course(
                id=cid,
                title=course["title"],
                instructor_id=course["instructorId"],
                slug=cid,
                description=course.get("description"),
                price=course.get("price", 0),
                status=course.get("status", COURSE_PUBLISHED),
                category_id=course.get("categoryId"),
                leaderboard_public=True,
                enroll_code=course.get("enrollCode") or f"{cid.upper()}-2026",
            )
        )
    sess.flush()


def _seed_enrollments(sess: Session, data: dict[str, Any]) -> None:
    for row in data.get("enrollments", []):
        sess.add(
            Enrollment(
                course_id=row["courseId"],
                student_id=row["studentId"],
                status="ACTIVE",
            )
        )
    sess.flush()


def _seed_content(sess: Session, data: dict[str, Any] | None = None) -> None:
    """Seed chapters and lessons from seed.json if available, else generate defaults."""
    if data and "chapters" in data and "lessons" in data:
        for chapter in data["chapters"]:
            sess.add(Chapter(
                id=chapter["id"],
                course_id=chapter["courseId"],
                title=chapter["title"],
                position=chapter.get("position", 1),
            ))
        for lesson in data["lessons"]:
            sess.add(Lesson(
                id=lesson["id"],
                chapter_id=lesson["chapterId"],
                title=lesson["title"],
                kind=lesson.get("kind", "text"),
                position=lesson.get("position", 1),
                duration_min=lesson.get("duration_min", 0),
                content=lesson.get("content"),
                media_url=lesson.get("media_url"),
                is_free_preview=lesson.get("is_free_preview", False),
            ))
    else:
        # Default content generation
        for course in sess.scalars(select(Course).order_by(Course.id)).all():
            for chapter_index, chapter_title in enumerate(
                ("Nhập môn", "Thực hành"), start=1
            ):
                chapter = Chapter(
                course_id=course.id,
                title=f"Chương {chapter_index}: {chapter_title}",
                position=chapter_index,
            )
            sess.add(chapter)
            sess.flush()

            lessons = [
                Lesson(
                    chapter_id=chapter.id,
                    title=f"Bài {chapter_index}.1 — Giới thiệu",
                    kind="text",
                    content="Nội dung bài giới thiệu (soạn thảo văn bản).",
                    duration_min=10,
                    position=1,
                    is_free_preview=(chapter_index == 1),
                ),
                Lesson(
                    chapter_id=chapter.id,
                    title=f"Bài {chapter_index}.2 — Video bài giảng",
                    kind="video",
                    media_url="https://example.com/lecture.mp4",
                    duration_min=25,
                    position=2,
                ),
                Lesson(
                    chapter_id=chapter.id,
                    title=f"Bài {chapter_index}.3 — Tài liệu PDF",
                    kind="pdf",
                    media_url="https://example.com/slides.pdf",
                    duration_min=15,
                    position=3,
                ),
            ]
            sess.add_all(lessons)
            sess.flush()

            sess.add(
                Question(
                    course_id=course.id,
                    created_by=teacher_id,
                    kind="MCQ",
                    prompt="HTTP status nào biểu thị Forbidden?",
                    options=["200", "403", "404", "500"],
                    answer={"index": 1},
                    points=2.0,
                )
            )
    sess.flush()


def _seed_assessments(sess: Session, data: dict[str, Any] | None = None) -> None:
    if data and "quizzes" in data and "questions" in data and "assignments" in data:
        for quiz in data["quizzes"]:
            sess.add(Quiz(
                id=quiz["id"],
                course_id=quiz["courseId"],
                title=quiz["title"],
                description=quiz.get("description"),
                time_limit_min=quiz.get("time_limit_min", 15),
                pass_score=quiz.get("pass_score", 5.0),
                max_attempts=quiz.get("max_attempts", 3),
                show_answers=quiz.get("show_answers", True),
                status=quiz.get("status", "PUBLISHED"),
            ))
        sess.flush()

        for question in data["questions"]:
            sess.add(Question(
                id=question["id"],
                course_id=question.get("courseId"),
                created_by=question.get("createdBy") or "u2",
                kind=question.get("kind", "MCQ"),
                prompt=question["prompt"],
                options=question.get("options", []),
                answer=question.get("answer", {"index": 0}),
                points=question.get("points", 1),
            ))
            # Link question to quiz via QuizQuestion
            quiz_id = question.get("quizId")
            if quiz_id:
                sess.add(QuizQuestion(quiz_id=quiz_id, question_id=question["id"], position=1))

        for assignment in data["assignments"]:
            due_at = assignment.get("due_at")
            if isinstance(due_at, str):
                from datetime import datetime
                for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
                    try:
                        due_at = datetime.strptime(due_at, fmt)
                        break
                    except ValueError:
                        continue
            else:
                due_at = None

            sess.add(Assignment(
                id=assignment["id"],
                course_id=assignment["courseId"],
                title=assignment["title"],
                description=assignment.get("description"),
                max_score=assignment.get("max_score", 10),
                due_at=due_at,
            ))
    else:
        # Default assessments
        for index, course in enumerate(
            sess.scalars(select(Course).order_by(Course.id)).all(), start=1
        ):
            quiz = Quiz(
                course_id=course.id,
                title=f"Kiểm tra chương {index}",
                description="Bài kiểm tra trắc nghiệm cuối chương.",
                time_limit_min=15,
                pass_score=5.0,
                max_attempts=3,
                show_answers=True,
                status="PUBLISHED",
            )
            sess.add(quiz)
            sess.flush()

            question = sess.scalars(
                select(Question).where(Question.course_id == course.id)
            ).first()
            if question is not None:
                sess.add(
                    QuizQuestion(quiz_id=quiz.id, question_id=question.id, position=1)
                )

            sess.add(
                Assignment(
                    course_id=course.id,
                    title=f"Bài tập chương {index}",
                    description="Nộp bài làm dạng văn bản hoặc tệp đính kèm.",
                    max_score=10.0,
                )
            )
    sess.flush()


def _seed_community(sess: Session) -> None:
    student = sess.scalars(select(User).where(User.role == ROLE_STUDENT)).first()
    instructor = sess.scalars(select(User).where(User.role == ROLE_INSTRUCTOR)).first()
    if student is None or instructor is None:
        return

    for course in sess.scalars(select(Course).order_by(Course.id)).all():
        topic = ForumTopic(
            course_id=course.id,
            author_id=instructor.id,
            title=f"Hỏi đáp khoá {course.title}",
            body="Mọi thắc mắc về bài giảng, bài tập đăng tại đây.",
            pinned=True,
        )
        sess.add(topic)
        sess.flush()
        sess.add(
            ForumPost(
                topic_id=topic.id,
                author_id=student.id,
                body="Em chào thầy/cô, em đã xem xong chương 1 ạ.",
            )
        )
        sess.add(
            LiveSession(
                course_id=course.id,
                title=f"Live ôn tập {course.title}",
                meeting_url="https://meet.example.com/lms",
                created_by=instructor.id,
            )
        )
        sess.add(
            Notification(
                user_id=student.id,
                kind="INFO",
                title=f"Khoá {course.title} đã cập nhật nội dung",
                body="Chương 2 đã được mở.",
                link=f"/my-courses/{course.id}/learn",
            )
        )
    sess.flush()


def _seed_rewards(sess: Session) -> None:
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
                description="Đạt một bài kiểm tra",
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

    for enrollment in sess.scalars(select(Enrollment)).all():
        sess.add(
            Certificate(
                code=f"CERT-{enrollment.course_id.upper()}-{enrollment.student_id.upper()}",
                user_id=enrollment.student_id,
                course_id=enrollment.course_id,
                final_score=8.0,
            )
        )
    sess.flush()


# ---------------------------------------------------------------------------
# Truy cập DB từ request
# ---------------------------------------------------------------------------


def get_db() -> Database:
    from flask import current_app

    db: Database = current_app.extensions["lms_db"]
    return db