"""Entrypoint giao diện web: ``flask --app webapp run``.

API chấm thi vẫn chạy riêng bằng ``flask --app app run``.
"""

from web import create_web_app

app = create_web_app()
