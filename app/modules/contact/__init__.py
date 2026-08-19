from flask import Blueprint

bp = Blueprint("contact", __name__, url_prefix="/contact")
from . import routes  # noqa
