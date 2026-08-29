"""Squad 4 — Agent 18: Database Transaction Rollbacks.

Force SQLAlchemy errors mid-operation to verify db.session.rollback()
execution and session cleanup.
"""

import pytest
from app.core.db import TxError, tx
from app.core.security import hash_password
from app.extensions import db
from app.models.school import School
from app.models.user import User, UserRole
from sqlalchemy.exc import SQLAlchemyError


class TestTxFunction:
    """Test the tx() transaction wrapper."""

    def test_successful_commit(self, app):
        with app.app_context():

            def create_school():
                s = School(name_ar="TX School", name_en="TX School")
                db.session.add(s)
                return s

            result = tx(create_school)
            assert result is not None
            assert result.name_ar == "TX School"
            assert db.session.get(School, result.id) is not None

    def test_rollback_on_sqlalchemy_error(self, app):
        with app.app_context():
            call_count = 0

            def failing_operation():
                nonlocal call_count
                call_count += 1
                # First call succeeds in creating object, second call fails
                s = School(name_ar="Fail School")
                db.session.add(s)
                db.session.flush()
                # Force a SQLAlchemy error
                raise SQLAlchemyError("Simulated DB error")

            with pytest.raises(SQLAlchemyError):
                tx(failing_operation)

            # Verify rollback happened - school should not exist
            schools = School.query.filter_by(name_ar="Fail School").all()
            assert len(schools) == 0

    def test_rollback_on_generic_exception(self, app):
        with app.app_context():

            def failing_operation():
                s = School(name_ar="Generic Fail")
                db.session.add(s)
                db.session.flush()
                raise ValueError("Simulated logic error")

            with pytest.raises(ValueError):
                tx(failing_operation)

            schools = School.query.filter_by(name_ar="Generic Fail").all()
            assert len(schools) == 0

    def test_tx_error_propagation(self, app):
        with app.app_context():

            def raise_tx_error():
                raise TxError("Business logic error")

            with pytest.raises(TxError):
                tx(raise_tx_error)


class TestTransactionIntegrity:
    """Verify transactions maintain data integrity on rollback."""

    def test_partial_write_rollback(self, app):
        """Verify that a failed transaction doesn't leave partial data."""
        with app.app_context():

            def create_then_fail():
                s1 = School(name_ar="Good School")
                db.session.add(s1)
                db.session.flush()
                raise SQLAlchemyError("Force rollback")

            with pytest.raises(SQLAlchemyError):
                tx(create_then_fail)

            # Good School should not exist
            assert School.query.filter_by(name_ar="Good School").count() == 0

    def test_multiple_operations_rollback(self, app):
        """Multiple DB operations in one tx should all rollback on failure."""
        with app.app_context():

            def multi_op():
                s = School(name_ar="Multi School")
                db.session.add(s)
                db.session.flush()
                u = User(
                    email="multi@test.com",
                    name_ar="Multi User",
                    role=UserRole.student,
                    password_hash=hash_password("Test123!"),
                )
                db.session.add(u)
                db.session.flush()
                raise SQLAlchemyError("Force rollback")

            with pytest.raises(SQLAlchemyError):
                tx(multi_op)

            assert School.query.filter_by(name_ar="Multi School").count() == 0
            assert User.query.filter_by(email="multi@test.com").count() == 0

    def test_session_clean_after_rollback(self, app):
        """After a rollback, the session should be usable for new operations."""
        with app.app_context():

            def failing():
                raise SQLAlchemyError("Error")

            with pytest.raises(SQLAlchemyError):
                tx(failing)

            # Session should still work
            s = School(name_ar="After Rollback")
            db.session.add(s)
            db.session.commit()
            assert s.id is not None


class TestTxErrorClass:
    def test_tx_error_is_exception(self):
        err = TxError("test")
        assert isinstance(err, Exception)
        assert str(err) == "test"

    def test_tx_error_catchable(self):
        try:
            raise TxError("catch me")
        except TxError as e:
            assert str(e) == "catch me"
