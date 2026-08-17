"""Blueprint تتبع التقدم"""

from flask import Blueprint

bp = Blueprint("progress", __name__, url_prefix="/progress")

from . import routes  # noqa: E402,F401
