"""SQUAD 2 EXTRA: Tests for email service, content service, impersonation."""

from app.models.user import User, UserRole
from app.services.content import (
    _sanitize_html,
    create_lesson,
    create_unit,
    get_lesson,
    list_units,
    publish_lesson,
    unpublish_lesson,
    update_lesson,
)
from app.services.email import (
    _dir,
    _fmt_date,
    _footer,
    _recipient_locale,
    send_welcome_email,
)
from app.services.impersonation import (
    SESSION_KEY,
    clear_impersonation,
    impersonator_user,
    is_impersonating,
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
    def _cid(self, app):
        """Create a valid class and return its ID."""
        from tests.conftest import make_class, make_grade, make_subject

        sid = make_school(app)
        tid = make_user(app, "teacher", school_id=sid)
        gid = make_grade(app, sid)
        subid = make_subject(app)
        cid = make_class(app, sid, gid, subid, teacher_id=tid)
        return cid

    def test_create_unit(self, app):
        with app.app_context():
            cid = self._cid(app)
            u = create_unit(cid, "Unit 1")
            assert u.title == "Unit 1"

    def test_list_units(self, app):
        with app.app_context():
            cid = self._cid(app)
            create_unit(cid, "Unit A")
            create_unit(cid, "Unit B")
            units = list_units(cid)
            assert len(units) == 2

    def test_create_lesson(self, app):
        with app.app_context():
            cid = self._cid(app)
            lesson, err = create_lesson(cid, "Lesson 1")
            assert err is None
            assert lesson.title == "Lesson 1"

    def test_create_lesson_empty_title(self, app):
        with app.app_context():
            cid = self._cid(app)
            lesson, err = create_lesson(cid, "")
            assert lesson is None

    def test_get_lesson(self, app):
        with app.app_context():
            cid = self._cid(app)
            lesson, _ = create_lesson(cid, "Test Lesson")
            fetched = get_lesson(lesson.id)
            assert fetched is not None

    def test_publish_unpublish(self, app):
        with app.app_context():
            cid = self._cid(app)
            lesson, _ = create_lesson(cid, "Draft Lesson")
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
            cid = self._cid(app)
            lesson, _ = create_lesson(cid, "Original")
            update_lesson(lesson, title="Updated", unit_id=None, body_html="<p>Body</p>")
            assert lesson.title == "Updated"


# ── Impersonation ──
class TestImpersonation:
    def test_not_impersonating(self, app):
        with app.test_request_context():
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
