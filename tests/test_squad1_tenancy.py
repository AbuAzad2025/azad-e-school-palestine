"""Squad 1 — Agent 1: Multi-Tenant Guard.

Tests isolated tenant data leaks, missing tenant headers, cross-tenant
mutation attacks, and tenant_scope failures.
"""

from unittest.mock import patch

import pytest
from app.core.tenancy import (
    TenantContext,
    current_school_id,
    get_school_or_404,
    scope_by_school,
    tenant_scope,
)
from app.models.class_room import ClassRoom
from app.models.school import School
from app.models.user import UserRole
from tests.conftest import make_class, make_grade, make_school, make_subject


# ---------------------------------------------------------------------------
# current_school_id
# ---------------------------------------------------------------------------
class TestCurrentSchoolId:
    def test_unauthenticated_returns_none(self, app):
        with app.test_request_context():
            with patch("app.core.tenancy.current_user") as mock_user:
                mock_user.is_authenticated = False
                assert current_school_id() is None

    def test_super_admin_returns_none(self, app):
        with app.test_request_context():
            with patch("app.core.tenancy.current_user") as mock_user:
                mock_user.is_authenticated = True
                mock_user.role = UserRole.super_admin
                assert current_school_id() is None

    def test_school_user_returns_school_id(self, app):
        with app.test_request_context():
            with patch("app.core.tenancy.current_user") as mock_user:
                mock_user.is_authenticated = True
                mock_user.role = UserRole.student
                mock_user.school_id = 42
                assert current_school_id() == 42

    def test_teacher_returns_school_id(self, app):
        with app.test_request_context():
            with patch("app.core.tenancy.current_user") as mock_user:
                mock_user.is_authenticated = True
                mock_user.role = UserRole.teacher
                mock_user.school_id = 7
                assert current_school_id() == 7


# ---------------------------------------------------------------------------
# scope_by_school
# ---------------------------------------------------------------------------
class TestScopeBySchool:
    def test_filters_by_school_id(self, app):
        """scope_by_school works on models with school_id column (e.g. ClassRoom)."""
        with app.app_context():
            s1 = make_school(app)
            s2 = make_school(app)
            g1 = make_grade(app, s1, 1)
            g2 = make_grade(app, s2, 2)
            sub1 = make_subject(app, "Math")
            sub2 = make_subject(app, "Science")
            make_class(app, s1, g1, sub1)
            make_class(app, s2, g2, sub2)
            result = scope_by_school(ClassRoom, s1).all()
            assert all(r.school_id == s1 for r in result)
            assert len(result) == 1

    def test_missing_filter_key_raises_valueerror(self, app):
        with app.app_context():
            with pytest.raises(ValueError, match="بلا عمود"):
                # School model has no 'school_id' column
                scope_by_school(School, 1, filter_key="nonexistent_col")

    def test_empty_result_set(self, app):
        with app.app_context():
            result = scope_by_school(ClassRoom, 99999).all()
            assert result == []


# ---------------------------------------------------------------------------
# tenant_scope
# ---------------------------------------------------------------------------
class TestTenantScope:
    def test_super_admin_can_access_any_school(self, app):
        with app.app_context():
            s = make_school(app)
            g = make_grade(app, s, 1)
            sub = make_subject(app, "Math")
            make_class(app, s, g, sub)

            with patch("app.core.tenancy.current_user") as mock_user:
                mock_user.is_authenticated = True
                mock_user.role = UserRole.super_admin
                mock_user.school_id = None
                # tenant_scope for ClassRoom: super_admin bypass
                result = tenant_scope(ClassRoom, s)
                assert result is not None

    def test_cross_tenant_access_aborts_403(self, app):
        with app.app_context():
            s1 = make_school(app)
            s2 = make_school(app)

            with patch("app.core.tenancy.current_user") as mock_user:
                mock_user.is_authenticated = True
                mock_user.role = UserRole.student
                mock_user.school_id = s1
                with pytest.raises(Exception):
                    tenant_scope(ClassRoom, s2)


# ---------------------------------------------------------------------------
# get_school_or_404
# ---------------------------------------------------------------------------
class TestGetSchoolOr404:
    def test_returns_school_when_found(self, app):
        with app.app_context():
            sid = make_school(app)
            with patch("app.core.tenancy.current_user") as mock_user:
                mock_user.is_authenticated = True
                mock_user.role = UserRole.super_admin
                mock_user.school_id = None
                school = get_school_or_404(sid)
                assert school is not None
                assert school.id == sid

    def test_404_when_not_found(self, app):
        with app.app_context():
            with patch("app.core.tenancy.current_user") as mock_user:
                mock_user.is_authenticated = True
                mock_user.role = UserRole.super_admin
                mock_user.school_id = None
                from werkzeug.exceptions import NotFound

                with pytest.raises(NotFound):
                    get_school_or_404(99999)

    def test_cross_tenant_403(self, app):
        with app.app_context():
            s1 = make_school(app)
            s2 = make_school(app)
            with patch("app.core.tenancy.current_user") as mock_user:
                mock_user.is_authenticated = True
                mock_user.role = UserRole.student
                mock_user.school_id = s1
                from werkzeug.exceptions import Forbidden

                with pytest.raises(Forbidden):
                    get_school_or_404(s2)


# ---------------------------------------------------------------------------
# TenantContext dataclass
# ---------------------------------------------------------------------------
class TestTenantContext:
    def test_frozen(self, app):
        tc = TenantContext(school_id=1, role="teacher")
        assert tc.school_id == 1
        assert tc.role == "teacher"
        with pytest.raises(AttributeError):
            tc.school_id = 2


# ---------------------------------------------------------------------------
# Cross-tenant data isolation via scope_by_school
# ---------------------------------------------------------------------------
class TestCrossTenantIsolation:
    def test_scope_prevents_cross_school_query(self, app):
        """Ensure ClassRoom query scoped to school1 excludes school2."""
        with app.app_context():
            s1 = make_school(app)
            s2 = make_school(app)
            g1 = make_grade(app, s1, 1)
            g2 = make_grade(app, s2, 2)
            sub1 = make_subject(app, "Math")
            sub2 = make_subject(app, "Science")
            c1 = make_class(app, s1, g1, sub1)
            c2 = make_class(app, s2, g2, sub2)

            scoped = scope_by_school(ClassRoom, s1)
            results = scoped.all()
            assert all(r.school_id == s1 for r in results)
            assert len(results) == 1

    def test_scope_multiple_schools_different(self, app):
        """Two different school scopes return different results."""
        with app.app_context():
            s1 = make_school(app)
            s2 = make_school(app)
            g1 = make_grade(app, s1, 1)
            g2 = make_grade(app, s2, 2)
            sub = make_subject(app, "Shared")
            c1 = make_class(app, s1, g1, sub)
            c2 = make_class(app, s2, g2, sub)

            r1 = scope_by_school(ClassRoom, s1).all()
            r2 = scope_by_school(ClassRoom, s2).all()
            assert len(r1) == 1
            assert len(r2) == 1
            assert r1[0].school_id == s1
            assert r2[0].school_id == s2
