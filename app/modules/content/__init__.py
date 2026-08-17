"""Blueprint المحتوى (الدروس)"""

from flask import Blueprint

bp = Blueprint("content", __name__, url_prefix="/classes")

from . import routes  # noqa: E402,F401
