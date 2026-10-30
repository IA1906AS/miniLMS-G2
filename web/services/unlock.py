"""Điều kiện mở khoá bài học — rule khai báo, không hard-code.

Một bài học có thể có nhiều ``UnlockRule`` (AND). Không có rule nào nghĩa là
bài học mở. Hàm ``can_access`` là điểm kiểm tra duy nhất, có phát hiện chu
trình (A mở khoá B, B mở khoá A) để không treo server.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from web.models import (
    UNLOCK_DATE_REACHED,
    UNLOCK_LESSON_COMPLETED,
    UNLOCK_MANUAL,
    UNLOCK_QUIZ_PASSED,
    Lesson,
    Quiz,
    QuizAttempt,
    UnlockRule,
    utcnow,
)
from web.services.activity import completed_lesson_ids

MAX_DEPTH = 12


class UnlockCycleError(RuntimeError):
    """Rule mở khoá tạo chu trình — dữ liệu sai, cần chặn khi lưu."""


def rules_for(sess: Session, lesson_id: int) -> list[UnlockRule]:
    return list(
        sess.scalars(
            select(UnlockRule)
            .where(UnlockRule.lesson_id == lesson_id)
            .order_by(UnlockRule.id)
        ).all()
    )


def has_cycle(
    sess: Session, lesson_id: int, _seen: frozenset[int] = frozenset()
) -> bool:
    if lesson_id in _seen:
        return True
    seen = _seen | {lesson_id}
    for rule in rules_for(sess, lesson_id):
        if rule.ref_lesson_id is not None and has_cycle(sess, rule.ref_lesson_id, seen):
            return True
    return False


def _rule_ok(
    sess: Session,
    rule: UnlockRule,
    *,
    user_id: str | None,
    section_id: int,
    depth: int,
    cache: dict[int, bool],
) -> bool:
    if rule.rule_type == UNLOCK_MANUAL:
        return True
    if rule.rule_type == UNLOCK_DATE_REACHED:
        return rule.available_from is None or rule.available_from <= utcnow()
    if rule.rule_type == UNLOCK_LESSON_COMPLETED:
        if rule.ref_lesson_id is None or user_id is None:
            return False
        return rule.ref_lesson_id in completed_lesson_ids(sess, user_id, section_id)
    if rule.rule_type == UNLOCK_QUIZ_PASSED:
        if user_id is None or rule.ref_quiz_id is None:
            return False
        quiz = sess.get(Quiz, rule.ref_quiz_id)
        if quiz is None:
            return False
        attempts = sess.scalars(
            select(QuizAttempt).where(
                QuizAttempt.quiz_id == quiz.id,
                QuizAttempt.student_id == user_id,
                QuizAttempt.passed.is_(True),
            )
        ).all()
        if not attempts:
            return False
        threshold = rule.threshold if rule.threshold is not None else quiz.pass_score
        return any(attempt.score >= threshold for attempt in attempts)
    if depth > MAX_DEPTH:
        return False
    return False


def can_access(
    sess: Session,
    lesson: Lesson,
    *,
    user_id: str | None,
    section_id: int,
    is_teacher_or_admin: bool = False,
) -> bool:
    """True nếu người dùng được mở bài học này.

    Giảng viên/admin bỏ qua điều kiện mở khoá; bài ``is_preview`` luôn mở.
    """
    if is_teacher_or_admin or lesson.is_preview:
        return True
    if user_id is None:
        return False

    cache: dict[int, bool] = {}
    for rule in rules_for(sess, lesson.id):
        if not _rule_ok(
            sess,
            rule,
            user_id=user_id,
            section_id=section_id,
            depth=0,
            cache=cache,
        ):
            return False
    return True


def locked_lessons(sess: Session, *, user_id: str | None, section_id: int) -> set[int]:
    """Tập id bài học bị khoá — dùng để hiển thị ổ khoá trong mục lục."""
    lessons = sess.scalars(
        select(Lesson)
        .join(Lesson.module)
        .where(Lesson.module.has(section_id=section_id))
    ).all()
    return {
        lesson.id
        for lesson in lessons
        if not can_access(sess, lesson, user_id=user_id, section_id=section_id)
    }


def describe_rule(rule: UnlockRule) -> str:
    if rule.rule_type == UNLOCK_LESSON_COMPLETED:
        return "hoàn thành bài học trước"
    if rule.rule_type == UNLOCK_QUIZ_PASSED:
        return "đạt điểm quiz yêu cầu"
    if rule.rule_type == UNLOCK_DATE_REACHED:
        when = rule.available_from.strftime("%d/%m/%Y") if rule.available_from else "?"
        return f"mở từ {when}"
    if rule.rule_type == UNLOCK_MANUAL:
        return "mở thủ công"
    return rule.rule_type


def rules_summary(sess: Session, lesson_id: int) -> list[dict[str, Any]]:
    return [
        {"id": rule.id, "type": rule.rule_type, "text": describe_rule(rule)}
        for rule in rules_for(sess, lesson_id)
    ]
