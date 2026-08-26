"""Unit tests for app.core.tenancy and app.core.permissions."""

import pytest
from app.core.permissions import any_role, role_required
from app.core.tenancy import current_school_id, get_school_or_404, scope_by_school
from app.extensions import db
from app.models.school import School
from app.models.user import User, UserRole, UserRoleLink
from flask_login import login_user
from tests.conftest import make_school, make_user


class TestScopeBySchool:
    def test_filters_by_school_id(self, app):
        with app.app_context():
            sid = make_school(app)
            make_user(app, "student", school_id=sid)
            # Scope query should return only users in that school
            result = scope_by_school(UserRoleLink, sid)
            assert result.count() >= 1

    def test_raises_without_school_column(self, app):
        with app.app_context():
            # School model has no school_id column
            with pytest.raises(ValueError, match="بلا عمود"):
                scope_by_school(School, 1, filter_key="school_id")


class TestCurrentSchoolId:
    def test_returns_none_for_unauthenticated(self, app):
        with app.app_context():
            with app.test_request_context():
                # Without login, current_user is anonymous
                assert current_school_id() is None


class TestRoleRequired:
    def test_allows_matching_role(self, app):
        with app.app_context():
            sid = make_school(app)
            uid = make_user(app, "school_admin", school_id=sid)

            with app.test_request_context():
                user = db.session.get(User, uid)
                login_user(user)

                @role_required(UserRole.school_admin)
                def protected():
                    return "ok"

                result = protected()
                assert result == "ok"

    def test_rejects_wrong_role(self, app):
        with app.app_context():
            sid = make_school(app)
            uid = make_user(app, "student", school_id=sid)

            with app.test_request_context():
                user = db.session.get(User, uid)
                login_user(user)

                @role_required(UserRole.school_admin)
                def protected():
                    return "ok"

                from werkzeug.exceptions import Forbidden

                with pytest.raises(Forbidden):
                    protected()

    def test_super_admin_passes_all_roles(self, app):
        with app.app_context():
            uid = make_user(app, "super_admin")

            with app.test_request_context():
                user = db.session.get(User, uid)
                login_user(user)

                @role_required(UserRole.teacher, UserRole.student)
                def protected():
                    return "ok"

                result = protected()
                assert result == "ok"


class TestAnyRole:
    def test_returns_true_for_matching(self, app):
        with app.app_context():
            sid = make_school(app)
            uid = make_user(app, "teacher", school_id=sid)

            with app.test_request_context():
                user = db.session.get(User, uid)
                login_user(user)
                assert any_role(UserRole.teacher) is True

    def test_returns_false_for_non_matching(self, app):
        with app.app_context():
            sid = make_school(app)
            uid = make_user(app, "student", school_id=sid)

            with app.test_request_context():
                user = db.session.get(User, uid)
                login_user(user)
                assert any_role(UserRole.teacher) is False


class TestGetSchoolOr404:
    def test_returns_existing_school(self, app):
        with app.app_context():
            sid = make_school(app)
            with app.test_request_context():
                # super_admin has current_school_id() = None, so no 403 check
                uid = make_user(app, "super_admin")
                user = db.session.get(User, uid)
                login_user(user)
                school = get_school_or_404(sid)
                assert school.id == sid

    def test_404_for_missing_school(self, app):
        with app.app_context():
            with app.test_request_context():
                from werkzeug.exceptions import NotFound

                uid = make_user(app, "super_admin")
                user = db.session.get(User, uid)
                login_user(user)
                with pytest.raises(NotFound):
                    get_school_or_404(999999)
