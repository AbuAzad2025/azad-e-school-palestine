"""Squad 1 — Agent 2: Auth & Session Specialist.

Tests session invalidation (password_changed_at), expired tokens,
invalid JWTs, refresh loops, brute force lockout, and login flows.
"""

import pytest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch, MagicMock

from app.core.db import tx
from app.core.security import (
    hash_password,
    verify_password,
    validate_password_policy,
    check_password_reuse,
    COMMON_PASSWORDS,
)
from app.core.tokens import make_reset_token, read_reset_token, make_token, read_token
from app.extensions import db
from app.models.user import User, UserRole, UserApprovalStatus, UserRoleLink
from app.services.auth import (
    authenticate,
    mark_login,
    register_user,
    request_password_reset,
    reset_password,
    confirm_email,
    is_current,
    register_individual,
)
from tests.conftest import make_school, make_user


# ---------------------------------------------------------------------------
# authenticate — Brute force & lockout
# ---------------------------------------------------------------------------
class TestAuthenticateLockout:
    def test_failed_attempt_increments_count(self, app):
        with app.app_context():
            sid = make_school(app)
            uid = make_user(app, "student", school_id=sid)
            user_obj = db.session.get(User, uid)

            user, error = authenticate(user_obj.email, "WrongPass123!")
            assert user is None
            db.session.refresh(user_obj)
            assert user_obj.failed_login_attempts == 1

    def test_multiple_failed_attempts_lock_account(self, app):
        with app.app_context():
            sid = make_school(app)
            uid = make_user(app, "student", school_id=sid)
            user_obj = db.session.get(User, uid)

            for i in range(5):
                user, error = authenticate(user_obj.email, "WrongPass123!")
                assert user is None

            db.session.refresh(user_obj)
            assert user_obj.failed_login_attempts >= 5
            assert user_obj.locked_until is not None
            assert user_obj.locked_until > datetime.now(UTC)

    def test_locked_account_rejects_correct_password(self, app):
        with app.app_context():
            sid = make_school(app)
            uid = make_user(app, "student", school_id=sid)
            user_obj = db.session.get(User, uid)

            # Lock the account
            user_obj.failed_login_attempts = 5
            user_obj.locked_until = datetime.now(UTC) + timedelta(minutes=15)
            db.session.commit()

            user, error = authenticate(user_obj.email, "TestPass123!")
            assert user is None
            assert "مقفل" in error

    def test_successful_login_resets_failed_attempts(self, app):
        with app.app_context():
            sid = make_school(app)
            uid = make_user(app, "student", school_id=sid)
            user_obj = db.session.get(User, uid)

            user_obj.failed_login_attempts = 3
            db.session.commit()

            user, error = authenticate(user_obj.email, "TestPass123!")
            assert user is not None
            # authenticate() modifies user in-memory; reset is committed via mark_login
            assert user.failed_login_attempts == 0

    def test_inactive_user_rejected(self, app):
        with app.app_context():
            sid = make_school(app)
            uid = make_user(app, "student", school_id=sid)
            user_obj = db.session.get(User, uid)

            user_obj.is_active = False
            db.session.commit()

            user, error = authenticate(user_obj.email, "TestPass123!")
            assert user is None
            assert "معطّل" in error

    def test_pending_approval_rejected(self, app):
        with app.app_context():
            sid = make_school(app)
            uid = make_user(app, "student", school_id=sid, approved=False)
            user_obj = db.session.get(User, uid)

            user, error = authenticate(user_obj.email, "TestPass123!")
            assert user is None
            assert "انتظار" in error


# ---------------------------------------------------------------------------
# Session invalidation via password_changed_at
# ---------------------------------------------------------------------------
class TestSessionInvalidation:
    def test_password_change_invalidates_old_session_id(self, app):
        """After password change, get_id() returns different stamp → old session invalid."""
        with app.app_context():
            sid = make_school(app)
            uid = make_user(app, "student", school_id=sid)
            user_obj = db.session.get(User, uid)

            old_id = user_obj.get_id()

            user_obj.password_changed_at = datetime.now(UTC)
            db.session.commit()

            new_id = user_obj.get_id()
            assert old_id != new_id

    def test_get_id_includes_timestamp(self, app):
        with app.app_context():
            sid = make_school(app)
            uid = make_user(app, "student", school_id=sid)
            user_obj = db.session.get(User, uid)

            user_obj.password_changed_at = datetime(2026, 1, 1, tzinfo=UTC)
            db.session.commit()
            user_obj2 = db.session.get(User, uid)
            session_id = user_obj2.get_id()
            assert "2026" in session_id

    def test_get_id_without_password_changed_at(self, app):
        with app.app_context():
            sid = make_school(app)
            uid = make_user(app, "student", school_id=sid)
            user_obj = db.session.get(User, uid)
            assert user_obj.password_changed_at is None
            session_id = user_obj.get_id()
            assert str(uid) in session_id


