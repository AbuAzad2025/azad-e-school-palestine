"""مسارات تتبع الإيرادات — لوحة تحكم السوبر أدمن"""

from app.core.permissions import role_required
from app.models.user import UserRole
from app.services.revenue import get_revenue_dashboard_data
from flask import render_template, request
from flask_login import login_required

from . import bp


@bp.get("/admin/revenue")
@login_required
@role_required(UserRole.super_admin)
def revenue_dashboard():
    """لوحة تحكم الإيرادات للسوبر أدمن."""
    days = request.args.get("days", 30, type=int)
    if days not in [7, 30, 90, 365]:
        days = 30

    data = get_revenue_dashboard_data(days=days)
    return render_template("admin/revenue.html", data=data, days=days)
