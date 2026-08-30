"""Financial Ledger Integrity & Race Condition Tests.

Verifies that:
- Double-approval of payments is prevented (FOR UPDATE)
- Double-subscription is prevented
- Double commission creation is prevented
- Discount code cannot exceed max_uses
- Subscription balance calculations are consistent
"""

from decimal import Decimal

from tests.conftest import (
    make_class,
    make_grade,
    make_payment,
    make_school,
    make_subject,
    make_subscription,
    make_subscription_plan,
    make_user,
)


class TestDoubleApprovalPrevention:
    """Two approvals of the same payment must not both succeed."""

    def test_cannot_approve_payment_twice(self, app, client):
        from app.core.db import TxError
        from app.extensions import db
        from app.models.billing import ManualPayment
        from app.services.billing import approve_payment

        school = make_school(app)
        grade = make_grade(app, school)
        subject_id = make_subject(app)
        student = make_user(app, role="student", school_id=school)
        class_id = make_class(app, school, grade, subject_id)
        plan_id = make_subscription_plan(app, school, class_id=class_id)
        sub_id = make_subscription(app, student, plan_id, class_id)
        pay_id = make_payment(app, sub_id, amount=100.0, status="pending")

        with app.app_context():
            payment1 = db.session.get(ManualPayment, pay_id)
            approve_payment(payment1, reviewer_id=1)

            payment2 = db.session.get(ManualPayment, pay_id)
            assert payment2.status == "approved"

            try:
                approve_payment(payment2, reviewer_id=1)
                assert False, "Should have raised TxError"
            except TxError:
                pass

    def test_cannot_reject_payment_twice(self, app, client):
        from app.core.db import TxError
        from app.extensions import db
        from app.models.billing import ManualPayment
        from app.services.billing import reject_payment

        school = make_school(app)
        grade = make_grade(app, school)
        subject_id = make_subject(app)
        student = make_user(app, role="student", school_id=school)
        class_id = make_class(app, school, grade, subject_id)
        plan_id = make_subscription_plan(app, school, class_id=class_id)
        sub_id = make_subscription(app, student, plan_id, class_id)
        pay_id = make_payment(app, sub_id, amount=100.0, status="pending")

        with app.app_context():
            payment1 = db.session.get(ManualPayment, pay_id)
            reject_payment(payment1, reviewer_id=1)

            payment2 = db.session.get(ManualPayment, pay_id)
            assert payment2.status == "rejected"

            try:
                reject_payment(payment2, reviewer_id=1)
                assert False, "Should have raised TxError"
            except TxError:
                pass


class TestDoubleSubscriptionPrevention:
    """Two subscriptions for the same user/class must not both succeed."""

    def test_cannot_create_duplicate_active_subscription(self, app, client):
        from app.extensions import db
        from app.models.billing import Subscription, SubscriptionPlan
        from app.services.billing import subscribe

        school = make_school(app)
        grade = make_grade(app, school)
        subject_id = make_subject(app)
        student = make_user(app, role="student", school_id=school)
        class_id = make_class(app, school, grade, subject_id)
        plan_id = make_subscription_plan(app, school, class_id=class_id)

        with app.app_context():
            plan = db.session.get(SubscriptionPlan, plan_id)

            # First subscription (pending) succeeds
            sub1, err1 = subscribe(student, plan, class_id)
            assert sub1 is not None, f"First subscribe failed: {err1}"

            # Activate the first subscription manually
            sub1_obj = db.session.get(Subscription, sub1.id)
            sub1_obj.status = "active"
            db.session.commit()

            # Second subscription should fail (already active)
            sub2, err2 = subscribe(student, plan, class_id)
            assert sub2 is None
            assert "نشط" in err2 or "active" in err2.lower()

            # Only one subscription should exist
            count = Subscription.query.filter_by(user_id=student, class_id=class_id).count()
            assert count == 1


class TestCommissionIntegrity:
    """Commission records must not be duplicated for the same session."""

    def test_cannot_create_duplicate_commission(self, app, client):
        from app.extensions import db
        from app.models.tutoring import TutorCommission, TutoringSession
        from app.services.tutoring import create_commission_record

        school = make_school(app)
        tutor = make_user(app, role="teacher", school_id=school)
        student = make_user(app, role="student", school_id=school)

        with app.app_context():
            session = TutoringSession(
                tutor_id=tutor,
                student_id=student,
                subject="Math",
                status="completed",
                price=Decimal("200.00"),
            )
            db.session.add(session)
            db.session.commit()
            session_id = session.id

            c1 = create_commission_record(session)
            assert c1 is not None

            session2 = db.session.get(TutoringSession, session_id)
            c2 = create_commission_record(session2)
            assert c2 is None

            count = TutorCommission.query.filter_by(session_id=session_id).count()
            assert count == 1


class TestSubscriptionBalanceConsistency:
    """Balance must decrease only after payment approval."""

    def test_balance_decreases_with_approved_payments(self, app, client):
        from app.extensions import db
        from app.models.billing import ManualPayment, Subscription
        from app.services.billing import approve_payment, record_manual_payment, subscription_balance

        school = make_school(app)
        grade = make_grade(app, school)
        subject_id = make_subject(app)
        student = make_user(app, role="student", school_id=school)
        class_id = make_class(app, school, grade, subject_id)
        plan_id = make_subscription_plan(app, school, class_id=class_id, price=Decimal("500.00"))
        sub_id = make_subscription(app, student, plan_id, class_id, price=500.0)

        with app.app_context():
            balance = subscription_balance(sub_id)
            assert balance == Decimal("500.00"), f"Expected 500.00, got {balance}"

            sub = db.session.get(Subscription, sub_id)
            payment, err = record_manual_payment(sub, reference="PAY-001", amount=200)
            assert payment is not None

            balance = subscription_balance(sub_id)
            assert balance == Decimal("500.00"), f"Expected 500.00 after pending, got {balance}"

            payment_obj = db.session.get(ManualPayment, payment.id)
            approve_payment(payment_obj, reviewer_id=1)

            balance = subscription_balance(sub_id)
            assert balance == Decimal("300.00"), f"Expected 300.00 after approval, got {balance}"


class TestDiscountCodeAtomicity:
    """Discount code usage must not exceed max_uses."""

    def test_discount_code_max_uses_enforced(self, app, client):
        from app.extensions import db
        from app.models.billing import DiscountCode, Subscription
        from app.services.billing import apply_discount_code

        school = make_school(app)
        grade = make_grade(app, school)
        subject_id = make_subject(app)
        student = make_user(app, role="student", school_id=school)
        class_id = make_class(app, school, grade, subject_id)
        plan_id = make_subscription_plan(app, school, class_id=class_id, price=Decimal("100.00"))
        sub_id = make_subscription(app, student, plan_id, class_id)

        with app.app_context():
            dc = DiscountCode(
                code="TEST10",
                name="Test Discount",
                type="fixed",
                value=Decimal("10.00"),
                max_uses=1,
                is_active=True,
            )
            db.session.add(dc)
            db.session.commit()

            result1, err1 = apply_discount_code(sub_id, "TEST10")
            assert result1 is not None, f"First apply failed: {err1}"

            result2, err2 = apply_discount_code(sub_id, "TEST10")
            assert result2 is None
            assert "استنفاد" in err2 or "exceeded" in err2.lower()

            dc_refreshed = db.session.get(DiscountCode, dc.id)
            assert dc_refreshed.used_count == 1