# ---------------------------------------------------------------------------
# reset_password — one-time token reuse
# ---------------------------------------------------------------------------
class TestResetPasswordOneTime:
    def test_token_reuse_after_password_change(self, app):
        """Token becomes invalid after first use (password_changed_at changes)."""
        with app.app_context():
            sid = make_school(app)
            uid = make_user(app, "student", school_id=sid)
            user_obj = db.session.get(User, uid)

            token = make_reset_token(uid, user_obj.email, user_obj.password_changed_at)
            error = reset_password(token, "NewStr0ng!Pass1")
            assert error is None

            # Try to reuse same token
            error2 = reset_password(token, "AnotherStr0ng!Pass2")
            assert error2 is not None

    def test_token_with_wrong_pc_stamp_fails(self, app):
        """Token with stale password_changed_at should fail."""
        with app.app_context():
            sid = make_school(app)
            uid = make_user(app, "student", school_id=sid)
            user_obj = db.session.get(User, uid)

            # Token created with old timestamp
            old_ts = datetime(2020, 1, 1, tzinfo=UTC)
            token = make_reset_token(uid, user_obj.email, old_ts)

            # User's actual pc is None
            error = reset_password(token, "NewStr0ng!Pass1")
            assert error is not None

    def test_reset_with_valid_token_new_password(self, app):
        with app.app_context():
            sid = make_school(app)
            uid = make_user(app, "student", school_id=sid)
            user_obj = db.session.get(User, uid)

            token = make_reset_token(uid, user_obj.email, user_obj.password_changed_at)
            error = reset_password(token, "BrandNewStr0ng!1")
            assert error is None

            # Verify new password works
            user_obj2 = db.session.get(User, uid)
            assert verify_password(user_obj2.password_hash, "BrandNewStr0ng!1")

    def test_reset_with_invalid_token(self, app):
        with app.app_context():
            error = reset_password("completely-invalid-token", "AnyPass123!")
            assert error is not None

    def test_reset_with_expired_token(self, app):
        with app.app_context():
            sid = make_school(app)
            uid = make_user(app, "student", school_id=sid)
            user_obj = db.session.get(User, uid)

            token = make_reset_token(uid, user_obj.email, user_obj.password_changed_at)
            # max_age=-1 means already expired
            r_uid, r_email, r_pc = read_reset_token(token, max_age_seconds=-1)
            assert r_uid is None

    def test_reset_nonexistent_user(self, app):
        with app.app_context():
            token = make_reset_token(99999, "ghost@test.com", None)
            error = reset_password(token, "SomePass123!")
            assert error is not None


# ---------------------------------------------------------------------------
# register_user — validation
# ---------------------------------------------------------------------------
class TestRegisterUserValidation:
    def test_register_duplicate_email(self, app):
        with app.app_context():
            sid = make_school(app)
            make_user(app, "student", school_id=sid, email="dup@test.com")
            user, error = register_user("dup@test.com", "Another", "student", "StrongP@ss1")
            assert user is None
            assert error is not None

    def test_register_invalid_role(self, app):
        with app.app_context():
            user, error = register_user("bad@test.com", "Hacker", "hacker", "StrongP@ss1")
            assert user is None

    def test_register_weak_password(self, app):
        with app.app_context():
            user, error = register_user("weak@test.com", "Weak", "student", "123")
            assert user is None

    def test_register_with_invalid_join_code(self, app):
        with app.app_context():
            user, error = register_user(
                "fail@test.com", "Student", "student", "StrongP@ss1",
                school_join_code="WRONG"
            )
            assert user is None

    def test_register_adds_password_to_history(self, app):
        with app.app_context():
            user, error = register_user("hist@test.com", "Student", "student", "StrongP@ss1")
            assert user is not None
            assert len(user.password_history) >= 1


# ---------------------------------------------------------------------------
# mark_login
# ---------------------------------------------------------------------------
class TestMarkLogin:
    def test_sets_last_login_at(self, app):
        with app.app_context():
            sid = make_school(app)
            uid = make_user(app, "student", school_id=sid)
            user_obj = db.session.get(User, uid)
            mark_login(user_obj)
            db.session.refresh(user_obj)
            assert user_obj.last_login_at is not None
            assert user_obj.failed_login_attempts == 0


