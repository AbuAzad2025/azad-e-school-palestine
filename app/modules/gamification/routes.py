"""مسارات الشارات — ملف الطالب والشارات المكتسبة"""

from app.services.gamification import check_and_award_badges, get_student_badges
from flask import render_template
from flask_login import current_user, login_required

from . import bp


@bp.get("/badges")
@login_required
def badges():
    """صفحة شارات الطالب."""
    badges = get_student_badges(current_user.id)
    all_badges = get_all_badges()
    return render_template("gamification/badges.html", badges=badges, all_badges=all_badges)


@bp.post("/badges/check")
@login_required
def check_badges():
    """فحص ومنح الشارات المستحقة (AJAX endpoint)."""
    from app.models.user import UserRole
    from flask import abort, jsonify, request

    if current_user.role not in (UserRole.student, UserRole.super_admin):
        abort(403)

    event_type = request.json.get("event_type")
    event_data = request.json.get("event_data")

    if not event_type:
        return jsonify({"error": "event_type required"}), 400

    new_badges = check_and_award_badges(current_user.id, event_type, event_data)

    return jsonify(
        {
            "awarded": len(new_badges),
            "badges": [{"id": b.badge.id, "name": b.badge.name, "icon": b.badge.icon_name} for b in new_badges],
        }
    )


def get_all_badges():
    """جلب كل الشارات المتاحة."""
    from app.models.gamification import Badge

    return Badge.query.filter_by(is_active=True).all()
