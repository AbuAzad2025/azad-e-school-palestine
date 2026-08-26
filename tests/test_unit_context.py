"""Unit tests for app.core.context — template context helpers."""

from app.core.context import (
    ICON_NAMES,
    can_access_admin,
    can_manage_schools,
    has_any_role,
    has_role,
    icon,
    is_parent,
    is_school_admin,
    is_student,
    is_super_admin,
    is_teacher,
)
from app.extensions import db
from app.models.user import User, UserRole
from flask_login import login_user
from tests.conftest import make_school, make_user


class TestIcon:
    def test_valid_icon_name(self, app):
        with app.app_context():
            with app.test_request_context():
                result = icon("home")
                assert "icon-home" in result
                assert "svg" in result

    def test_unknown_icon_falls_back_to_check(self, app):
        with app.app_context():
            with app.test_request_context():
                result = icon("nonexistent_icon")
                assert "icon-check" in result

    def test_custom_class(self, app):
        with app.app_context():
            with app.test_request_context():
                result = icon("home", "custom-class")
                assert "custom-class" in result

    def test_all_icon_names_are_strings(self):
        for name in ICON_NAMES:
            assert isinstance(name, str)

    def test_icon_names_not_empty(self):
        assert len(ICON_NAMES) > 0


class TestHasRole:
    def test_matching_role(self, app):
        with app.app_context():
            uid = make_user(app, "student")
            with app.test_request_context():
                user = db.session.get(User, uid)
                login_user(user)
                assert has_role(UserRole.student) is True

    def test_non_matching_role(self, app):
        with app.app_context():
            uid = make_user(app, "student")
            with app.test_request_context():
                user = db.session.get(User, uid)
                login_user(user)
                assert has_role(UserRole.teacher) is False

    def test_string_role(self, app):
        with app.app_context():
            uid = make_user(app, "teacher")
            with app.test_request_context():
                user = db.session.get(User, uid)
                login_user(user)
                assert has_role("teacher") is True

    def test_unauthenticated(self, app):
        with app.app_context():
            with app.test_request_context():
                assert has_role(UserRole.student) is False


class TestHasAnyRole:
    def test_matches_one_of_many(self, app):
        with app.app_context():
            uid = make_user(app, "teacher")
            with app.test_request_context():
                user = db.session.get(User, uid)
                login_user(user)
                assert has_any_role(UserRole.teacher, UserRole.student) is True

    def test_no_match(self, app):
        with app.app_context():
            uid = make_user(app, "student")
            with app.test_request_context():
                user = db.session.get(User, uid)
                login_user(user)
                assert has_any_role(UserRole.teacher, UserRole.parent) is False


class TestRoleChecks:
    def test_is_super_admin(self, app):
        with app.app_context():
            uid = make_user(app, "super_admin")
            with app.test_request_context():
                user = db.session.get(User, uid)
                login_user(user)
                assert is_super_admin() is True
                assert is_student() is False

    def test_is_student(self, app):
        with app.app_context():
            uid = make_user(app, "student")
            with app.test_request_context():
                user = db.session.get(User, uid)
                login_user(user)
                assert is_student() is True

    def test_is_teacher(self, app):
        with app.app_context():
            uid = make_user(app, "teacher")
            with app.test_request_context():
                user = db.session.get(User, uid)
                login_user(user)
                assert is_teacher() is True

    def test_is_school_admin(self, app):
        with app.app_context():
            sid = make_school(app)
            uid = make_user(app, "school_admin", school_id=sid)
            with app.test_request_context():
                user = db.session.get(User, uid)
                login_user(user)
                assert is_school_admin() is True

    def test_is_parent(self, app):
        with app.app_context():
            uid = make_user(app, "parent")
            with app.test_request_context():
                user = db.session.get(User, uid)
                login_user(user)
                assert is_parent() is True


class TestAccessChecks:
    def test_can_access_admin(self, app):
        with app.app_context():
            uid = make_user(app, "super_admin")
            with app.test_request_context():
                user = db.session.get(User, uid)
                login_user(user)
                assert can_access_admin() is True

    def test_can_manage_schools(self, app):
        with app.app_context():
            uid = make_user(app, "super_admin")
            with app.test_request_context():
                user = db.session.get(User, uid)
                login_user(user)
                assert can_manage_schools() is True

    def test_student_cannot_manage_schools(self, app):
        with app.app_context():
            uid = make_user(app, "student")
            with app.test_request_context():
                user = db.session.get(User, uid)
                login_user(user)
                assert can_manage_schools() is False

    def test_unauthenticated_cannot_access_admin(self, app):
        with app.app_context():
            with app.test_request_context():
                assert can_access_admin() is False