# ---------------------------------------------------------------------------
# is_current
# ---------------------------------------------------------------------------
class TestIsCurrent:
    def test_is_current_true(self, app):
        with app.app_context():
            sid = make_school(app)
            uid = make_user(app, "student", school_id=sid)
            user_obj = db.session.get(User, uid)

            with app.test_request_context():
                from flask_login import LoginManager
                with patch("app.services.auth.current_user") as mock_user:
                    mock_user.is_authenticated = True
                    mock_user.id = uid
                    assert is_current(user_obj) is True

    def test_is_current_false_different_user(self, app):
        with app.app_context():
            sid = make_school(app)
            uid = make_user(app, "student", school_id=sid)
            user_obj = db.session.get(User, uid)

            with app.test_request_context():
                with patch("app.services.auth.current_user") as mock_user:
                    mock_user.is_authenticated = True
                    mock_user.id = uid + 999
                    assert is_current(user_obj) is False

    def test_is_current_unauthenticated(self, app):
        with app.app_context():
            sid = make_school(app)
            uid = make_user(app, "student", school_id=sid)
            user_obj = db.session.get(User, uid)

            with app.test_request_context():
                with patch("app.services.auth.current_user") as mock_user:
                    mock_user.is_authenticated = False
                    assert is_current(user_obj) is False


# ---------------------------------------------------------------------------
# confirm_email
# ---------------------------------------------------------------------------
class TestConfirmEmail:
    def test_valid_token_confirms(self, app):
        with app.app_context():
            sid = make_school(app)
            uid = make_user(app, "student", school_id=sid)
            user_obj = db.session.get(User, uid)
            token = make_token(uid, user_obj.email, "azad-email-confirm")
            result = confirm_email(uid, token)
            assert result is True
            db.session.refresh(user_obj)
            assert user_obj.is_verified is True

    def test_invalid_token_fails(self, app):
        with app.app_context():
            result = confirm_email(1, "bad-token")
            assert result is False

    def test_mismatched_uid_fails(self, app):
        with app.app_context():
            sid = make_school(app)
            uid = make_user(app, "student", school_id=sid)
            user_obj = db.session.get(User, uid)
            token = make_token(uid, user_obj.email, "azad-email-confirm")
            result = confirm_email(uid + 999, token)
            assert result is False

    def test_nonexistent_user_fails(self, app):
        with app.app_context():
            sid = make_school(app)
            uid = make_user(app, "student", school_id=sid)
            user_obj = db.session.get(User, uid)
            token = make_token(uid, user_obj.email, "azad-email-confirm")
            # Delete user
            db.session.delete(user_obj)
            db.session.commit()
            result = confirm_email(uid, token)
            assert result is False


# ---------------------------------------------------------------------------
# request_password_reset
# ---------------------------------------------------------------------------
class TestRequestPasswordReset:
    def test_returns_token_for_existing_user(self, app):
        with app.app_context():
            sid = make_school(app)
            uid = make_user(app, "student", school_id=sid)
            user_obj = db.session.get(User, uid)
            token = request_password_reset(user_obj.email)
            assert token is not None

    def test_returns_none_for_unknown_email(self, app):
        with app.app_context():
            token = request_password_reset("unknown@test.com")
            assert token is None

    def test_case_insensitive_email(self, app):
        with app.app_context():
            sid = make_school(app)
            uid = make_user(app, "student", school_id=sid, email="User@Test.COM")
            token = request_password_reset("user@test.com")
            assert token is not None


# ---------------------------------------------------------------------------
# register_individual
# ---------------------------------------------------------------------------
class TestRegisterIndividual:
    def test_register_creates_individual_user(self, app):
        with app.app_context():
            user, error = register_individual("ind@test.com", "Individual", "StrongP@ss1")
            assert error is None
            assert user is not None
            assert user.is_individual is True
            assert user.approval_status == UserApprovalStatus.approved
            assert user.is_verified is True

    def test_duplicate_email_rejected(self, app):
        with app.app_context():
            register_individual("ind@test.com", "First", "StrongP@ss1")
            user2, error = register_individual("ind@test.com", "Second", "StrongP@ss1")
            assert user2 is None

    def test_weak_password_rejected(self, app):
        with app.app_context():
            user, error = register_individual("weak@test.com", "Weak", "123")
            assert user is None


