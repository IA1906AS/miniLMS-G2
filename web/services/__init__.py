"""Tầng nghiệp vụ của LMS — không module nào ở đây import flask.

Mỗi hàm nhận ``Session`` (SQLAlchemy) và actor dạng ``dict`` nên test được
bằng unit test thuần, tái dùng cho cả giao diện HTML và API JSON.
"""

from __future__ import annotations
