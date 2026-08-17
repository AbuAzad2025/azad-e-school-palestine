"""Blueprint التقييم (اختبارات)"""

from flask import Blueprint

bp = Blueprint("assessment", __name__, url_prefix="/classes")

from . import routes  # noqa: E402,F401