# ---------------------------------------------------------------------------
# User model methods
# ---------------------------------------------------------------------------
class TestUserModel:
    def test_is_locked_future(self, app):
        with app.app_context():
            sid = make_school(app)
            uid = make_user(app, "student", school_id=sid)
            user_obj = db.session.get(User, uid)
            user_obj.locked_until = datetime.now(UTC) + timedelta(hours=1)
            db.session.commit()
            assert user_obj.is_locked() is True

    def test_is_locked_past(self, app):
        with app.app_context():
            sid = make_school(app)
            uid = make_user(app, "student", school_id=sid)
            user_obj = db.session.get(User, uid)
            user_obj.locked_until = datetime.now(UTC) - timedelta(hours=1)
            db.session.commit()
            assert user_obj.is_locked() is False

    def test_increment_failed_login(self, app):
        with app.app_context():
            sid = make_school(app)
            uid = make_user(app, "student", school_id=sid)
            user_obj = db.session.get(User, uid)
            user_obj.increment_failed_login(max_attempts=5, lockout_minutes=15)
            assert user_obj.failed_login_attempts == 1
            assert user_obj.locked_until is None

    def test_increment_locks_at_max(self, app):
        with app.app_context():
            sid = make_school(app)
            uid = make_user(app, "student", school_id=sid)
            user_obj = db.session.get(User, uid)
            user_obj.failed_login_attempts = 4
            user_obj.increment_failed_login(max_attempts=5, lockout_minutes=15)
            assert user_obj.failed_login_attempts == 5
            assert user_obj.locked_until is not None

    def test_reset_failed_login(self, app):
        with app.app_context():
            sid = make_school(app)
            uid = make_user(app, "student", school_id=sid)
            user_obj = db.session.get(User, uid)
            user_obj.failed_login_attempts = 3
            user_obj.locked_until = datetime.now(UTC)
            user_obj.reset_failed_login()
            assert user_obj.failed_login_attempts == 0
            assert user_obj.locked_until is None

    def test_add_password_to_history(self, app):
        with app.app_context():
            sid = make_school(app)
            uid = make_user(app, "student", school_id=sid)
            user_obj = db.session.get(User, uid)
            h1 = hash_password("Pass1")
            h2 = hash_password("Pass2")
            user_obj.add_password_to_history(h1)
            user_obj.add_password_to_history(h2)
            assert h1 in user_obj.password_history
            assert h2 in user_obj.password_history

    def test_add_password_to_history_no_duplicates(self, app):
        with app.app_context():
            sid = make_school(app)
            uid = make_user(app, "student", school_id=sid)
            user_obj = db.session.get(User, uid)
            h = hash_password("Pass1")
            user_obj.add_password_to_history(h)
            user_obj.add_password_to_history(h)
            assert user_obj.password_history.count(h) == 1

    def test_add_password_to_history_trims(self, app):
        with app.app_context():
            sid = make_school(app)
            uid = make_user(app, "student", school_id=sid)
            user_obj = db.session.get(User, uid)
            hashes = [hash_password(f"Pass{i}") for i in range(10)]
            for h in hashes:
                user_obj.add_password_to_history(h, history_count=5)
            assert len(user_obj.password_history) == 5

    def test_is_approved_property(self, app):
        with app.app_context():
            sid = make_school(app)
            uid = make_user(app, "student", school_id=sid, approved=True)
            user_obj = db.session.get(User, uid)
            assert user_obj.is_approved is True

    def test_is_approved_not_active(self, app):
        with app.app_context():
            sid = make_school(app)
            uid = make_user(app, "student", school_id=sid, approved=True)
            user_obj = db.session.get(User, uid)
            user_obj.is_active = False
            assert user_obj.is_approved is False

    def test_is_approved_pending(self, app):
        with app.app_context():
            sid = make_school(app)
            uid = make_user(app, "student", school_id=sid, approved=False)
            user_obj = db.session.get(User, uid)
            assert user_obj.is_approved is False

    def test_school_id_from_role_link(self, app):
        with app.app_context():
            sid = make_school(app)
            uid = make_user(app, "student", school_id=sid)
            user_obj = db.session.get(User, uid)
            assert user_obj.school_id == sid

    def test_school_id_none_for_no_links(self, app):
        with app.app_context():
            uid = make_user(app, "super_admin")
            user_obj = db.session.get(User, uid)
            assert user_obj.school_id is None

    def test_belongs_to_school_true(self, app):
        with app.app_context():
            sid = make_school(app)
            uid = make_user(app, "student", school_id=sid)
            user_obj = db.session.get(User, uid)
            assert user_obj.belongs_to_school is True

    def test_belongs_to_school_false_no_links(self, app):
        with app.app_context():
            uid = make_user(app, "student")
            user_obj = db.session.get(User, uid)
            assert user_obj.belongs_to_school is False
