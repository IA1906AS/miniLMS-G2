"""BẢN TRƯỚC KHI SỬA — trích nguyên trạng logic sửa điểm cũ.

Chỉ dùng cho mục đích minh hoạ/báo cáo, KHÔNG được import vào ứng dụng.
Tương ứng admin.py (grade_quiz_adjust, grade_assignment_adjust) trước pattern.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from web.models import QuizAttempt, Submission


def adjust_assignment_old(
    sess: Session, submission_id: int, score_raw: str, feedback_raw: str | None = None
) -> float:
    submission = sess.get(Submission, submission_id)
    if submission is None:
        raise LookupError("submission not found")
    old_score = submission.score
    submission.score = float(score_raw)          # V02: không kiểm tra miền/NaN
    submission.feedback = feedback_raw or ""     # V03: thiếu field -> xoá nhận xét
    sess.flush()
    return old_score


def adjust_quiz_old(sess: Session, attempt_id: int, score_raw: str) -> float:
    attempt = sess.get(QuizAttempt, attempt_id)
    if attempt is None:
        raise LookupError("attempt not found")
    old_score = attempt.score
    attempt.score = float(score_raw)
    attempt.passed = attempt.score >= attempt.quiz.pass_score  # V02: AttributeError
    sess.flush()
    return old_score
