"""Squad 1 — Agent 3: RBAC & Permissions.

Tests all role matrix combinations (Admin, Teacher, Student, Parent, Anonymous)
across role_required and any_role.
"""

from unittest.mock import patch

import pytest
from app.core.permissions import SUPER_ROLE, _has_any, any_role, role_required
from app.models.user import UserRole


class TestRoleRequiredDecorator:
    """role_required must reject unauthenticated and unauthorized users."""

    def test_unauthenticated_returns_401(self, app):
        with app.app_context():
            with app.test_request_context():
                with patch("app.core.permissions.current_user") as mock_user:
                    mock_user.is_authenticated = False

                    @role_required(UserRole.teacher)
                    def protected():
                        return "ok"

                    with pytest.raises(Exception) as exc_info:
                        protected()
                    assert exc_info.value.code == 401

    def test_wrong_role_returns_403(self, app):
        with app.app_context():
            with app.test_request_context():
                with patch("app.core.permissions.current_user") as mock_user:
                    mock_user.is_authenticated = True
                    mock_user.role = UserRole.student

                    @role_required(UserRole.teacher)
                    def protected():
                        return "ok"

                    with pytest.raises(Exception) as exc_info:
                        protected()
                    assert exc_info.value.code == 403

    def test_correct_role_allows(self, app):
        with app.app_context():
            with app.test_request_context():
                with patch("app.core.permissions.current_user") as mock_user:
                    mock_user.is_authenticated = True
                    mock_user.role = UserRole.teacher

                    @role_required(UserRole.teacher)
                    def protected():
                        return "ok"

                    assert protected() == "ok"

    def test_super_admin_bypasses(self, app):
        with app.app_context():
            with app.test_request_context():
                with patch("app.core.permissions.current_user") as mock_user:
                    mock_user.is_authenticated = True
                    mock_user.role = UserRole.super_admin

                    @role_required(UserRole.teacher)
                    def protected():
                        return "ok"

                    assert protected() == "ok"

    def test_multiple_roles(self, app):
        with app.app_context():
            with app.test_request_context():
                for role in [UserRole.teacher, UserRole.student]:
                    with patch("app.core.permissions.current_user") as mock_user:
                        mock_user.is_authenticated = True
                        mock_user.role = role

                        @role_required(UserRole.teacher, UserRole.student)
                        def protected():
                            return "ok"

                        assert protected() == "ok"

    def test_parent_denied_when_not_in_roles(self, app):
        with app.app_context():
            with app.test_request_context():
                with patch("app.core.permissions.current_user") as mock_user:
                    mock_user.is_authenticated = True
                    mock_user.role = UserRole.parent

                    @role_required(UserRole.teacher)
                    def protected():
                        return "ok"

                    with pytest.raises(Exception) as exc_info:
                        protected()
                    assert exc_info.value.code == 403

    def test_school_admin_denied_for_teacher_only(self, app):
        with app.app_context():
            with app.test_request_context():
                with patch("app.core.permissions.current_user") as mock_user:
                    mock_user.is_authenticated = True
                    mock_user.role = UserRole.school_admin

                    @role_required(UserRole.teacher)
                    def protected():
                        return "ok"

                    with pytest.raises(Exception) as exc_info:
                        protected()
                    assert exc_info.value.code == 403


class TestAnyRole:
    """any_role returns bool for template/logic use."""

    def test_unauthenticated_returns_false(self, app):
        with app.app_context():
            with patch("app.core.permissions.current_user") as mock_user:
                mock_user.is_authenticated = False
                assert any_role(UserRole.teacher) is False

    def test_matching_role_returns_true(self, app):
        with app.app_context():
            with patch("app.core.permissions.current_user") as mock_user:
                mock_user.is_authenticated = True
                mock_user.role = UserRole.teacher
                assert any_role(UserRole.teacher) is True

    def test_non_matching_role_returns_false(self, app):
        with app.app_context():
            with patch("app.core.permissions.current_user") as mock_user:
                mock_user.is_authenticated = True
                mock_user.role = UserRole.student
                assert any_role(UserRole.teacher) is False

    def test_super_admin_always_true(self, app):
        with app.app_context():
            with patch("app.core.permissions.current_user") as mock_user:
                mock_user.is_authenticated = True
                mock_user.role = UserRole.super_admin
                assert any_role(UserRole.teacher) is True
                assert any_role(UserRole.student) is True
                assert any_role(UserRole.parent) is True
                assert any_role(UserRole.school_admin) is True

    def test_multiple_roles(self, app):
        with app.app_context():
            with patch("app.core.permissions.current_user") as mock_user:
                mock_user.is_authenticated = True
                mock_user.role = UserRole.teacher
                assert any_role(UserRole.teacher, UserRole.student) is True

                mock_user.role = UserRole.student
                assert any_role(UserRole.teacher, UserRole.student) is True

                mock_user.role = UserRole.parent
                assert any_role(UserRole.teacher, UserRole.student) is False


class TestHasAny:
    """Internal _has_any function."""

    def test_no_args_returns_false(self, app):
        with app.app_context():
            with patch("app.core.permissions.current_user") as mock_user:
                mock_user.is_authenticated = True
                mock_user.role = UserRole.student
                # _has_any with no roles
                assert _has_any() is False


class TestSuperRole:
    def test_super_role_is_super_admin(self, app):
        assert SUPER_ROLE == UserRole.super_admin
