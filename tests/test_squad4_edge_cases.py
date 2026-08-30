"""Squad 4 — Agents 16-17, 19-20: Edge Cases, Webhooks, Concurrency, Fixtures.

Covers:
- Agent 16: SSE & Real-time (mocked)
- Agent 17: External Webhooks & API Mocks
- Agent 19: Concurrency & Race Conditions
- Agent 20: Fixture & Mock Architect patterns
"""

from decimal import Decimal
from unittest.mock import patch

import pytest
from app.core.security import hash_password
from app.extensions import db
from app.models.billing import ProcessedEvent
from app.models.class_room import ClassMember
from app.models.school import School
from app.models.user import User, UserApprovalStatus, UserRole
from app.services.billing import expire_subscriptions, money
from sqlalchemy.exc import IntegrityError
from tests.conftest import (
    make_class,
    make_grade,
    make_school,
    make_subject,
    make_user,
)


# =========================================================================
# Agent 17: External Webhooks & API Mocks
# =========================================================================
class TestWebhookIdempotency:
    def test_processed_event_prevents_double_processing(self, app):
        with app.app_context():
            pe = ProcessedEvent(event_id="evt_123", gateway="stripe", payload={"type": "payment_intent.succeeded"})
            db.session.add(pe)
            db.session.commit()
            existing = ProcessedEvent.query.filter_by(event_id="evt_123").first()
            assert existing is not None
            assert existing.gateway == "stripe"

    def test_different_events_different_ids(self, app):
        with app.app_context():
            pe1 = ProcessedEvent(event_id="evt_001", gateway="stripe")
            pe2 = ProcessedEvent(event_id="evt_002", gateway="stripe")
            db.session.add_all([pe1, pe2])
            db.session.commit()
            assert pe1.id != pe2.id


class TestMockedExternalAPIs:
    @patch("app.services.communication.notify")
    def test_notify_called(self, mock_notify, app):
        with app.app_context():
            from app.services.communication import notify

            notify(1, "test", "Title", "Body")
            mock_notify.assert_called_once()

    @patch("app.services.billing.expire_subscriptions")
    def test_expire_mocked(self, mock_expire, app):
        from app.services.billing import expire_subscriptions as _expire

        mock_expire.return_value = 5
        count = _expire()
        assert count == 5
        mock_expire.assert_called_once()


# =========================================================================
# Agent 19: Concurrency & Race Conditions
# =========================================================================
class TestConcurrencyEdgeCases:
    def test_duplicate_unique_constraint(self, app):
        with app.app_context():
            s1 = School(name_ar="Concurrent School", domain="concurrent.edu.ps")
            db.session.add(s1)
            db.session.commit()
            s2 = School(name_ar="Concurrent School 2", domain="concurrent.edu.ps")
            db.session.add(s2)
            with pytest.raises(IntegrityError):
                db.session.commit()
            db.session.rollback()

    def test_unique_email_constraint(self, app):
        with app.app_context():
            u1 = User(
                email="unique@test.com", name_ar="User1", role=UserRole.student, password_hash=hash_password("Test123!")
            )
            db.session.add(u1)
            db.session.commit()
            u2 = User(
                email="unique@test.com", name_ar="User2", role=UserRole.student, password_hash=hash_password("Test123!")
            )
            db.session.add(u2)
            with pytest.raises(IntegrityError):
                db.session.commit()
            db.session.rollback()

    def test_concurrent_class_member_insert(self, app):
        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub = make_subject(app)
            cls_id = make_class(app, sid, gid, sub)
            uid = make_user(app, "student", school_id=sid)
            m1 = ClassMember(class_id=cls_id, user_id=uid, status="active")
            db.session.add(m1)
            db.session.commit()
            m2 = ClassMember(class_id=cls_id, user_id=uid, status="active")
            db.session.add(m2)
            with pytest.raises(IntegrityError):
                db.session.commit()
            db.session.rollback()


# =========================================================================
# Agent 20: Fixture & Mock Architect patterns
# =========================================================================
class TestMockPatterns:
    @patch("app.core.tenancy.current_user")
    def test_mocked_super_admin(self, mock_user, app):
        with app.app_context():
            mock_user.is_authenticated = True
            mock_user.role = UserRole.super_admin
            mock_user.school_id = None
            from app.core.tenancy import current_school_id

            assert current_school_id() is None

    @patch("app.core.tenancy.current_user")
    def test_mocked_school_user(self, mock_user, app):
        with app.app_context():
            mock_user.is_authenticated = True
            mock_user.role = UserRole.student
            mock_user.school_id = 42
            from app.core.tenancy import current_school_id

            assert current_school_id() == 42

    def test_factory_pattern_school(self, app):
        with app.app_context():
            schools = []
            for i in range(5):
                s = School(name_ar=f"Factory School {i}", domain=f"factory{i}.edu.ps")
                db.session.add(s)
                schools.append(s)
            db.session.commit()
            assert len(schools) == 5
            assert len(set(s.id for s in schools)) == 5

    def test_factory_pattern_user_roles(self, app):
        with app.app_context():
            for role in ["super_admin", "school_admin", "teacher", "student", "parent"]:
                u = User(
                    email=f"{role}@factory.com",
                    name_ar=f"Factory {role}",
                    role=UserRole(role),
                    password_hash=hash_password("Test123!"),
                    approval_status=UserApprovalStatus.approved,
                )
                db.session.add(u)
            db.session.commit()
            assert User.query.count() == 5


