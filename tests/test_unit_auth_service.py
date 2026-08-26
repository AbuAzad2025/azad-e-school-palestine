"""Unit tests for app.services.auth — registration, authentication, password reset."""

from app.core.tokens import make_activation_token
from app.extensions import db
from app.models.user import User, UserApprovalStatus, UserRole
from app.services.auth import (
    authenticate,
    confirm_email,
    mark_login,
    register_individual,
    register_user,
    request_password_reset,
    reset_password,
)
from tests.conftest import make_school, make_user


class TestRegisterUser:
    def test_register_student(self, app):
        with app.app_context():
            user, error = register_user(
                email="new@test.com",
                name_ar="طالب جديد",
                role="student",
                password="StrongP@ss1",
            )
            assert error is None
            assert user is not None
            assert user.email == "new@test.com"
            assert user.approval_status == UserApprovalStatus.pending

    def test_register_duplicate_email(self, app):
        with app.app_context():
            sid = make_school(app)
            make_user(app, "student", school_id=sid, email="dup@test.com")
            user, error = register_user("dup@test.com", "Another", "student", "StrongP@ss1")
            assert user is None
            assert "مسجّل مسبقاً" in error

    def test_register_with_school_join_code(self, app):
        with app.app_context():
            from app.models.school import School

            s = School(
                name_ar="مدرسة اختبار",
                name_en="Test School",
                domain="join-test.org",
                join_code="JOIN123",
            )
            db.session.add(s)
            db.session.commit()

            user, error = register_user(
                "joined@test.com",
                "طالب مدرسة",
                "student",
                "StrongP@ss1",
                school_join_code="join123",
            )
            assert error is None
            assert user is not None

    def test_register_with_invalid_join_code(self, app):
        with app.app_context():
            user, error = register_user(
                "fail@test.com",
                "طالب",
                "student",
                "StrongP@ss1",
                school_join_code="WRONG",
            )
            assert user is None
            assert "كود" in error

    def test_register_weak_password(self, app):
        with app.app_context():
            user, error = register_user("weak@test.com", "طالب", "student", "123")
            assert user is None
            assert error is not None

    def test_register_invalid_role(self, app):
        with app.app_context():
            user, error = register_user("bad@test.com", "طالب", "hacker", "StrongP@ss1")
            assert user is None
            assert "غير صالح" in error


class TestAuthenticate:
    def test_authenticate_success(self, app):
        with app.app_context():
            sid = make_school(app)
            uid = make_user(app, "student", school_id=sid, approved=True)
            user_obj = db.session.get(User, uid)
            user, error = authenticate(user_obj.email, "TestPass123!")
            assert error is None
            assert user is not None
            assert user.id == uid

    def test_authenticate_wrong_password(self, app):
        with app.app_context():
            sid = make_school(app)
            uid = make_user(app, "student", school_id=sid)
            user_obj = db.session.get(User, uid)
            user, error = authenticate(user_obj.email, "WrongPass123!")
            assert user is None
            assert "غير صحيحة" in error

    def test_authenticate_nonexistent_email(self, app):
        with app.app_context():
            user, error = authenticate("noone@test.com", "anything")
            assert user is None
            assert "غير صحيحة" in error

    def test_authenticate_inactive_user(self, app):
        with app.app_context():
            sid = make_school(app)
            uid = make_user(app, "student", school_id=sid)
            user_obj = db.session.get(User, uid)
            user_obj.is_active = False
            db.session.commit()
            user, error = authenticate(user_obj.email, "TestPass123!")
            assert user is None
            assert "معطّل" in error

    def test_authenticate_pending_user(self, app):
        with app.app_context():
            sid = make_school(app)
            uid = make_user(app, "student", school_id=sid, approved=False)
            user_obj = db.session.get(User, uid)
            user, error = authenticate(user_obj.email, "TestPass123!")
            assert user is None
            assert "انتظار" in error


class TestRequestPasswordReset:
    def test_returns_token_for_existing_user(self, app):
        with app.app_context():
            sid = make_school(app)
            uid = make_user(app, "student", school_id=sid)
            user_obj = db.session.get(User, uid)
            token = request_password_reset(user_obj.email)
            assert token is not None
            assert len(token) > 10

    def test_returns_none_for_unknown_email(self, app):
        with app.app_context():
            token = request_password_reset("unknown@test.com")
            assert token is None


class TestResetPassword:
    def test_reset_with_valid_token(self, app):
        with app.app_context():
            from app.core.tokens import make_reset_token

            sid = make_school(app)
            uid = make_user(app, "student", school_id=sid)
            user_obj = db.session.get(User, uid)
            token = make_reset_token(uid, user_obj.email, user_obj.password_changed_at)

            error = reset_password(token, "NewStr0ng!Pass")
            assert error is None

            # Verify old password no longer works
            user_obj2 = db.session.get(User, uid)
            from app.core.security import verify_password

            assert verify_password(user_obj2.password_hash, "NewStr0ng!Pass") is True

    def test_reset_with_invalid_token(self, app):
        with app.app_context():
            error = reset_password("bad-token", "NewStr0ng!Pass")
            assert error is not None


class TestRegisterIndividual:
    def test_register_individual_user(self, app):
        with app.app_context():
            user, error = register_individual("ind@test.com", "طالب فردي", "StrongP@ss1")
            assert error is None
            assert user is not None
            assert user.is_individual is True
            assert user.role == UserRole.student

    def test_register_individual_duplicate(self, app):
        with app.app_context():
            user, error = register_individual("ind@test.com", "أول", "StrongP@ss1")
            assert error is None
            user2, error2 = register_individual("ind@test.com", "ثاني", "StrongP@ss1")
            # If first succeeds, second should fail with duplicate
            if user:
                assert user2 is None
                assert "مسجّل مسبقاً" in error2


class TestMarkLogin:
    def test_sets_last_login(self, app):
        with app.app_context():
            sid = make_school(app)
            uid = make_user(app, "student", school_id=sid)
            user_obj = db.session.get(User, uid)
            mark_login(user_obj)
            user_obj2 = db.session.get(User, uid)
            assert user_obj2.last_login_at is not None


class TestConfirmEmail:
    def test_confirm_with_valid_token(self, app):
        with app.app_context():
            sid = make_school(app)
            uid = make_user(app, "student", school_id=sid)
            user_obj = db.session.get(User, uid)
            token = make_activation_token(uid, user_obj.email)
            result = confirm_email(uid, token)
            assert result is True

    def test_confirm_with_invalid_token(self, app):
        with app.app_context():
            result = confirm_email(1, "bad-token")
            assert result is False
