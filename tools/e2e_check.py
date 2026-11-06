"""Kiểm thử end-to-end các tính năng vừa bổ sung + xác minh ghi DB.

Chạy: .venv\\Scripts\\python.exe tools\\e2e_check.py
"""

from __future__ import annotations

import io
import re
from email import message_from_bytes
from pathlib import Path
import sys
from datetime import timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import select

from web import create_web_app
from web.database import get_db
from web.models import (
    Attachment,
    AuditEvent,
    Enrollment,
    ForumTopic,
    Notification,
    PasswordResetToken,
    QuizAttempt,
    Submission,
    User,
    utcnow,
)

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        PASS.append(name)
        print(f"PASS  {name} {detail}")
    else:
        FAIL.append(name)
        print(f"FAIL  {name} {detail}")


def login(client, email: str, password: str = "Lms@2026"):
    return client.post(
        "/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )


def mail_dir(app) -> Path:
    path = Path(app.config["MAIL_DIR"])
    if not path.is_absolute():
        path = Path(app.root_path).parent / path
    return path


def main() -> int:
    app = create_web_app()
    app.config.update(TESTING=True)
    uploads = Path(app.root_path).parent / app.config["UPLOAD_DIR"]

    # --- 1. EMAIL + reset password ---
    with app.test_client() as c:
        r = c.post("/forgot-password", data={"email": "chi.sv@lms.test"})
        check("forgot-password 200", r.status_code == 200, str(r.status_code))

    mails = sorted(mail_dir(app).glob("*-reset-*.eml"))
    check("reset email file created", bool(mails))
    token = None
    if mails:
        msg = message_from_bytes(mails[-1].read_bytes())
        body = msg.get_payload(decode=True)
        text = body.decode("utf-8", "ignore") if body else ""
        m = re.search(r"/reset-password/([A-Za-z0-9_\-]+)", text)
        token = m.group(1) if m else None
    check("reset token extracted from email", bool(token))

    with app.app_context():
        with get_db().session() as s:
            row = s.scalars(
                select(PasswordResetToken).order_by(PasswordResetToken.id.desc())
            ).first()
            check("reset token row saved", row is not None)

    if token:
        with app.test_client() as c:
            r = c.post(
                f"/reset-password/{token}",
                data={
                    "new_password": "NewPass@2026",
                    "confirm_password": "NewPass@2026",
                },
            )
            check("reset-password submit 200", r.status_code == 200)
        with app.test_client() as c:
            r = login(c, "chi.sv@lms.test", "NewPass@2026")
            check("login with new password", r.status_code == 302, str(r.status_code))
            c.post(
                "/profile/password",
                data={
                    "old_password": "NewPass@2026",
                    "new_password": "Lms@2026",
                    "confirm_password": "Lms@2026",
                },
            )

    # --- 2. Avatar upload ---
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00"
        b"\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    with app.test_client() as c:
        login(c, "chi.sv@lms.test")
        r = c.post(
            "/profile/avatar",
            data={"avatar": (io.BytesIO(png), "a.png")},
            content_type="multipart/form-data",
            follow_redirects=False,
        )
        check("avatar upload redirect", r.status_code == 302, str(r.status_code))
    with app.app_context():
        with get_db().session() as s:
            u = s.get(User, "u4")
            check(
                "avatar_path saved",
                bool(u and u.avatar_path),
                str(u.avatar_path if u else None),
            )

    # --- 3. GV gửi thông báo + email ---
    with app.test_client() as c:
        login(c, "an.gv@lms.test")
        r = c.post(
            "/instructor/notifications",
            data={
                "course_id": "c1",
                "title": "Lịch thi cuối kỳ",
                "body": "Thi ngày 20/12.",
            },
            follow_redirects=False,
        )
        check("instructor notify redirect", r.status_code == 302, str(r.status_code))
    with app.app_context():
        with get_db().session() as s:
            notes = s.scalars(
                select(Notification).where(
                    Notification.sender_id == "u2",
                    Notification.title == "Lịch thi cuối kỳ",
                )
            ).all()
            check("notification rows saved", len(notes) >= 4, f"rows={len(notes)}")
    check("notification email files", bool(list(mail_dir(app).glob("*-notify-*.eml"))))

    # --- 4. Ghi danh bằng mã ---
    with app.test_client() as c:
        login(c, "chi.sv@lms.test")
        r = c.post("/enroll", data={"code": "C2-2026"}, follow_redirects=False)
        check("enroll by code redirect", r.status_code == 302, str(r.status_code))
    with app.app_context():
        with get_db().session() as s:
            e = s.scalars(
                select(Enrollment).where(
                    Enrollment.course_id == "c2",
                    Enrollment.student_id == "u4",
                )
            ).first()
            check("enrollment row saved", e is not None)

    # --- 5. Upload tài liệu bài giảng ---
    with app.test_client() as c:
        login(c, "an.gv@lms.test")
        r = c.post(
            "/lessons/1/attachments",
            data={
                "title": "Slide HTML5",
                "file": (io.BytesIO(b"%PDF-1.4 test"), "slide.pdf"),
            },
            content_type="multipart/form-data",
            follow_redirects=False,
        )
        check("attachment upload redirect", r.status_code == 302, str(r.status_code))
    with app.app_context():
        with get_db().session() as s:
            att = s.scalars(
                select(Attachment).where(Attachment.title == "Slide HTML5")
            ).first()
            check("attachment row saved", att is not None)
            check(
                "attachment file exists",
                bool(att and (uploads / att.stored_name).is_file()),
            )

    # --- 6. Nộp bài kèm tệp ---
    with app.test_client() as c:
        login(c, "chi.sv@lms.test")
        r = c.post(
            "/assignments/1/submit",
            data={
                "text": "Bài làm của em",
                "file": (io.BytesIO(b"print('hello')"), "bai.py"),
            },
            content_type="multipart/form-data",
            follow_redirects=False,
        )
        check("assignment submit redirect", r.status_code == 302, str(r.status_code))
    with app.app_context():
        with get_db().session() as s:
            sub = s.scalars(
                select(Submission).where(
                    Submission.assignment_id == 1,
                    Submission.student_id == "u4",
                )
            ).first()
            check("submission row saved", sub is not None)
            check(
                "submission file_path saved",
                bool(sub and sub.file_path),
                str(sub.file_path if sub else None),
            )
            sub_id = sub.id if sub else None

    # --- 7. Chấm điểm + audit ---
    if sub_id:
        with app.test_client() as c:
            login(c, "an.gv@lms.test")
            r = c.post(
                f"/assignments/1/submissions/{sub_id}/grade",
                data={"score": "8.5", "feedback": "Tốt"},
                follow_redirects=False,
            )
            check("grade redirect", r.status_code == 302, str(r.status_code))
        with app.app_context():
            with get_db().session() as s:
                sub = s.get(Submission, sub_id)
                check(
                    "grade saved",
                    sub is not None and sub.score == 8.5,
                    str(sub.score if sub else None),
                )
                ev = s.scalars(
                    select(AuditEvent).where(
                        AuditEvent.action == "GRADE_UPDATE",
                        AuditEvent.resource == f"submission:{sub_id}",
                    )
                ).first()
                check("grade audit saved", ev is not None)

    # --- 8. Forum sửa chủ đề của chính mình ---
    with app.app_context():
        with get_db().session() as s:
            topic = s.scalars(
                select(ForumTopic).where(
                    ForumTopic.course_id == "c1",
                    ForumTopic.author_id == "u4",
                )
            ).first()
            topic_id = topic.id if topic else None
    if topic_id:
        with app.test_client() as c:
            login(c, "chi.sv@lms.test")
            r = c.post(
                f"/forum/c1/topic/{topic_id}/edit",
                data={"title": "Tiêu đề đã sửa", "content": "Nội dung đã sửa"},
                follow_redirects=False,
            )
            check("forum topic edit", r.status_code == 302, str(r.status_code))
        with app.app_context():
            with get_db().session() as s:
                t = s.get(ForumTopic, topic_id)
                check(
                    "forum topic updated",
                    t is not None and t.title == "Tiêu đề đã sửa",
                )

    # --- 9. Hồ sơ thành viên + lọc theo GV + nhật ký ---
    with app.test_client() as c:
        login(c, "chi.sv@lms.test")
        check("member profile 200", c.get("/members/u2").status_code == 200)
        check("course filter by instructor", c.get("/courses?instructor=u2").status_code == 200)
    with app.test_client() as c:
        login(c, "admin@lms.test")
        r = c.get("/admin/audit")
        check("admin audit page", r.status_code == 200, str(r.status_code))
        check("audit page has GRADE_UPDATE", b"GRADE_UPDATE" in r.data)

    # --- 10. Cưỡng chế thời gian quiz ---
    with app.app_context():
        with get_db().session() as s:
            att = QuizAttempt(
                quiz_id=1,
                student_id="u5",
                status="IN_PROGRESS",
                started_at=utcnow() - timedelta(days=2),
            )
            s.add(att)
            s.flush()
            att_id = att.id
    with app.test_client() as c:
        login(c, "dung.sv@lms.test")
        r = c.post(
            f"/quizzes/1/attempts/{att_id}/submit",
            data={},
            follow_redirects=False,
        )
        check("expired quiz submit handled", r.status_code == 302, str(r.status_code))
    with app.app_context():
        with get_db().session() as s:
            att = s.get(QuizAttempt, att_id)
            check(
                "quiz attempt marked EXPIRED",
                att is not None and att.status == "EXPIRED",
                str(att.status if att else None),
            )

    print("\n===== SUMMARY =====")
    print(f"PASS: {len(PASS)}  FAIL: {len(FAIL)}")
    if FAIL:
        print("Failed:", ", ".join(FAIL))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
