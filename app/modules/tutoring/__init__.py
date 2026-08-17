"""Blueprint الدروس الخصوصية"""

from flask import Blueprint

bp = Blueprint("tutoring", __name__, url_prefix="/tutoring")

from . import routes  # noqa: E402,F401
