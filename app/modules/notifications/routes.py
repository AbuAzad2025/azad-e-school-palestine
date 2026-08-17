"""مسارات الإشعارات"""

from app.models.communication import Notification
from app.services.communication import mark_all_read
from flask import redirect, render_template, url_for
from flask_login import current_user, login_required

from . import bp


@bp.get("/")
@login_required
def index():
    items = (
        Notification.query.filter_by(user_id=current_user.id).order_by(Notification.created_at.desc()).limit(100).all()
    )
    return render_template("notifications/index.html", items=items)


@bp.post("/read")
@login_required
def read():
    mark_all_read(current_user.id)
    return redirect(url_for("notifications.index"))
