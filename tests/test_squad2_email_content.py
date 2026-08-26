"""SQUAD 2 EXTRA: Tests for email service, content service, impersonation."""

import pytest
from unittest.mock import patch, MagicMock
from app.extensions import db
from app.models.user import User, UserRole, UserApprovalStatus
from app.services.email import (
    _recipient_locale, _dir, _fmt_date, _footer,
    send_welcome_email, send_payment_approved_email, send_payment_rejected_email,
    send_grade_published_email, send_quiz_result_email,
    send_absence_alert_email, send_contact_reply_email,
)
from app.services.content import (
    create_unit, list_units, create_lesson, get_lesson,
    publish_lesson, unpublish_lesson, _sanitize_html,
    list_lessons, update_lesson,
)
from app.services.impersonation import (
    is_impersonating, impersonator_user, clear_impersonation, SESSION_KEY,
)
from tests.conftest import make_school, make_user


# ── Email Service ──
class TestEmailService:
    def test_recipient_locale(self, app):
        with app.app_context():
            u = User(name_ar="Test", email="t@test.com", role=UserRole.student, locale="ar", password_hash="x")
            assert _recipient_locale(u) == "ar"

    def test_recipient_locale_none(self, app):
        with app.app_context():
            u = User(name_ar="Test", email="t@test.com", role=UserRole.student, password_hash="x")
            u.locale = None
            assert _recipient_locale(u) == "ar"

    def test_dir_ar(self):
        assert _dir("ar") == "rtl"

    def test_dir_en(self):
        assert _dir("en") == "ltr"

    def test_fmt_date_none(self):
        assert _fmt_date(None, "ar") == "—"

    def test_footer(self):
        f = _footer()
        assert "تلقائية" in f or "auto" in f.lower()

    def test_send_disabled(self, app):
        with app.app_context():
            app.config["EMAIL_ENABLED"] = False
            u = User(name_ar="Test", email="t@test.com", role=UserRole.student, locale="ar", password_hash="x")
            result = send_welcome_email(u)
            assert result is False


# ── Content Service ──
class TestContentService:
    def test_create_unit(self, app):
        with app.app_context():
            u = create_unit(1, "Unit 1")
            assert u.title == "Unit 1"

    def test_list_units(self, app):
        with app.app_context():
            create_unit(1, "Unit A")
            create_unit(1, "Unit B")
            units = list_units(1)
            assert len(units) == 2

    def test_create_lesson(self, app):
        with app.app_context():
            lesson, err = create_lesson(1, "Lesson 1")
            assert err is None
            assert lesson.title == "Lesson 1"

    def test_create_lesson_empty_title(self, app):
        with app.app_context():
            lesson, err = create_lesson(1, "")
            assert lesson is None

    def test_get_lesson(self, app):
        with app.app_context():
            lesson, _ = create_lesson(1, "Test Lesson")
            fetched = get_lesson(lesson.id)
            assert fetched is not None

    def test_publish_unpublish(self, app):
        with app.app_context():
            lesson, _ = create_lesson(1, "Draft Lesson")
            publish_lesson(lesson)
            assert lesson.status == "published"
            unpublish_lesson(lesson)
            assert lesson.status == "draft"

    def test_sanitize_html(self):
        result = _sanitize_html("<p>Hello</p><script>alert('xss')</script>")
        assert "<script>" not in result
        assert "<p>Hello</p>" in result

    def test_sanitize_html_none(self):
        assert _sanitize_html(None) is None

    def test_update_lesson(self, app):
        with app.app_context():
            lesson, _ = create_lesson(1, "Original")
            update_lesson(lesson, title="Updated", unit_id=None, body_html="<p>Body</p>")
            assert lesson.title == "Updated"


# ── Impersonation ──
class TestImpersonation:
    def test_not_impersonating(self, app):
        with app.test_request_context():
            from flask import session
            assert is_impersonating() is False

    def test_impersonator_user_none(self, app):
        with app.test_request_context():
            assert impersonator_user() is None

    def test_clear_impersonation(self, app):
        with app.test_request_context():
            from flask import session
            session[SESSION_KEY] = "1"
            clear_impersonation()
            assert SESSION_KEY not in session
