"""Unit tests for app.core.tenancy and app.core.permissions."""

import pytest
from app.core.permissions import any_role, role_required
from app.core.tenancy import current_school_id, get_school_or_404, scope_by_school
from app.extensions import db
from app.models.school import School
from app.models.user import User, UserRole, UserRoleLink
from flask_login import login_user
from tests.conftest import make_school, make_user
from werkzeug.exceptions import Forbidden


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

    def test_cross_school_403(self, app):
        """Student from school A cannot access school B."""
        with app.app_context():
            sid_a = make_school(app)
            sid_b = make_school(app)
            uid = make_user(app, "student", school_id=sid_a)
            with app.test_request_context():
                user = db.session.get(User, uid)
                login_user(user)
                from werkzeug.exceptions import Forbidden

                with pytest.raises(Forbidden):
                    get_school_or_404(sid_b)


class TestTenantScope:
    def test_allows_matching_school(self, app):
        """Student can scope to their own school."""
        with app.app_context():
            sid = make_school(app)
            uid = make_user(app, "student", school_id=sid)
            with app.test_request_context():
                user = db.session.get(User, uid)
                login_user(user)
                from app.core.tenancy import tenant_scope

                result = tenant_scope(UserRoleLink, sid)
                assert result.count() >= 1

    def test_cross_school_403(self, app):
        """Student from school A cannot scope school B."""
        with app.app_context():
            sid_a = make_school(app)
            sid_b = make_school(app)
            uid = make_user(app, "student", school_id=sid_a)
            with app.test_request_context():
                user = db.session.get(User, uid)
                login_user(user)
                from app.core.tenancy import tenant_scope

                with pytest.raises(Forbidden):
                    tenant_scope(UserRoleLink, sid_b)

    def test_super_admin_bypasses_tenant_scope(self, app):
        """super_admin (school_id=None) can access any school."""
        with app.app_context():
            sid = make_school(app)
            uid = make_user(app, "super_admin")
            with app.test_request_context():
                user = db.session.get(User, uid)
                login_user(user)
                from app.core.tenancy import tenant_scope

                result = tenant_scope(UserRoleLink, sid)
                assert result.count() >= 0  # no 403 raised


class TestRoleRequiredEdgeCases:
    def test_unauthenticated_returns_401(self, app):
        with app.app_context():
            with app.test_request_context():
                @role_required(UserRole.teacher)
                def protected():
                    return "ok"

                from werkzeug.exceptions import Unauthorized

                with pytest.raises(Unauthorized):
                    protected()

    def test_role_required_with_multiple_roles(self, app):
        """Teacher OR student should pass."""
        with app.app_context():
            uid = make_user(app, "teacher")
            with app.test_request_context():
                user = db.session.get(User, uid)
                login_user(user)

                @role_required(UserRole.teacher, UserRole.student)
                def protected():
                    return "ok"

                assert protected() == "ok"

    def test_role_required_rejects_non_matching_in_multi(self, app):
        """Parent should be rejected when only teacher/student allowed."""
        with app.app_context():
            uid = make_user(app, "parent")
            with app.test_request_context():
                user = db.session.get(User, uid)
                login_user(user)

                @role_required(UserRole.teacher, UserRole.student)
                def protected():
                    return "ok"

                with pytest.raises(Forbidden):
                    protected()


class TestAnyRoleEdgeCases:
    def test_any_role_unauthenticated(self, app):
        with app.app_context():
            with app.test_request_context():
                assert any_role(UserRole.student) is False

    def test_any_role_super_admin_matches_any(self, app):
        with app.app_context():
            uid = make_user(app, "super_admin")
            with app.test_request_context():
                user = db.session.get(User, uid)
                login_user(user)
                assert any_role(UserRole.teacher, UserRole.student, UserRole.parent) is True
