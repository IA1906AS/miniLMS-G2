"""Entrypoint giao diện web: ``flask --app webapp run`` hoặc ``python webapp.py``.

API chấm thi vẫn chạy riêng bằng ``flask --app app run``.
"""

import os

from dotenv import load_dotenv

from web import create_web_app

load_dotenv()
# JWT_SECRET bắt buộc lấy từ môi trường/.env — không có giá trị mặc định cứng.
app = create_web_app()

if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "").lower() in {"1", "true", "yes"}
    app.run(host="127.0.0.1", port=8888, debug=debug)
