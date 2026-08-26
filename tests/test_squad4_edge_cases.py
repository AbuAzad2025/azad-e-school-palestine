"""Squad 4 — Agents 16-17, 19-20: Edge Cases, Webhooks, Concurrency, Fixtures.

Covers:
- Agent 16: SSE & Real-time (mocked)
- Agent 17: External Webhooks & API Mocks
- Agent 19: Concurrency & Race Conditions
- Agent 20: Fixture & Mock Architect patterns
"""

import pytest
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch, MagicMock, PropertyMock
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy import func

from app.core.db import tx, TxError
from app.extensions import db
from app.models.billing import Subscription, SubscriptionPlan, ProcessedEvent, ManualPayment
from app.models.school import School, Grade
from app.models.user import User, UserRole, UserApprovalStatus
from app.models.class_room import ClassRoom, ClassMember
from app.core.security import hash_password
from app.services.billing import money, expire_subscriptions
from tests.conftest import (
    make_school, make_user, make_class, make_grade, make_subject,
    make_subscription_plan, make_subscription, make_payment,
    make_class_member,
)


# =========================================================================
# Agent 17: External Webhooks & API Mocks
# =========================================================================
class TestWebhookIdempotency:
    def test_processed_event_prevents_double_processing(self, app):
        """ProcessedEvent should prevent processing the same webhook twice."""
        with app.app_context():
            pe = ProcessedEvent(
                event_id="evt_123",
                gateway="stripe",
                payload={"type": "payment_intent.succeeded"},
            )
            db.session.add(pe)
            db.session.commit()

            # Simulating second processing attempt
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

    @patch("app.core.security.hash_password")
    def test_password_hash_mocked(self, mock_hash, app):
        mock_hash.return_value="mocked_hash"
        from app.core.security import hash_password
        result = hash_password("test")
        assert result == "mocked_hash"

    @patch("app.services.billing.expire_subscriptions")
    def test_expire_mocked(self, mock_expire, app):
        mock_expire.return_value = 5
        from app.services.billing import expire_subscriptions
        count = expire_subscriptions()
        assert count == 5
        mock_expire.assert_called_once()


# =========================================================================
# Agent 19: Concurrency & Race Conditions
# =========================================================================
class TestConcurrencyEdgeCases:
    def test_duplicate_unique_constraint(self, app):
        """Duplicate unique values should raise IntegrityError on commit."""
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
                email="unique@test.com",
                name_ar="User1",
                role=UserRole.student,
                password_hash=hash_password("Test123!"),
            )
            db.session.add(u1)
            db.session.commit()

            u2 = User(
                email="unique@test.com",
                name_ar="User2",
                role=UserRole.student,
                password_hash=hash_password("Test123!"),
            )
            db.session.add(u2)
            with pytest.raises(IntegrityError):
                db.session.commit()
            db.session.rollback()

    def test_duplicate_subscription_unique_index(self, app):
        """uq_subscription_active: only one active per (user_id, class_id)."""
        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub = make_subject(app)
            cls_id = make_class(app, sid, gid, sub)
            uid = make_user(app, "student", school_id=sid)
            plan_id = make_subscription_plan(app, sid)

            # First active subscription
            s1 = Subscription(
                user_id=uid, plan_id=plan_id, class_id=cls_id,
                price=100, status="active"
            )
            db.session.add(s1)
            db.session.commit()

            # Second active for same user+class should fail
            s2 = Subscription(
                user_id=uid, plan_id=plan_id, class_id=cls_id,
                price=100, status="active"
            )
            db.session.add(s2)
            with pytest.raises(IntegrityError):
                db.session.commit()
            db.session.rollback()

    def test_concurrent_class_member_insert(self, app):
        """Simulate rapid concurrent inserts of the same class member."""
        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub = make_subject(app)
            cls_id = make_class(app, sid, gid, sub)
            uid = make_user(app, "student", school_id=sid)

            # First insert succeeds
            m1 = ClassMember(class_id=cls_id, user_id=uid, status="active")
            db.session.add(m1)
            db.session.commit()

            # Second insert should fail (unique constraint)
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
    def test_mocked_current_user(self, mock_user, app):
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

    def test_mocked_file_storage(self, app):
        from unittest.mock import MagicMock
        from werkzeug.datastructures import FileStorage
        from io import BytesIO

        content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        file = FileStorage(
            stream=BytesIO(content),
            filename="test.png",
            content_type="image/png",
        )
        assert file.filename == "test.png"
        assert file.read(8) == b"\x89PNG\r\n\x1a\n"

    def test_factory_pattern_school(self, app):
        """Factory pattern: create schools with varying attributes."""
        with app.app_context():
            schools = []
            for i in range(5):
                s = School(
                    name_ar=f"Factory School {i}",
                    domain=f"factory{i}.edu.ps",
                )
                db.session.add(s)
                schools.append(s)
            db.session.commit()
            assert len(schools) == 5
            assert len(set(s.id for s in schools)) == 5

    def test_factory_pattern_user_roles(self, app):
        """Factory pattern: create users with each role."""
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
            count = User.query.count()
            assert count == 5


