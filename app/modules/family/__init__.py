"""Blueprint روابط الأسرة"""

from flask import Blueprint

bp = Blueprint("family", __name__, url_prefix="/family")

from . import routes  # noqa: E402,F401
