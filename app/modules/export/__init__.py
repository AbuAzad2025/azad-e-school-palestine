"""Blueprint التصدير"""

from flask import Blueprint

bp = Blueprint("export", __name__, url_prefix="/export")

from . import routes  # noqa: E402,F401
