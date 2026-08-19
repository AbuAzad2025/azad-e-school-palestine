"""اختبارات تفضيلات الإشعارات."""

from app.services.notification_preferences import (
    get_preferences,
    should_notify,
    update_preference,
)
from tests.conftest import make_user


def test_default_notifications_enabled(app):
    uid = make_user(app, role="student")
    with app.app_context():
        assert should_notify(uid, "result", "in_app") is True
        assert should_notify(uid, "result", "email") is True


def test_update_preference(app):
    uid = make_user(app, role="student")
    with app.app_context():
        pref = update_preference(uid, "result", email_enabled=False, in_app_enabled=True)
        assert pref.email_enabled is False
        assert pref.in_app_enabled is True
        assert pref.notif_type == "result"
        assert pref.user_id == uid


def test_should_notify_in_app(app):
    uid = make_user(app, role="student")
    with app.app_context():
        update_preference(uid, "result", email_enabled=True, in_app_enabled=False)
        assert should_notify(uid, "result", "in_app") is False
        assert should_notify(uid, "result", "email") is True


def test_should_notify_email(app):
    uid = make_user(app, role="student")
    with app.app_context():
        update_preference(uid, "result", email_enabled=False, in_app_enabled=True)
        assert should_notify(uid, "result", "email") is False
        assert should_notify(uid, "result", "in_app") is True


def test_disable_notification(app):
    uid = make_user(app, role="student")
    with app.app_context():
        update_preference(uid, "result", email_enabled=True, in_app_enabled=False)
        assert should_notify(uid, "result", "in_app") is False


def test_disable_email_only(app):
    uid = make_user(app, role="student")
    with app.app_context():
        update_preference(uid, "result", email_enabled=False, in_app_enabled=True)
        assert should_notify(uid, "result", "in_app") is True
        assert should_notify(uid, "result", "email") is False


def test_get_preferences(app):
    uid = make_user(app, role="student")
    with app.app_context():
        update_preference(uid, "result", email_enabled=True, in_app_enabled=True)
        update_preference(uid, "message", email_enabled=False, in_app_enabled=True)
        prefs = get_preferences(uid)
        assert len(prefs) == 2
        types = {p.notif_type for p in prefs}
        assert types == {"result", "message"}


def test_update_preference_upsert(app):
    uid = make_user(app, role="student")
    with app.app_context():
        update_preference(uid, "result", email_enabled=True, in_app_enabled=True)
        update_preference(uid, "result", email_enabled=False, in_app_enabled=False)
        prefs = get_preferences(uid)
        assert len(prefs) == 1
        assert prefs[0].email_enabled is False
        assert prefs[0].in_app_enabled is False
