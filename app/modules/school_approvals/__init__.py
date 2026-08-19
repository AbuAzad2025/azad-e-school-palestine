"""Blueprint موافقات المدرسة"""

from flask import Blueprint

bp = Blueprint("school_approvals", __name__, url_prefix="/school-admin")

from . import routes  # noqa: E402,F401
