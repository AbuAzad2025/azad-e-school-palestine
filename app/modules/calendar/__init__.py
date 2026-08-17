"""Blueprint التقويم الأكاديمي"""

from flask import Blueprint

bp = Blueprint("calendar", __name__, url_prefix="/calendar")

from . import routes  # noqa: E402,F401
