"""Media blueprint — secure video streaming routes."""

from flask import Blueprint

bp = Blueprint("media", __name__, url_prefix="/media")

from . import routes  # noqa: F401, E402
