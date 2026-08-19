"""خدمات تفضيلات الإشعارات."""

from app.extensions import db
from app.models.communication import NotificationPreference

from .base import tx

DEFAULT_TYPES = ["result", "new_assignment", "announcement", "subscription", "message", "grade_appeal", "badge"]


def get_preferences(user_id: int) -> list[NotificationPreference]:
    return NotificationPreference.query.filter_by(user_id=user_id).all()


def get_preference(user_id: int, notif_type: str) -> NotificationPreference | None:
    return NotificationPreference.query.filter_by(user_id=user_id, notif_type=notif_type).first()


def update_preference(
    user_id: int,
    notif_type: str,
    email_enabled: bool,
    in_app_enabled: bool,
) -> NotificationPreference:
    existing = NotificationPreference.query.filter_by(user_id=user_id, notif_type=notif_type).first()

    def _update():
        if existing:
            existing.email_enabled = email_enabled
            existing.in_app_enabled = in_app_enabled
            return existing
        pref = NotificationPreference(
            user_id=user_id,
            notif_type=notif_type,
            email_enabled=email_enabled,
            in_app_enabled=in_app_enabled,
        )
        db.session.add(pref)
        return pref

    return tx(_update)


def should_notify(user_id: int, notif_type: str, channel: str = "in_app") -> bool:
    pref = get_preference(user_id, notif_type)
    if not pref:
        return True
    if channel == "email":
        return pref.email_enabled
    return pref.in_app_enabled
