from flask import Blueprint

bp = Blueprint("individual", __name__, url_prefix="/my")

from . import routes  # noqa: E402, F401
