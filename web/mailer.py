"""Dịch vụ EMAIL (thành phần EMAIL trong đặc tả).

Chế độ dev: không có SMTP thì ghi mỗi email thành một tệp ``.eml`` trong
``instance/mail/`` để vẫn kiểm chứng được "email đã được gửi".
Nếu cấu hình ``SMTP_HOST`` trong môi trường thì gửi thật qua SMTP.
"""

from __future__ import annotations

import smtplib
from datetime import datetime
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path

from flask import current_app


def _mail_dir() -> Path:
    configured = current_app.config.get("MAIL_DIR") or "instance/mail"
    path = Path(str(configured))
    if not path.is_absolute():
        path = Path(current_app.root_path).parent / path
    path.mkdir(parents=True, exist_ok=True)
    return path


def send_email(to: str, subject: str, body: str, *, kind: str = "generic") -> str:
    """Gửi (hoặc ghi ra tệp) một email. Trả về định danh/tệp đã tạo."""
    sender = current_app.config.get("MAIL_FROM", "no-reply@minilms.local")
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="minilms.local")
    msg.set_content(body)

    smtp_host = current_app.config.get("SMTP_HOST")
    if smtp_host:
        port = int(current_app.config.get("SMTP_PORT", 25))
        with smtplib.SMTP(smtp_host, port, timeout=10) as client:
            username = current_app.config.get("SMTP_USER")
            if username:
                client.starttls()
                client.login(username, current_app.config.get("SMTP_PASSWORD", ""))
            client.send_message(msg)
        return f"smtp:{to}"

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    safe_to = "".join(c if c.isalnum() or c in "._-" else "_" for c in to)
    path = _mail_dir() / f"{stamp}-{kind}-{safe_to}.eml"
    path.write_bytes(msg.as_bytes())
    return str(path)


def send_password_reset(to: str, reset_url: str, ttl_minutes: int) -> str:
    body = (
        "Xin chào,\n\n"
        "Bạn (hoặc ai đó) đã yêu cầu khôi phục mật khẩu cho tài khoản miniLMS.\n"
        f"Mở liên kết sau để đặt mật khẩu mới ({ttl_minutes} phút hiệu lực):\n\n"
        f"{reset_url}\n\n"
        "Nếu không phải bạn, hãy bỏ qua email này.\n"
    )
    return send_email(to, "[miniLMS] Khôi phục mật khẩu", body, kind="reset")


def send_notification(to: str, title: str, body: str, link: str | None = None) -> str:
    text = f"{title}\n\n{body}\n"
    if link:
        text += f"\nXem chi tiết: {link}\n"
    return send_email(to, f"[miniLMS] {title}", text, kind="notify")