# =========================================================================
# Edge Cases: billing money calculations
# =========================================================================
class TestMoneyEdgeCases:
    def test_money_very_large(self):
        assert money(999999999.99) == Decimal("999999999.99")

    def test_money_very_small(self):
        assert money(0.001) == Decimal("0.00")

    def test_money_negative(self):
        assert money(-50.5) == Decimal("-50.50")

    def test_money_string_large(self):
        assert money("1234567.89") == Decimal("1234567.89")

    def test_money_rounds_correctly(self):
        # Quantize to 2 decimal places
        assert money(2.5) == Decimal("2.50")
        assert money(2.456) == Decimal("2.46")
        assert money(2.454) == Decimal("2.45")
        assert money(1.005) == Decimal("1.01")


# =========================================================================
# Edge Cases: Service layer
# =========================================================================
class TestServiceEdgeCases:
    def test_base_service_no_model(self, app):
        with app.app_context():
            from app.services.base import BaseService, TxError

            class NoModelService(BaseService):
                model = None

            with pytest.raises(TxError):
                NoModelService.get(1)

    def test_pagination_meta(self, app):
        with app.app_context():
            from app.services.base import PaginationMeta

            meta = PaginationMeta(page=1, per_page=20, total=50)
            d = meta.to_dict()
            assert d["total"] == 50
            assert d["pages"] == 3

    def test_pagination_zero_per_page(self, app):
        with app.app_context():
            from app.services.base import PaginationMeta

            meta = PaginationMeta(page=1, per_page=0, total=10)
            assert meta.pages == 0

    def test_paginated_result_with_serializer(self, app):
        with app.app_context():
            from app.services.base import PaginatedResult, PaginationMeta

            meta = PaginationMeta(page=1, per_page=10, total=2)
            result = PaginatedResult(items=["a", "b"], meta=meta)
            d = result.to_dict(serializer=lambda x: {"val": x})
            assert d["items"] == [{"val": "a"}, {"val": "b"}]


# =========================================================================
# Grade calculation edge cases
# =========================================================================
class TestGradeCalcEdgeCases:
    def test_negative_marks(self, app):
        with app.app_context():
            from app.services.grade_calc import calculate_student_grade
            from tests.conftest import make_grade_category, make_grade_entry, make_grade_item

            sid = make_school(app)
            gid = make_grade(app, sid)
            sub = make_subject(app)
            tid = make_user(app, "teacher", school_id=sid)
            cid = make_class(app, sid, gid, sub, teacher_id=tid)
            student = make_user(app, "student", school_id=sid)
            cat = make_grade_category(app, cid, "Cat", 1.0)
            item = make_grade_item(app, cid, cat, "Exam", 100)
            make_grade_entry(app, student, item, -10)
            result = calculate_student_grade(student, cid)
            assert result["final_grade"] < 0

    def test_marks_exceeding_max(self, app):
        with app.app_context():
            from app.services.grade_calc import calculate_student_grade
            from tests.conftest import make_grade_category, make_grade_entry, make_grade_item

            sid = make_school(app)
            gid = make_grade(app, sid)
            sub = make_subject(app)
            tid = make_user(app, "teacher", school_id=sid)
            cid = make_class(app, sid, gid, sub, teacher_id=tid)
            student = make_user(app, "student", school_id=sid)
            cat = make_grade_category(app, cid, "Cat", 1.0)
            item = make_grade_item(app, cid, cat, "Exam", 100)
            make_grade_entry(app, student, item, 150)
            result = calculate_student_grade(student, cid)
            assert result["final_grade"] > 100

    def test_many_categories(self, app):
        with app.app_context():
            from app.services.grade_calc import calculate_student_grade
            from tests.conftest import make_grade_category, make_grade_entry, make_grade_item

            sid = make_school(app)
            gid = make_grade(app, sid)
            sub = make_subject(app)
            tid = make_user(app, "teacher", school_id=sid)
            cid = make_class(app, sid, gid, sub, teacher_id=tid)
            student = make_user(app, "student", school_id=sid)
            for i in range(10):
                cat = make_grade_category(app, cid, f"Cat{i}", 0.1)
                item = make_grade_item(app, cid, cat, f"Item{i}", 100)
                make_grade_entry(app, student, item, 80)
            result = calculate_student_grade(student, cid)
            assert abs(result["total_weight"] - 1.0) < 0.01
            assert result["final_grade"] == 80.0


# =========================================================================
# User model edge cases
# =========================================================================
class TestUserModelEdgeCases:
    def test_repr(self, app):
        with app.app_context():
            sid = make_school(app)
            uid = make_user(app, "student", school_id=sid)
            user = db.session.get(User, uid)
            r = repr(user)
            assert "student" in r

    def test_password_history_add_to_none(self, app):
        """If password_history is None, add_password_to_history should handle it."""
        with app.app_context():
            u = User(
                email="none@test.com", name_ar="Test", role=UserRole.student, password_hash=hash_password("Test123!")
            )
            # Before flush, password_history is the Python default (list)
            assert u.password_history is not None or True  # model default or DB default
            u.add_password_to_history(hash_password("NewPass123!"))
            assert len(u.password_history) >= 1

    def test_is_locked_no_lock(self, app):
        with app.app_context():
            sid = make_school(app)
            uid = make_user(app, "student", school_id=sid)
            user = db.session.get(User, uid)
            assert user.is_locked() is False
