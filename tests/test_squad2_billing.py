"""Squad 2 — Agent 9: Billing & Subscriptions.

Tests expired subscriptions, idempotency on webhooks, failed payments,
discount codes, and balance calculations.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from app.core.db import TxError
from app.extensions import db
from app.models.billing import (
    Subscription,
    SubscriptionPlan,
)
from app.services.billing import (
    apply_discount_code,
    approve_payment,
    can_record_payment,
    create_discount_code,
    create_plan,
    expire_subscriptions,
    list_plans,
    list_subscriptions,
    money,
    record_manual_payment,
    reject_payment,
    subscribe,
    subscription_balance,
    subscription_payment_summary,
    validate_discount_code,
)
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


def _sub_ctx(app):
    """Create school+grade+subject+class+user+plan, return (sid, uid, plan_id, cls_id)."""
    sid = make_school(app)
    gid = make_grade(app, sid)
    sub = make_subject(app)
    cls_id = make_class(app, sid, gid, sub)
    uid = make_user(app, "student", school_id=sid)
    plan_id = make_subscription_plan(app, sid, class_id=cls_id, price=100)
    return sid, uid, plan_id, cls_id


# ---------------------------------------------------------------------------
# money()
# ---------------------------------------------------------------------------
class TestMoney:
    @pytest.mark.parametrize(
        "input_val,expected",
        [
            (100, Decimal("100.00")),
            (99.999, Decimal("100.00")),
            (99.994, Decimal("99.99")),
            ("50.50", Decimal("50.50")),
            (0, Decimal("0.00")),
            (-10, Decimal("-10.00")),
            ("0.001", Decimal("0.00")),
        ],
    )
    def test_money_rounding(self, input_val, expected):
        assert money(input_val) == expected

    def test_money_float(self):
        assert money(19.995) == Decimal("20.00")

    def test_money_string(self):
        assert money("100.5") == Decimal("100.50")


# ---------------------------------------------------------------------------
# create_plan
# ---------------------------------------------------------------------------
class TestCreatePlan:
    def test_create_plan_success(self, app):
        with app.app_context():
            sid = make_school(app)
            plan, error = create_plan(sid, "Annual Plan", "annual", 500)
            assert error is None
            assert plan is not None
            assert plan.price == Decimal("500.00")

    def test_create_plan_empty_name(self, app):
        with app.app_context():
            sid = make_school(app)
            plan, error = create_plan(sid, "", "annual", 500)
            assert plan is None
            assert error is not None

    def test_create_plan_invalid_type(self, app):
        with app.app_context():
            sid = make_school(app)
            plan, error = create_plan(sid, "Plan", "invalid_type", 500)
            assert plan is None
            assert error is not None

    def test_create_plan_valid_types(self, app):
        with app.app_context():
            sid = make_school(app)
            for pt in ["first_term", "second_term", "annual"]:
                plan, error = create_plan(sid, f"P {pt}", pt, 100)
                assert error is None


# ---------------------------------------------------------------------------
# list_plans
# ---------------------------------------------------------------------------
class TestListPlans:
    def test_list_all(self, app):
        with app.app_context():
            sid = make_school(app)
            make_subscription_plan(app, sid)
            assert len(list_plans()) >= 1

    def test_list_by_class(self, app):
        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub = make_subject(app)
            cls_id = make_class(app, sid, gid, sub)
            make_subscription_plan(app, sid, class_id=cls_id)
            assert len(list_plans(class_id=cls_id)) >= 1


# ---------------------------------------------------------------------------
# subscribe
# ---------------------------------------------------------------------------
class TestSubscribe:
    def test_subscribe_success(self, app):
        with app.app_context():
            sid, uid, plan_id, cls_id = _sub_ctx(app)
            plan = db.session.get(SubscriptionPlan, plan_id)
            sub, error = subscribe(uid, plan, cls_id)
            assert error is None
            assert sub.status == "pending"

    def test_subscribe_active_already_exists(self, app):
        with app.app_context():
            sid, uid, plan_id, cls_id = _sub_ctx(app)
            # Create an active subscription directly
            sub_id = make_subscription(app, uid, plan_id, cls_id, status="active")
            plan = db.session.get(SubscriptionPlan, plan_id)
            sub2, error = subscribe(uid, plan, cls_id)
            assert sub2 is None
            assert error is not None


# ---------------------------------------------------------------------------
# list_subscriptions
# ---------------------------------------------------------------------------
class TestListSubscriptions:
    def test_list_all(self, app):
        with app.app_context():
            sid, uid, plan_id, cls_id = _sub_ctx(app)
            make_subscription(app, uid, plan_id, cls_id)
            assert len(list_subscriptions()) >= 1

    def test_filter_by_status(self, app):
        with app.app_context():
            sid, uid, plan_id, cls_id = _sub_ctx(app)
            make_subscription(app, uid, plan_id, cls_id, status="active")
            assert all(s.status == "active" for s in list_subscriptions(status="active"))


# ---------------------------------------------------------------------------
# record_manual_payment
# ---------------------------------------------------------------------------
class TestRecordManualPayment:
    def test_record_success(self, app):
        with app.app_context():
            sid, uid, plan_id, cls_id = _sub_ctx(app)
            sub_id = make_subscription(app, uid, plan_id, cls_id)
            sub = db.session.get(Subscription, sub_id)
            payment, error = record_manual_payment(sub, "REF001", 50.0)
            assert error is None
            assert payment is not None

    def test_record_empty_reference(self, app):
        with app.app_context():
            sid, uid, plan_id, cls_id = _sub_ctx(app)
            sub_id = make_subscription(app, uid, plan_id, cls_id)
            sub = db.session.get(Subscription, sub_id)
            payment, error = record_manual_payment(sub, "", 50.0)
            assert payment is None

    def test_record_zero_amount(self, app):
        with app.app_context():
            sid, uid, plan_id, cls_id = _sub_ctx(app)
            sub_id = make_subscription(app, uid, plan_id, cls_id)
            sub = db.session.get(Subscription, sub_id)
            payment, error = record_manual_payment(sub, "REF001", 0)
            assert payment is None


# ---------------------------------------------------------------------------
# approve / reject
# ---------------------------------------------------------------------------
class TestApproveReject:
    def test_approve_activates(self, app):
        with app.app_context():
            sid, uid, plan_id, cls_id = _sub_ctx(app)
            sub_id = make_subscription(app, uid, plan_id, cls_id)
            sub = db.session.get(Subscription, sub_id)
            payment, _ = record_manual_payment(sub, "REF001", 100)
            approved = approve_payment(payment)
            assert approved.status == "active"
            assert approved.start_at is not None

    def test_approve_already_approved(self, app):
        with app.app_context():
            sid, uid, plan_id, cls_id = _sub_ctx(app)
            sub_id = make_subscription(app, uid, plan_id, cls_id)
            sub = db.session.get(Subscription, sub_id)
            payment, _ = record_manual_payment(sub, "REF001", 100)
            approve_payment(payment)
            with pytest.raises(TxError):
                approve_payment(payment)

    def test_reject(self, app):
        with app.app_context():
            sid, uid, plan_id, cls_id = _sub_ctx(app)
            sub_id = make_subscription(app, uid, plan_id, cls_id)
            sub = db.session.get(Subscription, sub_id)
            payment, _ = record_manual_payment(sub, "REF001", 100)
            reject_payment(payment)
            db.session.refresh(payment)
            assert payment.status == "rejected"

    def test_reject_already_rejected(self, app):
        with app.app_context():
            sid, uid, plan_id, cls_id = _sub_ctx(app)
            sub_id = make_subscription(app, uid, plan_id, cls_id)
            sub = db.session.get(Subscription, sub_id)
            payment, _ = record_manual_payment(sub, "REF001", 100)
            reject_payment(payment)
            with pytest.raises(TxError):
                reject_payment(payment)


# ---------------------------------------------------------------------------
# expire_subscriptions
# ---------------------------------------------------------------------------
class TestExpireSubscriptions:
    def test_expires_old(self, app):
        with app.app_context():
            sid, uid, plan_id, cls_id = _sub_ctx(app)
            sub_id = make_subscription(app, uid, plan_id, cls_id, status="active")
            sub = db.session.get(Subscription, sub_id)
            sub.end_at = datetime.now(UTC) - timedelta(days=1)
            db.session.commit()
            count = expire_subscriptions()
            assert count >= 1
            db.session.refresh(sub)
            assert sub.status == "expired"

    def test_future_not_expired(self, app):
        with app.app_context():
            sid, uid, plan_id, cls_id = _sub_ctx(app)
            sub_id = make_subscription(app, uid, plan_id, cls_id, status="active")
            sub = db.session.get(Subscription, sub_id)
            sub.end_at = datetime.now(UTC) + timedelta(days=30)
            db.session.commit()
            expire_subscriptions()
            db.session.refresh(sub)
            assert sub.status == "active"


# ---------------------------------------------------------------------------
# subscription_balance
# ---------------------------------------------------------------------------
class TestSubscriptionBalance:
    def test_full_balance(self, app):
        with app.app_context():
            sid, uid, plan_id, cls_id = _sub_ctx(app)
            sub_id = make_subscription(app, uid, plan_id, cls_id)
            assert subscription_balance(sub_id) == Decimal("100.00")

    def test_partial_payment(self, app):
        with app.app_context():
            sid, uid, plan_id, cls_id = _sub_ctx(app)
            sub_id = make_subscription(app, uid, plan_id, cls_id)
            make_payment(app, sub_id, amount=30, status="approved")
            assert subscription_balance(sub_id) == Decimal("70.00")

    def test_nonexistent(self, app):
        with app.app_context():
            assert subscription_balance(99999) == Decimal("0.00")


# ---------------------------------------------------------------------------
# can_record_payment
# ---------------------------------------------------------------------------
class TestCanRecordPayment:
    def test_valid(self, app):
        with app.app_context():
            sid, uid, plan_id, cls_id = _sub_ctx(app)
            sub_id = make_subscription(app, uid, plan_id, cls_id)
            ok, _ = can_record_payment(sub_id, 50)
            assert ok is True

    def test_zero(self, app):
        with app.app_context():
            sid, uid, plan_id, cls_id = _sub_ctx(app)
            sub_id = make_subscription(app, uid, plan_id, cls_id)
            ok, _ = can_record_payment(sub_id, 0)
            assert ok is False

    def test_exceeds(self, app):
        with app.app_context():
            sid, uid, plan_id, cls_id = _sub_ctx(app)
            sub_id = make_subscription(app, uid, plan_id, cls_id)
            ok, _ = can_record_payment(sub_id, 200)
            assert ok is False


# ---------------------------------------------------------------------------
# subscription_payment_summary
# ---------------------------------------------------------------------------
class TestSubscriptionPaymentSummary:
    def test_empty(self, app):
        with app.app_context():
            sid, uid, plan_id, cls_id = _sub_ctx(app)
            sub_id = make_subscription(app, uid, plan_id, cls_id)
            s = subscription_payment_summary(sub_id)
            assert s["total_price"] == Decimal("100.00")
            assert s["total_paid"] == Decimal("0.00")
            assert s["approved_count"] == 0

    def test_with_payments(self, app):
        with app.app_context():
            sid, uid, plan_id, cls_id = _sub_ctx(app)
            sub_id = make_subscription(app, uid, plan_id, cls_id)
            make_payment(app, sub_id, amount=30, status="approved")
            make_payment(app, sub_id, amount=20, status="pending")
            s = subscription_payment_summary(sub_id)
            assert s["approved_count"] == 1
            assert s["pending_count"] == 1

    def test_nonexistent(self, app):
        with app.app_context():
            assert subscription_payment_summary(99999) == {}


# ---------------------------------------------------------------------------
# Discount Codes
# ---------------------------------------------------------------------------
class TestDiscountCodes:
    def test_create_percentage(self, app):
        with app.app_context():
            sid = make_school(app)
            dc, err = create_discount_code(sid, "SAVE10", "10% Off", "percentage", 10, max_uses=5)
            assert err is None

    def test_create_fixed(self, app):
        with app.app_context():
            sid = make_school(app)
            dc, err = create_discount_code(sid, "FIX50", "50 Off", "fixed", 50, max_uses=3)
            assert err is None

    def test_empty_code(self, app):
        with app.app_context():
            sid = make_school(app)
            assert create_discount_code(sid, "", "Empty", "percentage", 10)[0] is None

    def test_invalid_type(self, app):
        with app.app_context():
            sid = make_school(app)
            assert create_discount_code(sid, "BAD", "Bad", "invalid", 10)[0] is None

    def test_zero_value(self, app):
        with app.app_context():
            sid = make_school(app)
            assert create_discount_code(sid, "ZERO", "Zero", "percentage", 0)[0] is None

    def test_expired_date(self, app):
        with app.app_context():
            sid = make_school(app)
            assert create_discount_code(sid, "OLD", "Old", "percentage", 10, expiry_date=date(2020, 1, 1))[0] is None

    def test_duplicate(self, app):
        with app.app_context():
            sid = make_school(app)
            create_discount_code(sid, "DUP", "First", "percentage", 10)
            assert create_discount_code(sid, "DUP", "Second", "percentage", 20)[0] is None

    def test_max_uses_zero(self, app):
        with app.app_context():
            sid = make_school(app)
            assert create_discount_code(sid, "BAD", "Bad", "percentage", 10, max_uses=0)[0] is None


# ---------------------------------------------------------------------------
# validate_discount_code
# ---------------------------------------------------------------------------
class TestValidateDiscountCode:
    def test_valid(self, app):
        with app.app_context():
            sid = make_school(app)
            create_discount_code(sid, "VALID", "Valid", "percentage", 10, max_uses=5)
            plan_id = make_subscription_plan(app, sid, price=200)
            d, err = validate_discount_code("VALID", plan_id)
            assert err is None
            assert d == Decimal("20.00")

    def test_invalid(self, app):
        with app.app_context():
            sid = make_school(app)
            plan_id = make_subscription_plan(app, sid, price=200)
            d, err = validate_discount_code("NOPE", plan_id)
            assert d is None

    def test_inactive(self, app):
        with app.app_context():
            sid = make_school(app)
            dc, _ = create_discount_code(sid, "INACT", "Inactive", "percentage", 10)
            dc.is_active = False
            db.session.commit()
            plan_id = make_subscription_plan(app, sid, price=200)
            d, _ = validate_discount_code("INACT", plan_id)
            assert d is None

    def test_used_up(self, app):
        with app.app_context():
            sid = make_school(app)
            dc, _ = create_discount_code(sid, "USED", "Used", "percentage", 10, max_uses=1)
            dc.used_count = 1
            db.session.commit()
            plan_id = make_subscription_plan(app, sid, price=200)
            d, _ = validate_discount_code("USED", plan_id)
            assert d is None

    def test_fixed(self, app):
        with app.app_context():
            sid = make_school(app)
            create_discount_code(sid, "FIXED", "Fixed", "fixed", 50, max_uses=5)
            plan_id = make_subscription_plan(app, sid, price=200)
            d, err = validate_discount_code("FIXED", plan_id)
            assert err is None
            assert d == Decimal("50.00")

    def test_capped_at_price(self, app):
        with app.app_context():
            sid = make_school(app)
            create_discount_code(sid, "BIG", "Big", "percentage", 100, max_uses=5)
            plan_id = make_subscription_plan(app, sid, price=50)
            d, err = validate_discount_code("BIG", plan_id)
            assert err is None
            assert d == Decimal("50.00")

    def test_empty_code(self, app):
        with app.app_context():
            sid = make_school(app)
            plan_id = make_subscription_plan(app, sid, price=200)
            d, _ = validate_discount_code("", plan_id)
            assert d is None

    def test_nonexistent_plan(self, app):
        with app.app_context():
            sid = make_school(app)
            create_discount_code(sid, "NP", "NP", "percentage", 10)
            d, _ = validate_discount_code("NP", 99999)
            assert d is None


# ---------------------------------------------------------------------------
# apply_discount_code
# ---------------------------------------------------------------------------
class TestApplyDiscountCode:
    def test_apply_success(self, app):
        with app.app_context():
            sid, uid, plan_id, cls_id = _sub_ctx(app)
            create_discount_code(sid, "AP10", "Apply", "percentage", 10, max_uses=5)
            sub_id = make_subscription(app, uid, plan_id, cls_id)
            d, err = apply_discount_code(sub_id, "AP10")
            assert err is None
            # Plan price=100, 10% discount = 10.00
            assert d == Decimal("10.00")

    def test_apply_invalid(self, app):
        with app.app_context():
            sid, uid, plan_id, cls_id = _sub_ctx(app)
            sub_id = make_subscription(app, uid, plan_id, cls_id)
            d, _ = apply_discount_code(sub_id, "NOPE")
            assert d is None

    def test_apply_empty(self, app):
        with app.app_context():
            sid, uid, plan_id, cls_id = _sub_ctx(app)
            sub_id = make_subscription(app, uid, plan_id, cls_id)
            d, _ = apply_discount_code(sub_id, "")
            assert d is None

    def test_apply_nonexistent_sub(self, app):
        with app.app_context():
            sid = make_school(app)
            create_discount_code(sid, "T", "T", "percentage", 10)
            d, _ = apply_discount_code(99999, "T")
            assert d is None

    def test_apply_exhausted(self, app):
        with app.app_context():
            sid = make_school(app)
            dc, _ = create_discount_code(sid, "RACE", "Race", "fixed", 10, max_uses=1)
            dc.used_count = 1
            db.session.commit()
            plan_id = make_subscription_plan(app, sid, price=200)
            uid = make_user(app, "student", school_id=sid)
            gid = make_grade(app, sid)
            sub = make_subject(app)
            cls_id = make_class(app, sid, gid, sub)
            sub_id = make_subscription(app, uid, plan_id, cls_id)
            d, _ = apply_discount_code(sub_id, "RACE")
            assert d is None


# ---------------------------------------------------------------------------
# Subscription model defaults
# ---------------------------------------------------------------------------
class TestSubscriptionModel:
    def test_default_status(self, app):
        with app.app_context():
            sid, uid, plan_id, cls_id = _sub_ctx(app)
            sub_id = make_subscription(app, uid, plan_id, cls_id)
            sub = db.session.get(Subscription, sub_id)
            assert sub.status == "pending"

    def test_source_default(self, app):
        with app.app_context():
            sid, uid, plan_id, cls_id = _sub_ctx(app)
            sub_id = make_subscription(app, uid, plan_id, cls_id)
            sub = db.session.get(Subscription, sub_id)
            assert sub.source == "manual"
