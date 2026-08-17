"""AI Module — الذكاء الاصطناعي المساعد"""

from flask import Blueprint

bp = Blueprint("ai", __name__, url_prefix="/ai")

from . import routes  # noqa: E402,F401
