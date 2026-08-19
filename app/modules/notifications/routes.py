"""مسارات الإشعارات"""

from app.models.communication import Notification
from app.services.communication import mark_all_read
from flask import redirect, render_template, request, url_for
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


@bp.get("/preferences")
@login_required
def preferences():
    from app.services.notification_preferences import DEFAULT_TYPES, get_preferences

    prefs = get_preferences(current_user.id)
    prefs_map = {}
    for p in prefs:
        prefs_map[p.notif_type] = {"email_enabled": p.email_enabled, "in_app_enabled": p.in_app_enabled}
    notif_labels = {
        "result": "النتائج الدراسية",
        "new_assignment": "واجب جديد",
        "announcement": "إعلانات الصف",
        "subscription": "الاشتراكات",
        "message": "رسائل جديدة",
        "grade_appeal": "اعتراضات الدرجات",
        "badge": "شارات جديدة",
    }
    notif_types = [(t, notif_labels.get(t, t)) for t in DEFAULT_TYPES]
    return render_template("notifications/preferences.html", prefs_map=prefs_map, notif_types=notif_types)


@bp.post("/preferences")
@login_required
def preferences_save():
    from app.services.notification_preferences import DEFAULT_TYPES, update_preference

    for ntype in DEFAULT_TYPES:
        in_app = request.form.get(f"in_app_{ntype}") is not None
        email = request.form.get(f"email_{ntype}") is not None
        update_preference(current_user.id, ntype, email, in_app)
    from flask import flash
    from flask_babel import _

    flash(_("تم حفظ التفضيلات."), "success")
    return redirect(url_for("notifications.preferences"))
