"""Payments Module — المدفوعات والبوابات"""

from flask import Blueprint

bp = Blueprint("payments", __name__, url_prefix="/api/payments")

from . import routes  # noqa: E402,F401
from .routes import payments_ui_bp  # noqa: E402,F401