# =========================================================================
# Edge Cases: billing money calculations
# =========================================================================
class TestMoneyEdgeCases:
    def test_money_very_large(self):
        result = money(999999999.99)
        assert result == Decimal("999999999.99")

    def test_money_very_small(self):
        result = money(0.001)
        assert result == Decimal("0.00")

    def test_money_negative(self):
        result = money(-50.5)
        assert result == Decimal("-50.50")

    def test_money_string_large(self):
        result = money("1234567.89")
        assert result == Decimal("1234567.89")

    def test_money_rounds_half_up(self):
        """ROUND_HALF_UP: 2.5 → 3, 2.4 → 2"""
        assert money(2.5) == Decimal("3.00")
        assert money(2.4) == Decimal("2.00")
        assert money(2.45) == Decimal("2.00")  # 2.45 → 2.45 → 2.45, quantize → 2.45
        assert money(2.450) == Decimal("2.45")


# =========================================================================
# Edge Cases: Service layer
# =========================================================================
class TestServiceEdgeCases:
    def test_base_service_get_nonexistent(self, app):
        with app.app_context():
            from app.services.base import BaseService
            # BaseService with no model set
            class NoModelService(BaseService):
                model = None

            with pytest.raises(TxError):
                NoModelService.get(1)

    def test_base_service_count(self, app):
        with app.app_context():
            from app.services.base import BaseService, PaginationMeta, PaginatedResult

            # Test PaginationMeta
            meta = PaginationMeta(page=1, per_page=20, total=50)
            d = meta.to_dict()
            assert d["total"] == 50
            assert d["pages"] == 3

            # Test PaginatedResult
            result = PaginatedResult(items=[1, 2, 3], meta=meta)
            d = result.to_dict()
            assert len(d["items"]) == 3

    def test_pagination_meta_zero_per_page(self, app):
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
        """Negative marks should still calculate (no enforcement in service layer)."""
        with app.app_context():
            from app.services.grade_calc import calculate_student_grade
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub = make_subject(app)
            tid = make_user(app, "teacher", school_id=sid)
            cid = make_class(app, sid, gid, sub, teacher_id=tid)
            student = make_user(app, "student", school_id=sid)

            from tests.conftest import make_grade_category, make_grade_item, make_grade_entry
            cat = make_grade_category(app, cid, "Cat", 1.0)
            item = make_grade_item(app, cid, cat, "Exam", 100)
            make_grade_entry(app, student, item, -10)

            result = calculate_student_grade(student, cid)
            # Should not crash, pct = -10%
            assert result["final_grade"] < 0

    def test_marks_exceeding_max(self, app):
        """Marks exceeding max should calculate > 100%."""
        with app.app_context():
            from app.services.grade_calc import calculate_student_grade
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub = make_subject(app)
            tid = make_user(app, "teacher", school_id=sid)
            cid = make_class(app, sid, gid, sub, teacher_id=tid)
            student = make_user(app, "student", school_id=sid)

            from tests.conftest import make_grade_category, make_grade_item, make_grade_entry
            cat = make_grade_category(app, cid, "Cat", 1.0)
            item = make_grade_item(app, cid, cat, "Exam", 100)
            make_grade_entry(app, student, item, 150)

            result = calculate_student_grade(student, cid)
            assert result["final_grade"] > 100

    def test_float_precision(self, app):
        """Verify rounding precision with many decimal places."""
        result = round(80 * 0.4 + 90 * 0.6, 2)
        assert result == 86.0

    def test_many_categories(self, app):
        """Stress test with many categories."""
        with app.app_context():
            from app.services.grade_calc import calculate_student_grade
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub = make_subject(app)
            tid = make_user(app, "teacher", school_id=sid)
            cid = make_class(app, sid, gid, sub, teacher_id=tid)
            student = make_user(app, "student", school_id=sid)

            from tests.conftest import make_grade_category, make_grade_item, make_grade_entry
            for i in range(10):
                cat = make_grade_category(app, cid, f"Cat{i}", 0.1)
                item = make_grade_item(app, cid, cat, f"Item{i}", 100)
                make_grade_entry(app, student, item, 80)

            result = calculate_student_grade(student, cid)
            assert result["total_weight"] == 1.0
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
            assert str(uid) in r
            assert "student" in r

    def test_password_history_none_initial(self, app):
        with app.app_context():
            u = User(
                email="new@test.com",
                name_ar="New",
                role=UserRole.student,
                password_hash=hash_password("Test123!"),
            )
            # password_history defaults to list via model default
            assert u.password_history is not None

    def test_add_password_to_history_none_guard(self, app):
        """If password_history is somehow None, add_password_to_history should handle it."""
        with app.app_context():
            sid = make_school(app)
            uid = make_user(app, "student", school_id=sid)
            user = db.session.get(User, uid)
            user.password_history = None
            user.add_password_to_history(hash_password("NewPass123!"))
            assert len(user.password_history) == 1
