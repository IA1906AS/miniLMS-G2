"""Entrypoint giao diện web: ``flask --app webapp run`` hoặc ``python webapp.py``.

API chấm thi vẫn chạy riêng bằng ``flask --app app run``.
"""

import os

from dotenv import load_dotenv

from web import create_web_app

load_dotenv()
jwt_secret = (
    os.environ.get("JWT_SECRET")
    or "dev-secret-key-that-is-at-least-32-chars-long-12345"
)
app = create_web_app({"JWT_SECRET": jwt_secret})

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8888, debug=True)
