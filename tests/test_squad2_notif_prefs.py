"""Squad 2 — Agent 10: Notification Preferences.

Tests fallback configurations when preferences are missing,
disabled channels, and opt-out logic.
"""

import pytest
from app.extensions import db
from app.models.communication import NotificationPreference
from app.services.notification_preferences import (
    get_preferences,
    get_preference,
    update_preference,
    should_notify,
    DEFAULT_TYPES,
)
from tests.conftest import make_user


class TestShouldNotify:
    def test_default_all_enabled(self, app):
        """Without any preference, all channels should be enabled."""
        with app.app_context():
            uid = make_user(app, "student")
            for notif_type in DEFAULT_TYPES:
                assert should_notify(uid, notif_type, "in_app") is True
                assert should_notify(uid, notif_type, "email") is True

    def test_in_app_disabled(self, app):
        with app.app_context():
            uid = make_user(app, "student")
            update_preference(uid, "result", email_enabled=True, in_app_enabled=False)
            assert should_notify(uid, "result", "in_app") is False

    def test_email_disabled(self, app):
        with app.app_context():
            uid = make_user(app, "student")
            update_preference(uid, "result", email_enabled=False, in_app_enabled=True)
            assert should_notify(uid, "result", "email") is False

    def test_both_disabled(self, app):
        with app.app_context():
            uid = make_user(app, "student")
            update_preference(uid, "result", email_enabled=False, in_app_enabled=False)
            assert should_notify(uid, "result", "in_app") is False
            assert should_notify(uid, "result", "email") is False

    def test_unknown_type_defaults_enabled(self, app):
        """Non-existent notif_type should return True (default)."""
        with app.app_context():
            uid = make_user(app, "student")
            assert should_notify(uid, "unknown_type", "in_app") is True


class TestUpdatePreference:
    def test_create_new(self, app):
        with app.app_context():
            uid = make_user(app, "student")
            pref = update_preference(uid, "badge", email_enabled=True, in_app_enabled=False)
            assert pref.notif_type == "badge"
            assert pref.email_enabled is True
            assert pref.in_app_enabled is False

    def test_upsert_updates_existing(self, app):
        with app.app_context():
            uid = make_user(app, "student")
            update_preference(uid, "result", email_enabled=True, in_app_enabled=True)
            update_preference(uid, "result", email_enabled=False, in_app_enabled=False)
            prefs = get_preferences(uid)
            assert len(prefs) == 1
            assert prefs[0].email_enabled is False
            assert prefs[0].in_app_enabled is False


class TestGetPreferences:
    def test_empty(self, app):
        with app.app_context():
            uid = make_user(app, "student")
            prefs = get_preferences(uid)
            assert prefs == []

    def test_multiple(self, app):
        with app.app_context():
            uid = make_user(app, "student")
            update_preference(uid, "result", email_enabled=True, in_app_enabled=True)
            update_preference(uid, "message", email_enabled=False, in_app_enabled=True)
            update_preference(uid, "badge", email_enabled=True, in_app_enabled=False)
            prefs = get_preferences(uid)
            assert len(prefs) == 3


class TestGetPreference:
    def test_existing(self, app):
        with app.app_context():
            uid = make_user(app, "student")
            update_preference(uid, "result", email_enabled=True, in_app_enabled=True)
            pref = get_preference(uid, "result")
            assert pref is not None
            assert pref.notif_type == "result"

    def test_nonexistent(self, app):
        with app.app_context():
            uid = make_user(app, "student")
            pref = get_preference(uid, "nonexistent")
            assert pref is None


class TestDefaultTypes:
    def test_default_types_non_empty(self):
        assert len(DEFAULT_TYPES) > 0

    def test_default_types_contains_expected(self):
        assert "result" in DEFAULT_TYPES
        assert "new_assignment" in DEFAULT_TYPES
        assert "announcement" in DEFAULT_TYPES
        assert "subscription" in DEFAULT_TYPES
        assert "message" in DEFAULT_TYPES
