"""Unit tests for app.services.notification_preferences."""

from app.services.notification_preferences import (
    DEFAULT_TYPES,
    get_preference,
    get_preferences,
    should_notify,
    update_preference,
)
from tests.conftest import make_user


class TestGetPreferences:
    def test_returns_empty_list(self, app):
        with app.app_context():
            uid = make_user(app, "student")
            prefs = get_preferences(uid)
            assert prefs == []

    def test_returns_created_preferences(self, app):
        with app.app_context():
            uid = make_user(app, "student")
            update_preference(uid, "result", True, True)
            prefs = get_preferences(uid)
            assert len(prefs) == 1
            assert prefs[0].notif_type == "result"


class TestGetPreference:
    def test_returns_none_when_not_set(self, app):
        with app.app_context():
            uid = make_user(app, "student")
            pref = get_preference(uid, "result")
            assert pref is None

    def test_returns_preference_after_update(self, app):
        with app.app_context():
            uid = make_user(app, "student")
            update_preference(uid, "result", email_enabled=False, in_app_enabled=True)
            pref = get_preference(uid, "result")
            assert pref is not None
            assert pref.email_enabled is False
            assert pref.in_app_enabled is True


class TestUpdatePreference:
    def test_creates_new_preference(self, app):
        with app.app_context():
            uid = make_user(app, "student")
            pref = update_preference(uid, "result", True, False)
            assert pref.id is not None
            assert pref.notif_type == "result"

    def test_updates_existing_preference(self, app):
        with app.app_context():
            uid = make_user(app, "student")
            update_preference(uid, "result", True, True)
            updated = update_preference(uid, "result", False, False)
            assert updated.email_enabled is False
            assert updated.in_app_enabled is False

    def test_handles_all_default_types(self, app):
        with app.app_context():
            uid = make_user(app, "student")
            for ntype in DEFAULT_TYPES:
                pref = update_preference(uid, ntype, True, True)
                assert pref is not None
            all_prefs = get_preferences(uid)
            assert len(all_prefs) == len(DEFAULT_TYPES)


class TestShouldNotify:
    def test_defaults_to_true_when_no_pref(self, app):
        with app.app_context():
            uid = make_user(app, "student")
            assert should_notify(uid, "result") is True
            assert should_notify(uid, "result", "email") is True

    def test_respects_in_app_setting(self, app):
        with app.app_context():
            uid = make_user(app, "student")
            update_preference(uid, "result", email_enabled=True, in_app_enabled=False)
            assert should_notify(uid, "result", "in_app") is False
            assert should_notify(uid, "result", "email") is True

    def test_respects_email_setting(self, app):
        with app.app_context():
            uid = make_user(app, "student")
            update_preference(uid, "result", email_enabled=False, in_app_enabled=True)
            assert should_notify(uid, "result", "email") is False
            assert should_notify(uid, "result", "in_app") is True

    def test_all_disabled(self, app):
        with app.app_context():
            uid = make_user(app, "student")
            update_preference(uid, "result", False, False)
            assert should_notify(uid, "result") is False
            assert should_notify(uid, "result", "email") is False
