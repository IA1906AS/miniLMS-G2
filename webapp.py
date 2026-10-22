"""Entrypoint giao diện web: ``flask --app webapp run`` hoặc ``python webapp.py``.

API chấm thi vẫn chạy riêng bằng ``flask --app app run``.
"""

from dotenv import load_dotenv

from web import create_web_app

load_dotenv()
app = create_web_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8888, debug=True)
