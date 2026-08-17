"""Blueprint المدارس والصفوف"""

from flask import Blueprint

bp = Blueprint("schools", __name__, url_prefix="/schools")

from . import routes  # noqa: E402,F401
