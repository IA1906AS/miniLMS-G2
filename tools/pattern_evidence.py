"""Sinh bằng chứng before/after cho pattern Optimistic Locking (sửa điểm).

Chạy: .venv\\Scripts\\python.exe tools\\pattern_evidence.py
Kết quả ghi ra docs/patterns/evidence.txt
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "docs" / "patterns"))

from dotenv import load_dotenv

load_dotenv()


from sua_diem_truoc_khi_sua import adjust_assignment_old, adjust_quiz_old

from web import create_web_app
from web.database import get_db
from web.grade_service import (
    GradeConflict,
    GradeValidationError,
    update_quiz_grade,
    update_submission_grade,
)
from web.models import Quiz, QuizAttempt, Submission, utcnow

SECRET = "evidence-secret-key-that-is-at-least-32-chars-long"
SEED = str(ROOT / "seed.json")
ACTOR = {"id": "u1", "role": "ADMIN"}
LINES: list[str] = []


def log(text: str = "") -> None:
    print(text)
    LINES.append(text)


def new_app():
    app = create_web_app({"JWT_SECRET": SECRET, "DATABASE_URL": "sqlite://", "SEED_PATH": SEED})
    app.config.update(TESTING=True)
    return app


def make_submission(app, *, score=5.0, feedback="Tốt") -> int:
    with app.app_context(), get_db().session() as s:
        sub = Submission(
            assignment_id=1,
            student_id="u4",
            text="Bài làm",
            submitted_at=utcnow(),
            score=score,
            feedback=feedback,
            graded_at=utcnow(),
            version=1,
        )
        s.add(sub)
        s.flush()
        return sub.id


def reset_submission(app, sid: int) -> None:
    with app.app_context(), get_db().session() as s:
        sub = s.get(Submission, sid)
        sub.score = 5.0
        sub.feedback = "Tốt"
        sub.version = 1
        s.flush()


def get_sub(app, sid: int) -> tuple[float, str | None, int]:
    with app.app_context(), get_db().session() as s:
        sub = s.get(Submission, sid)
        return sub.score, sub.feedback, sub.version


def make_attempt(app) -> int:
    with app.app_context(), get_db().session() as s:
        attempt = QuizAttempt(
            quiz_id=1,
            student_id="u4",
            status="SUBMITTED",
            score=5.0,
            passed=False,
            started_at=utcnow(),
            submitted_at=utcnow(),
            version=1,
        )
        s.add(attempt)
        s.flush()
        return attempt.id


def main() -> int:
    app = new_app()

    # =====================================================================
    log("=" * 72)
    log("BẰNG CHỨNG BEFORE/AFTER — PATTERN #3 OPTIMISTIC LOCKING")
    log("Tính năng: sửa điểm bài nộp / điểm quiz")
    log("=" * 72)

    # --------------------------- V01 ---------------------------
    sid = make_submission(app, score=5.0, feedback="Tốt")
    log("")
    log("### V01 — Mất cập nhật khi hai người sửa cùng lúc (lost update)")
    log("")
    log("[BEFORE] Trạng thái ban đầu: score=5, version=1")
    with app.app_context(), get_db().session() as s:
        adjust_assignment_old(s, sid, "9", "Tốt")  # người A
        adjust_assignment_old(s, sid, "2", "Tốt")  # người B (vẫn nghĩ score=5)
    score, fb, ver = get_sub(app, sid)
    log(f"[BEFORE] Người A lưu 9 → người B lưu 2. Kết quả DB: score={score}, version={ver}")
    log("[BEFORE] KẾT LUẬN: thay đổi 9 của A bị ghi đè âm thầm, không báo lỗi.")

    reset_submission(app, sid)
    log("")
    log("[AFTER] Reset: score=5, version=1")
    with app.app_context(), get_db().session() as s:
        update_submission_grade(s, ACTOR, sid, "9", "Tốt", "1")  # người A
    score, fb, ver = get_sub(app, sid)
    log(f"[AFTER] Người A lưu 9 (version=1) → DB: score={score}, version={ver}")

    with app.app_context(), get_db().session() as s:
        try:
            update_submission_grade(s, ACTOR, sid, "2", "Tốt", "1")  # B cầm version cũ
        except GradeConflict as exc:
            log(f"[AFTER] Người B lưu 2 (version=1) → bị chặn: {exc}")
    score, fb, ver = get_sub(app, sid)
    log(f"[AFTER] KẾT QUẢ DB: score={score}, version={ver}")
    log("[AFTER] KẾT LUẬN: không ghi đè; client nhận 409 và phải tải lại.")

    # --------------------------- V02 ---------------------------
    log("")
    log("### V02 — 500 khi chỉnh điểm quiz (AttributeError attempt.quiz)")
    attempt_id = make_attempt(app)
    log("")
    log("[BEFORE] Gọi adjust_quiz_old():")
    with app.app_context(), get_db().session() as s:
        try:
            adjust_quiz_old(s, attempt_id, "8")
            log("[BEFORE] Không có lỗi (không mong đợi)")
        except AttributeError as exc:
            log(f"[BEFORE] AttributeError: {exc} → HTTP 500")

    log("")
    log("[AFTER] update_quiz_grade() dùng Quiz lấy theo quiz_id:")
    with app.app_context(), get_db().session() as s:
        result = update_quiz_grade(s, ACTOR, attempt_id, "8", "1")
        quiz = s.get(Quiz, s.get(QuizAttempt, attempt_id).quiz_id)
        log(
            f"[AFTER] score={result.new_score}, version={result.version}, "
            f"passed={s.get(QuizAttempt, attempt_id).passed} "
            f"(pass_score={quiz.pass_score})"
        )
    log("[AFTER] KẾT LUẬN: không còn 500; passed tính đúng theo pass_score.")

    # --------------------------- V03 ---------------------------
    sid3 = sid
    reset_submission(app, sid3)
    log("")
    log("### V03 — Nhận xét bị xoá khi yêu cầu không gửi trường feedback")
    log("")
    log("[BEFORE] feedback='Tốt', gửi {score: 7} (không có feedback):")
    with app.app_context(), get_db().session() as s:
        adjust_assignment_old(s, sid3, "7", None)
    score, fb, ver = get_sub(app, sid3)
    log(f"[BEFORE] DB sau đó: score={score}, feedback={fb!r} → nhận xét bị xoá")

    reset_submission(app, sid3)
    log("")
    log("[AFTER] feedback='Tốt', gửi {score: 7} (không có feedback):")
    with app.app_context(), get_db().session() as s:
        update_submission_grade(s, ACTOR, sid3, "7", None, "1")
    score, fb, ver = get_sub(app, sid3)
    log(f"[AFTER] DB sau đó: score={score}, feedback={fb!r} → nhận xét được giữ")

    # --------------------------- Validation ---------------------------
    log("")
    log("### Kiểm tra miền điểm (bổ sung trong bản AFTER)")
    reset_submission(app, sid3)
    for bad in ("99", "-1", "abc", "nan"):
        with app.app_context(), get_db().session() as s:
            try:
                update_submission_grade(s, ACTOR, sid3, bad, None, "1")
                log(f"  score={bad!r}: KHÔNG bị chặn (sai)")
            except GradeValidationError as exc:
                log(f"  score={bad!r}: bị chặn — {exc}")
    score, fb, ver = get_sub(app, sid3)
    log(f"  DB cuối: score={score}, version={ver} (không đổi)")

    log("")
    log("=" * 72)
    log("KẾT LUẬN: cả 3 lỗi đã được xử lý; 2 lỗi cuối có test hồi quy riêng.")
    log("=" * 72)

    out = ROOT / "docs" / "patterns" / "evidence.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(LINES) + "\n", encoding="utf-8")
    print(f"\nSaved: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
