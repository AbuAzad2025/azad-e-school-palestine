"""Blueprint الواجبات والدرجات والحضور"""

from flask import Blueprint

bp = Blueprint("grades", __name__, url_prefix="/classes")

from . import routes  # noqa: E402,F401
