"""Blueprint الاشتراكات والدفع"""

from flask import Blueprint

bp = Blueprint("billing", __name__, url_prefix="/billing")

from . import routes  # noqa: E402,F401
