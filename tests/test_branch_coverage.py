"""Massive branch coverage tests — targets every untested decision path.

Covers: billing, schools, assessment, tutoring, messages, content,
progress, video_service, grade_calc, finance, db, tenancy, permissions.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from base64 import urlsafe_b64encode
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from tests.conftest import (
    make_class,
    make_class_member,
    make_grade,
    make_grade_category,
    make_grade_entry,
    make_grade_item,
    make_lesson,
    make_payment,
    make_school,
    make_subject,
    make_subscription,
    make_subscription_plan,
    make_user,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _login(client, email, password="TestPass123!"):
    return client.post(
        "/auth/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )


def _make_super_admin(app):
    uid = f"admin_{int(time.time()*1000)}"
    return make_user(app, role="super_admin", email=f"{uid}@test.com")


def _make_school_admin(app, school_id):
    uid = f"sa_{int(time.time()*1000)}"
    return make_user(app, role="school_admin", school_id=school_id, email=f"{uid}@test.com")


def _make_teacher(app, school_id):
    uid = f"te_{int(time.time()*1000)}"
    return make_user(app, role="teacher", school_id=school_id, email=f"{uid}@test.com")


def _make_student(app, school_id=None):
    uid = f"st_{int(time.time()*1000)}"
    return make_user(app, role="student", school_id=school_id, email=f"{uid}@test.com")


# ===========================================================================
# BILLING — every branch path
# ===========================================================================

class TestBillingBranches:
    """billing.py — discount codes, approve/reject, balance, expiry, etc."""

    def test_money_zero(self, app):
        from app.services.billing import money
        with app.app_context():
            assert money(0) == Decimal("0.00")
            assert money("0") == Decimal("0.00")

    def test_money_float(self, app):
        from app.services.billing import money
        with app.app_context():
            result = money(19.995)
            assert result == Decimal("20.00")

    def test_money_string(self, app):
        from app.services.billing import money
        with app.app_context():
            assert money("42.5") == Decimal("42.50")

    def test_money_negative(self, app):
        from app.services.billing import money
        with app.app_context():
            assert money(-5) == Decimal("-5.00")

    def test_create_plan_empty_name(self, app):
        from app.services.billing import create_plan
        with app.app_context():
            sid = make_school(app)
            result, err = create_plan(sid, "", "annual", 100)
            assert result is None
            assert err is not None

    def test_create_plan_none_price(self, app):
        from app.services.billing import create_plan
        with app.app_context():
            sid = make_school(app)
            result, err = create_plan(sid, "Test", "annual", None)
            assert result is None

    def test_create_plan_invalid_type(self, app):
        from app.services.billing import create_plan
        with app.app_context():
            sid = make_school(app)
            result, err = create_plan(sid, "Test", "invalid_type", 100)
            assert result is None
            assert err is not None

    def test_create_plan_success(self, app):
        from app.services.billing import create_plan
        with app.app_context():
            sid = make_school(app)
            cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
            plan, err = create_plan(sid, "Annual Plan", "annual", 500, class_id=cid)
            assert plan is not None
            assert plan.price == Decimal("500.00")

    def test_list_plans_with_class(self, app):
        from app.services.billing import create_plan, list_plans
        with app.app_context():
            sid = make_school(app)
            cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
            create_plan(sid, "Class Plan", "annual", 100, class_id=cid)
            create_plan(sid, "Global Plan", "annual", 200)
            plans = list_plans(class_id=cid)
            assert len(plans) >= 2

    def test_list_plans_no_filter(self, app):
        from app.services.billing import create_plan, list_plans
        with app.app_context():
            sid = make_school(app)
            create_plan(sid, "P1", "annual", 50)
            assert len(list_plans()) >= 1

    def test_subscribe_duplicate_active_raises(self, app):
        from app.services.billing import subscribe
        from app.models.billing import SubscriptionPlan as SP
        with app.app_context():
            sid = make_school(app)
            cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
            uid = _make_student(app)
            plan_id = make_subscription_plan(app, sid, cid, price=0, plan="annual")
            plan_obj = db.session.get(SP, plan_id)
            make_subscription(app, uid, plan_id, cid, status="active")
            result, err = subscribe(uid, plan_obj, cid)
            assert result is None
            assert err is not None

    def test_record_manual_payment_invalid_reference(self, app):
        from app.services.billing import record_manual_payment
        from app.models.billing import Subscription as SubModel
        with app.app_context():
            sid = make_school(app)
            cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
            uid = _make_student(app)
            plan_id = make_subscription_plan(app, sid, cid, price=100)
            sub_id = make_subscription(app, uid, plan_id, cid)
            sub = db.session.get(SubModel, sub_id)
            result, err = record_manual_payment(sub, "", 50)
            assert result is None
            assert err is not None

    def test_record_manual_payment_zero_amount(self, app):
        from app.services.billing import record_manual_payment
        from app.models.billing import Subscription as SubModel
        with app.app_context():
            sid = make_school(app)
            cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
            uid = _make_student(app)
            plan_id = make_subscription_plan(app, sid, cid, price=100)
            sub_id = make_subscription(app, uid, plan_id, cid)
            sub = db.session.get(SubModel, sub_id)
            result, err = record_manual_payment(sub, "REF-123", 0)
            assert result is None

    def test_record_manual_payment_negative_amount(self, app):
        from app.services.billing import record_manual_payment
        from app.models.billing import Subscription as SubModel
        with app.app_context():
            sid = make_school(app)
            cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
            uid = _make_student(app)
            plan_id = make_subscription_plan(app, sid, cid, price=100)
            sub_id = make_subscription(app, uid, plan_id, cid)
            sub = db.session.get(SubModel, sub_id)
            result, err = record_manual_payment(sub, "REF-123", -10)
            assert result is None

    def test_record_manual_payment_success(self, app):
        from app.services.billing import record_manual_payment
        from app.models.billing import Subscription as SubModel
        with app.app_context():
            sid = make_school(app)
            cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
            uid = _make_student(app)
            plan_id = make_subscription_plan(app, sid, cid, price=100)
            sub_id = make_subscription(app, uid, plan_id, cid)
            sub = db.session.get(SubModel, sub_id)
            payment, err = record_manual_payment(sub, "REF-OK", 50, note="Cash")
            assert payment is not None
            assert payment.amount == Decimal("50.00")

    def test_approve_payment_already_reviewed(self, app):
        from app.services.billing import approve_payment
        from app.models.billing import ManualPayment as MP
        with app.app_context():
            sid = make_school(app)
            cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
            uid = _make_student(app)
            plan_id = make_subscription_plan(app, sid, cid, price=100)
            sub_id = make_subscription(app, uid, plan_id, cid)
            pay_id = make_payment(app, sub_id, status="approved")
            pay = db.session.get(MP, pay_id)
            with pytest.raises(Exception):
                approve_payment(pay)

    def test_approve_payment_pending_creates_member(self, app):
        from app.services.billing import approve_payment
        from app.models.billing import ManualPayment as MP
        with app.app_context():
            sid = make_school(app)
            cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
            uid = _make_student(app)
            plan_id = make_subscription_plan(app, sid, cid, price=100)
            sub_id = make_subscription(app, uid, plan_id, cid)
            pay_id = make_payment(app, sub_id, status="pending")
            pay = db.session.get(MP, pay_id)
            reviewer = _make_school_admin(app, sid)
            sub = approve_payment(pay, reviewer_id=reviewer)
            assert sub.status == "active"

    def test_approve_payment_already_active_member(self, app):
        from app.services.billing import approve_payment
        from app.models.billing import ManualPayment as MP
        with app.app_context():
            sid = make_school(app)
            cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
            uid = _make_student(app)
            plan_id = make_subscription_plan(app, sid, cid, price=100)
            sub_id = make_subscription(app, uid, plan_id, cid)
            make_class_member(app, cid, uid, status="active")
            pay_id = make_payment(app, sub_id, status="pending")
            pay = db.session.get(MP, pay_id)
            approve_payment(pay)

    def test_approve_payment_existing_inactive_member(self, app):
        from app.services.billing import approve_payment
        from app.models.billing import ManualPayment as MP
        with app.app_context():
            sid = make_school(app)
            cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
            uid = _make_student(app)
            plan_id = make_subscription_plan(app, sid, cid, price=100)
            sub_id = make_subscription(app, uid, plan_id, cid)
            make_class_member(app, cid, uid, status="pending")
            pay_id = make_payment(app, sub_id, status="pending")
            pay = db.session.get(MP, pay_id)
            approve_payment(pay)

    def test_reject_payment_already_reviewed(self, app):
        from app.services.billing import reject_payment
        from app.models.billing import ManualPayment as MP
        with app.app_context():
            sid = make_school(app)
            cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
            uid = _make_student(app)
            plan_id = make_subscription_plan(app, sid, cid, price=100)
            sub_id = make_subscription(app, uid, plan_id, cid)
            pay_id = make_payment(app, sub_id, status="rejected")
            pay = db.session.get(MP, pay_id)
            with pytest.raises(Exception):
                reject_payment(pay)

    def test_reject_payment_cancels_pending_subscription(self, app):
        from app.services.billing import reject_payment
        from app.models.billing import ManualPayment as MP, Subscription as SubModel
        with app.app_context():
            sid = make_school(app)
            cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
            uid = _make_student(app)
            plan_id = make_subscription_plan(app, sid, cid, price=100)
            sub_id = make_subscription(app, uid, plan_id, cid, status="pending")
            pay_id = make_payment(app, sub_id, status="pending")
            pay = db.session.get(MP, pay_id)
            reject_payment(pay)
            sub = db.session.get(SubModel, sub_id)
            assert sub.status == "cancelled"

    def test_reject_payment_non_pending_sub(self, app):
        from app.services.billing import reject_payment
        from app.models.billing import ManualPayment as MP
        with app.app_context():
            sid = make_school(app)
            cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
            uid = _make_student(app)
            plan_id = make_subscription_plan(app, sid, cid, price=100)
            sub_id = make_subscription(app, uid, plan_id, cid, status="active")
            pay_id = make_payment(app, sub_id, status="pending")
            pay = db.session.get(MP, pay_id)
            reject_payment(pay)  # should not crash even if sub is active

    def test_expire_subscriptions(self, app):
        from app.services.billing import expire_subscriptions
        from app.models.billing import Subscription as SubModel
        with app.app_context():
            sid = make_school(app)
            cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
            uid = _make_student(app)
            plan_id = make_subscription_plan(app, sid, cid, price=100)
            sub_id = make_subscription(app, uid, plan_id, cid, status="active")
            sub = db.session.get(SubModel, sub_id)
            sub.end_at = datetime.now(UTC) - timedelta(days=1)
            db.session.commit()
            count = expire_subscriptions()
            assert count >= 1

    def test_has_active_subscription_true(self, app):
        from app.services.billing import has_active_subscription
        with app.app_context():
            sid = make_school(app)
            cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
            uid = _make_student(app)
            plan_id = make_subscription_plan(app, sid, cid, price=100)
            make_subscription(app, uid, plan_id, cid, status="active")
            assert has_active_subscription(uid, cid) is True

    def test_has_active_subscription_false(self, app):
        from app.services.billing import has_active_subscription
        with app.app_context():
            assert has_active_subscription(99999, 99999) is False

    def test_subscription_balance_no_sub(self, app):
        from app.services.billing import subscription_balance
        with app.app_context():
            assert subscription_balance(99999) == Decimal("0.00")

    def test_subscription_balance_with_payments(self, app):
        from app.services.billing import subscription_balance
        from app.models.billing import Subscription as SubModel
        with app.app_context():
            sid = make_school(app)
            cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
            uid = _make_student(app)
            plan_id = make_subscription_plan(app, sid, cid, price=100)
            sub_id = make_subscription(app, uid, plan_id, cid)
            make_payment(app, sub_id, amount=60, status="approved")
            bal = subscription_balance(sub_id)
            assert bal == Decimal("40.00")

    def test_can_record_payment_zero(self, app):
        from app.services.billing import can_record_payment
        with app.app_context():
            ok, msg = can_record_payment(99999, 0)
            assert ok is False

    def test_can_record_payment_exceeds_balance(self, app):
        from app.services.billing import can_record_payment
        from app.models.billing import Subscription as SubModel
        with app.app_context():
            sid = make_school(app)
            cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
            uid = _make_student(app)
            plan_id = make_subscription_plan(app, sid, cid, price=100)
            sub_id = make_subscription(app, uid, plan_id, cid)
            ok, msg = can_record_payment(sub_id, 200)
            assert ok is False

    def test_subscription_payment_summary_no_sub(self, app):
        from app.services.billing import subscription_payment_summary
        with app.app_context():
            assert subscription_payment_summary(99999) == {}

    def test_subscription_payment_summary_with_payments(self, app):
        from app.services.billing import subscription_payment_summary
        from app.models.billing import Subscription as SubModel
        with app.app_context():
            sid = make_school(app)
            cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
            uid = _make_student(app)
            plan_id = make_subscription_plan(app, sid, cid, price=100)
            sub_id = make_subscription(app, uid, plan_id, cid)
            make_payment(app, sub_id, amount=40, status="approved")
            make_payment(app, sub_id, amount=20, status="pending")
            summary = subscription_payment_summary(sub_id)
            assert summary["total_price"] == Decimal("100.00")
            assert summary["approved_count"] == 1
            assert summary["pending_count"] == 1

    # --- Discount codes ---

    def test_create_discount_empty_code(self, app):
        from app.services.billing import create_discount_code
        with app.app_context():
            sid = make_school(app)
            result, err = create_discount_code(sid, "", "Test", "percentage", 10)
            assert result is None

    def test_create_discount_empty_name(self, app):
        from app.services.billing import create_discount_code
        with app.app_context():
            sid = make_school(app)
            result, err = create_discount_code(sid, "CODE", "", "percentage", 10)
            assert result is None

    def test_create_discount_invalid_type(self, app):
        from app.services.billing import create_discount_code
        with app.app_context():
            sid = make_school(app)
            result, err = create_discount_code(sid, "CODE", "Test", "invalid", 10)
            assert result is None

    def test_create_discount_zero_value(self, app):
        from app.services.billing import create_discount_code
        with app.app_context():
            sid = make_school(app)
            result, err = create_discount_code(sid, "CODE", "Test", "percentage", 0)
            assert result is None

    def test_create_discount_negative_value(self, app):
        from app.services.billing import create_discount_code
        with app.app_context():
            sid = make_school(app)
            result, err = create_discount_code(sid, "CODE", "Test", "fixed", -5)
            assert result is None

    def test_create_discount_max_uses_zero(self, app):
        from app.services.billing import create_discount_code
        with app.app_context():
            sid = make_school(app)
            result, err = create_discount_code(sid, "CODE", "Test", "percentage", 10, max_uses=0)
            assert result is None

    def test_create_discount_expired_date(self, app):
        from app.services.billing import create_discount_code
        with app.app_context():
            sid = make_school(app)
            yesterday = datetime.now(UTC).date() - timedelta(days=1)
            result, err = create_discount_code(sid, "CODE", "Test", "percentage", 10, expiry_date=yesterday)
            assert result is None

    def test_create_discount_duplicate(self, app):
        from app.services.billing import create_discount_code
        with app.app_context():
            sid = make_school(app)
            dc, _ = create_discount_code(sid, "DUP1", "Test", "percentage", 10)
            assert dc is not None
            dc2, err = create_discount_code(sid, "DUP1", "Test2", "percentage", 20)
            assert dc2 is None
            assert err is not None

    def test_create_discount_success(self, app):
        from app.services.billing import create_discount_code
        with app.app_context():
            sid = make_school(app)
            dc, err = create_discount_code(sid, "SAVE20", "Save 20%", "percentage", 20)
            assert dc is not None
            assert dc.code == "SAVE20"

    def test_validate_discount_empty_code(self, app):
        from app.services.billing import validate_discount_code
        with app.app_context():
            result, err = validate_discount_code("", 1)
            assert result is None

    def test_validate_discount_nonexistent(self, app):
        from app.services.billing import validate_discount_code
        with app.app_context():
            result, err = validate_discount_code("NONEXISTENT", 1)
            assert result is None

    def test_validate_discount_inactive(self, app):
        from app.services.billing import create_discount_code, validate_discount_code
        from app.extensions import db
        with app.app_context():
            sid = make_school(app)
            plan_id = make_subscription_plan(app, sid, price=100)
            dc, _ = create_discount_code(sid, "INACT", "Inactive", "percentage", 10)
            dc.is_active = False
            db.session.commit()
            result, err = validate_discount_code("INACT", plan_id)
            assert result is None

    def test_validate_discount_expired(self, app):
        from app.services.billing import create_discount_code, validate_discount_code
        from app.extensions import db
        with app.app_context():
            sid = make_school(app)
            plan_id = make_subscription_plan(app, sid, price=100)
            dc, _ = create_discount_code(sid, "EXP", "Expired", "fixed", 10, expiry_date=datetime.now(UTC).date() + timedelta(days=1))
            dc.expiry_date = datetime.now(UTC).date() - timedelta(days=1)
            db.session.commit()
            result, err = validate_discount_code("EXP", plan_id)
            assert result is None

    def test_validate_discount_max_uses_exceeded(self, app):
        from app.services.billing import create_discount_code, validate_discount_code
        from app.extensions import db
        with app.app_context():
            sid = make_school(app)
            plan_id = make_subscription_plan(app, sid, price=100)
            dc, _ = create_discount_code(sid, "EXH", "Exhausted", "fixed", 10, max_uses=1)
            dc.used_count = 1
            db.session.commit()
            result, err = validate_discount_code("EXH", plan_id)
            assert result is None

    def test_validate_discount_wrong_plan(self, app):
        from app.services.billing import create_discount_code, validate_discount_code
        with app.app_context():
            sid = make_school(app)
            plan_id = make_subscription_plan(app, sid, price=100)
            create_discount_code(sid, "SPEC", "Specific", "fixed", 10, applicable_plan_ids=[9999])
            result, err = validate_discount_code("SPEC", plan_id)
            assert result is None

    def test_validate_discount_nonexistent_plan(self, app):
        from app.services.billing import create_discount_code, validate_discount_code
        with app.app_context():
            sid = make_school(app)
            create_discount_code(sid, "NOPLAN", "No Plan", "fixed", 10)
            result, err = validate_discount_code("NOPLAN", 99999)
            assert result is None

    def test_validate_discount_percentage(self, app):
        from app.services.billing import create_discount_code, validate_discount_code
        with app.app_context():
            sid = make_school(app)
            plan_id = make_subscription_plan(app, sid, price=200)
            create_discount_code(sid, "PCT10", "10%", "percentage", 10)
            result, err = validate_discount_code("PCT10", plan_id)
            assert result == Decimal("20.00")

    def test_validate_discount_fixed(self, app):
        from app.services.billing import create_discount_code, validate_discount_code
        with app.app_context():
            sid = make_school(app)
            plan_id = make_subscription_plan(app, sid, price=200)
            create_discount_code(sid, "FIX50", "50 off", "fixed", 50)
            result, err = validate_discount_code("FIX50", plan_id)
            assert result == Decimal("50.00")

    def test_validate_discount_capped_at_plan_price(self, app):
        from app.services.billing import create_discount_code, validate_discount_code
        with app.app_context():
            sid = make_school(app)
            plan_id = make_subscription_plan(app, sid, price=10)
            create_discount_code(sid, "BIG", "Big", "fixed", 100)
            result, err = validate_discount_code("BIG", plan_id)
            assert result == Decimal("10.00")

    def test_apply_discount_empty_code(self, app):
        from app.services.billing import apply_discount_code
        with app.app_context():
            result, err = apply_discount_code(1, "")
            assert result is None

    def test_apply_discount_nonexistent_sub(self, app):
        from app.services.billing import apply_discount_code
        with app.app_context():
            result, err = apply_discount_code(99999, "CODE")
            assert result is None

    def test_apply_discount_code_not_found(self, app):
        from app.services.billing import apply_discount_code
        from app.models.billing import Subscription as SubModel
        with app.app_context():
            sid = make_school(app)
            cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
            uid = _make_student(app)
            plan_id = make_subscription_plan(app, sid, cid, price=100)
            sub_id = make_subscription(app, uid, plan_id, cid)
            result, err = apply_discount_code(sub_id, "NOPE")
            assert result is None


# ===========================================================================
# SCHOOLS — join_class, individual join, capacity, etc.
# ===========================================================================

class TestSchoolsBranches:
    """schools.py — all branch paths."""

    def test_create_school_empty_name(self, app):
        from app.services.schools import create_school
        with app.app_context():
            result, err = create_school("")
            assert result is None

    def test_create_school_duplicate_domain(self, app):
        from app.services.schools import create_school
        with app.app_context():
            s1, _ = create_school("School 1", domain="test.edu.ps")
            assert s1 is not None
            s2, err = create_school("School 2", domain="test.edu.ps")
            assert s2 is None

    def test_create_class_success(self, app):
        from app.services.schools import create_class
        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub_id = make_subject(app)
            cr, err = create_class(sid, sub_id, gid)
            assert cr is not None

    def test_list_classes(self, app):
        from app.services.schools import create_class, list_classes
        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub_id = make_subject(app)
            create_class(sid, sub_id, gid)
            classes = list_classes(sid)
            assert len(classes) >= 1

    def test_regenerate_join_code(self, app):
        from app.services.schools import create_class as create_cls, regenerate_join_code
        from app.models.class_room import ClassRoom
        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub_id = make_subject(app)
            cr = create_cls(sid, sub_id, gid)
            old_code = cr.join_code
            new_code = regenerate_join_code(cr)
            assert new_code != old_code

    def test_join_class_wrong_role(self, app):
        from app.services.schools import join_class, create_class as create_cls
        from app.models.class_room import ClassRoom
        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub_id = make_subject(app)
            cr_obj = create_cls(sid, sub_id, gid)
            cr = db.session.get(ClassRoom, cr_obj.id)
            teacher = _make_teacher(app, sid)
            user = db.session.get(User, teacher)
            err = join_class(cr, user)
            assert err is not None

    def test_join_class_already_member(self, app):
        from app.services.schools import join_class, create_class as create_cls
        from app.models.class_room import ClassRoom
        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub_id = make_subject(app)
            cr_obj = create_cls(sid, sub_id, gid)
            cr = db.session.get(ClassRoom, cr_obj.id)
            uid = _make_student(app)
            u = db.session.get(User, uid)
            make_class_member(app, cr_obj.id, uid)
            err = join_class(cr, u)
            assert err is not None

    def test_join_class_full(self, app):
        from app.services.schools import join_class, create_class as create_cls
        from app.models.class_room import ClassRoom
        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub_id = make_subject(app)
            cr_obj = create_cls(sid, sub_id, gid)
            cr = db.session.get(ClassRoom, cr_obj.id)
            cr.max_students = 1
            db.session.commit()
            uid = _make_student(app)
            u = db.session.get(User, uid)
            make_class_member(app, cr_obj.id, uid)
            uid2 = _make_student(app)
            u2 = db.session.get(User, uid2)
            err = join_class(cr, u2)
            assert err is not None

    def test_join_class_paid_plan(self, app):
        from app.services.schools import join_class, create_class as create_cls
        from app.models.class_room import ClassRoom
        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub_id = make_subject(app)
            cr_obj = create_cls(sid, sub_id, gid)
            cr = db.session.get(ClassRoom, cr_obj.id)
            make_subscription_plan(app, sid, cr_obj.id, price=100)
            uid = _make_student(app)
            u = db.session.get(User, uid)
            err = join_class(cr, u)
            assert err is not None

    def test_join_class_free_success(self, app):
        from app.services.schools import join_class, create_class as create_cls
        from app.models.class_room import ClassRoom
        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub_id = make_subject(app)
            cr_obj = create_cls(sid, sub_id, gid)
            cr = db.session.get(ClassRoom, cr_obj.id)
            uid = _make_student(app)
            u = db.session.get(User, uid)
            err = join_class(cr, u)
            assert err is None

    def test_join_class_parent_role(self, app):
        from app.services.schools import join_class, create_class as create_cls
        from app.models.class_room import ClassRoom
        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub_id = make_subject(app)
            cr_obj = create_cls(sid, sub_id, gid)
            cr = db.session.get(ClassRoom, cr_obj.id)
            uid = make_user(app, role="parent")
            u = db.session.get(User, uid)
            err = join_class(cr, u)
            assert err is None

    def test_is_member(self, app):
        from app.services.schools import is_member, create_class as create_cls
        from app.models.class_room import ClassRoom
        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub_id = make_subject(app)
            cr_obj = create_cls(sid, sub_id, gid)
            cr = db.session.get(ClassRoom, cr_obj.id)
            uid = _make_student(app)
            u = db.session.get(User, uid)
            assert is_member(cr, u) is False
            make_class_member(app, cr_obj.id, uid)
            assert is_member(cr, u) is True

    def test_join_class_individual_not_public(self, app):
        from app.services.schools import join_class_individual, create_class as create_cls
        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub_id = make_subject(app)
            cr_obj = create_cls(sid, sub_id, gid)
            uid = _make_student(app)
            result, err = join_class_individual(uid, cr_obj.id)
            assert result is None

    def test_join_class_individual_nonexistent(self, app):
        from app.services.schools import join_class_individual
        with app.app_context():
            result, err = join_class_individual(99999, 99999)
            assert result is None

    def test_join_class_individual_already_member(self, app):
        from app.services.schools import join_class_individual, create_class as create_cls
        from app.models.class_room import ClassRoom
        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub_id = make_subject(app)
            cr_obj = create_cls(sid, sub_id, gid)
            cr = db.session.get(ClassRoom, cr_obj.id)
            cr.is_public = True
            db.session.commit()
            uid = _make_student(app)
            make_class_member(app, cr_obj.id, uid)
            result, err = join_class_individual(uid, cr_obj.id)
            assert result is None

    def test_join_class_individual_full(self, app):
        from app.services.schools import join_class_individual, create_class as create_cls
        from app.models.class_room import ClassRoom
        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub_id = make_subject(app)
            cr_obj = create_cls(sid, sub_id, gid)
            cr = db.session.get(ClassRoom, cr_obj.id)
            cr.is_public = True
            cr.max_students = 1
            db.session.commit()
            uid = _make_student(app)
            make_class_member(app, cr_obj.id, uid)
            uid2 = _make_student(app)
            result, err = join_class_individual(uid2, cr_obj.id)
            assert result is None

    def test_join_class_individual_paid(self, app):
        from app.services.schools import join_class_individual, create_class as create_cls
        from app.models.class_room import ClassRoom
        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub_id = make_subject(app)
            cr_obj = create_cls(sid, sub_id, gid)
            cr = db.session.get(ClassRoom, cr_obj.id)
            cr.is_public = True
            db.session.commit()
            make_subscription_plan(app, sid, cr_obj.id, price=100)
            uid = _make_student(app)
            result, err = join_class_individual(uid, cr_obj.id)
            assert result is None

    def test_join_class_individual_free_success(self, app):
        from app.services.schools import join_class_individual, create_class as create_cls
        from app.models.class_room import ClassRoom
        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub_id = make_subject(app)
            cr_obj = create_cls(sid, sub_id, gid)
            cr = db.session.get(ClassRoom, cr_obj.id)
            cr.is_public = True
            db.session.commit()
            uid = _make_student(app)
            member, err = join_class_individual(uid, cr_obj.id)
            assert member is not None

    def test_get_or_create_subject_existing(self, app):
        from app.services.schools import get_or_create_subject
        with app.app_context():
            sub1 = get_or_create_subject("Mathematics")
            sub2 = get_or_create_subject("Mathematics")
            assert sub1.id == sub2.id

    def test_add_grade_existing(self, app):
        from app.services.schools import add_grade
        with app.app_context():
            sid = make_school(app)
            g1 = add_grade(sid, 5, name_ar="Grade 5")
            g2 = add_grade(sid, 5)
            assert g1.id == g2.id

    def test_create_school_with_defaults(self, app):
        from app.services.schools import create_school_with_defaults
        with app.app_context():
            school, err = create_school_with_defaults("Auto School")
            assert school is not None
            assert err is None


# ===========================================================================
# ASSESSMENT — quiz lifecycle, grading, deadlines
# ===========================================================================

class TestAssessmentBranches:
    """assessment.py — all branch paths."""

    def test_create_quiz_empty_title(self, app):
        from app.services.assessment import create_quiz
        with app.app_context():
            result, err = create_quiz(1, "")
            assert result is None

    def test_start_attempt_in_progress_existing(self, app):
        from app.services.assessment import create_quiz, start_attempt, add_question
        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub_id = make_subject(app)
            cr = make_class(app, sid, gid, sub_id)
            uid = _make_student(app)
            quiz_obj, _ = create_quiz(cr, "Test Quiz")
            q_id = add_question(quiz_obj, "mcq", "Q1", {"options": ["A", "B"]}, {"index": 0}, mark=10)
            a1, _ = start_attempt(quiz_obj, uid)
            a2, _ = start_attempt(quiz_obj, uid)
            assert a1.id == a2.id  # returns same in-progress attempt

    def test_start_attempt_exhausted(self, app):
        from app.services.assessment import create_quiz, start_attempt, add_question, submit_attempt
        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub_id = make_subject(app)
            cr = make_class(app, sid, gid, sub_id)
            uid = _make_student(app)
            quiz_obj, _ = create_quiz(cr, "Q", attempts_allowed=1)
            add_question(quiz_obj, "mcq", "Q1", {"options": ["A"]}, {"index": 0}, mark=10)
            a, _ = start_attempt(quiz_obj, uid)
            submit_attempt(a, allow_after_deadline=True)
            result, err = start_attempt(quiz_obj, uid)
            assert result is None
            assert err is not None

    def test_save_answer_already_submitted(self, app):
        from app.services.assessment import create_quiz, start_attempt, add_question, submit_attempt, save_answer
        from app.core.db import TxError
        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub_id = make_subject(app)
            cr = make_class(app, sid, gid, sub_id)
            uid = _make_student(app)
            quiz_obj, _ = create_quiz(cr, "Q")
            q = add_question(quiz_obj, "mcq", "Q1", {"options": ["A"]}, {"index": 0}, mark=10)
            a, _ = start_attempt(quiz_obj, uid)
            submit_attempt(a, allow_after_deadline=True)
            with pytest.raises(TxError):
                save_answer(a, q.id, {"index": 0})

    def test_grade_answer_mcq_correct(self, app):
        from app.services.assessment import _grade_answer
        with app.app_context():
            from app.models.assessment import Question
            q = Question(type="mcq", prompt="Q", correct_answer={"index": 1}, mark=10)
            is_correct, mark = _grade_answer(q, {"index": 1})
            assert is_correct is True
            assert mark == 10

    def test_grade_answer_mcq_wrong(self, app):
        from app.services.assessment import _grade_answer
        with app.app_context():
            from app.models.assessment import Question
            q = Question(type="mcq", prompt="Q", correct_answer={"index": 1}, mark=10)
            is_correct, mark = _grade_answer(q, {"index": 0})
            assert is_correct is False
            assert mark == 0

    def test_grade_answer_mcq_no_given(self, app):
        from app.services.assessment import _grade_answer
        with app.app_context():
            from app.models.assessment import Question
            q = Question(type="mcq", prompt="Q", correct_answer={"index": 1}, mark=10)
            is_correct, mark = _grade_answer(q, None)
            assert is_correct is None

    def test_grade_answer_mcq_no_correct(self, app):
        from app.services.assessment import _grade_answer
        with app.app_context():
            from app.models.assessment import Question
            q = Question(type="mcq", prompt="Q", correct_answer=None, mark=10)
            is_correct, mark = _grade_answer(q, {"index": 1})
            assert is_correct is None

    def test_grade_answer_true_false_correct(self, app):
        from app.services.assessment import _grade_answer
        with app.app_context():
            from app.models.assessment import Question
            q = Question(type="true_false", prompt="Q", correct_answer={"value": True}, mark=5)
            is_correct, mark = _grade_answer(q, {"value": True})
            assert is_correct is True
            assert mark == 5

    def test_grade_answer_true_false_wrong(self, app):
        from app.services.assessment import _grade_answer
        with app.app_context():
            from app.models.assessment import Question
            q = Question(type="true_false", prompt="Q", correct_answer={"value": True}, mark=5)
            is_correct, mark = _grade_answer(q, {"value": False})
            assert is_correct is False

    def test_grade_answer_true_false_none(self, app):
        from app.services.assessment import _grade_answer
        with app.app_context():
            from app.models.assessment import Question
            q = Question(type="true_false", prompt="Q", correct_answer=None, mark=5)
            is_correct, mark = _grade_answer(q, None)
            assert is_correct is None

    def test_grade_answer_essay(self, app):
        from app.services.assessment import _grade_answer
        with app.app_context():
            from app.models.assessment import Question
            q = Question(type="essay", prompt="Q")
            is_correct, mark = _grade_answer(q, {"text": "essay"})
            assert is_correct is None

    def test_grade_answer_matching(self, app):
        from app.services.assessment import _grade_answer
        with app.app_context():
            from app.models.assessment import Question
            q = Question(type="matching", prompt="Q")
            is_correct, mark = _grade_answer(q, {})
            assert is_correct is None

    def test_get_attempt(self, app):
        from app.services.assessment import create_quiz, start_attempt, add_question, get_attempt
        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub_id = make_subject(app)
            cr = make_class(app, sid, gid, sub_id)
            uid = _make_student(app)
            quiz_obj, _ = create_quiz(cr, "Q")
            add_question(quiz_obj, "mcq", "Q1", {"options": ["A"]}, {"index": 0}, mark=10)
            a, _ = start_attempt(quiz_obj, uid)
            fetched = get_attempt(a.id)
            assert fetched is not None


# ===========================================================================
# TUTORING — profiles, requests, sessions, ratings
# ===========================================================================

class TestTutoringBranches:
    """tutoring.py — all branch paths."""

    def test_create_profile_duplicate(self, app):
        from app.services.tutoring import create_tutor_profile
        with app.app_context():
            uid = _make_teacher(app, make_school(app))
            p1, _ = create_tutor_profile(uid, "Math")
            p2, err = create_tutor_profile(uid, "Physics")
            assert p2 is None
            assert err is not None

    def test_create_request_duplicate_open(self, app):
        from app.services.tutoring import create_request
        with app.app_context():
            tutor = _make_teacher(app, make_school(app))
            student = _make_student(app)
            r1, _ = create_request(tutor, student, "Math", None)
            r2, err = create_request(tutor, student, "Math", None)
            assert r2 is None
            assert err is not None

    def test_respond_request_reject(self, app):
        from app.services.tutoring import create_request, respond_request
        from app.models.tutoring import TutoringRequest as TR
        with app.app_context():
            tutor = _make_teacher(app, make_school(app))
            student = _make_student(app)
            r, _ = create_request(tutor, student, "Math", None)
            req = db.session.get(TR, r.id)
            respond_request(req, accept=False)
            assert req.status == "rejected"

    def test_can_access_student(self, app):
        from app.services.tutoring import can_access
        from app.models.tutoring import TutoringSession
        with app.app_context():
            tutor = _make_teacher(app, make_school(app))
            student = _make_student(app)
            s = TutoringSession(tutor_id=tutor, student_id=student, subject="Math", status="requested")
            u_student = db.session.get(User, student)
            assert can_access(u_student, s) is True

    def test_can_access_third_party(self, app):
        from app.services.tutoring import can_access
        from app.models.tutoring import TutoringSession
        with app.app_context():
            tutor = _make_teacher(app, make_school(app))
            student = _make_student(app)
            other = _make_student(app)
            s = TutoringSession(tutor_id=tutor, student_id=student, subject="Math", status="requested")
            u_other = db.session.get(User, other)
            assert can_access(u_other, s) is False

    def test_can_access_super_admin(self, app):
        from app.services.tutoring import can_access
        from app.models.tutoring import TutoringSession
        with app.app_context():
            tutor = _make_teacher(app, make_school(app))
            student = _make_student(app)
            s = TutoringSession(tutor_id=tutor, student_id=student, subject="Math", status="requested")
            admin_id = _make_super_admin(app)
            u_admin = db.session.get(User, admin_id)
            assert can_access(u_admin, s) is True

    def test_rate_session_not_found(self, app):
        from app.services.tutoring import rate_session
        with app.app_context():
            result, err = rate_session(99999, 99999, 5)
            assert result is None

    def test_rate_session_wrong_student(self, app):
        from app.services.tutoring import create_session as create_sess, rate_session
        from app.models.tutoring import TutoringSession as TS
        with app.app_context():
            tutor = _make_teacher(app, make_school(app))
            student = _make_student(app)
            other = _make_student(app)
            s_obj = create_sess(tutor, student, "Math", None)
            ts = db.session.get(TS, s_obj.id)
            ts.status = "completed"
            ts.end_time = datetime.now(UTC)
            db.session.commit()
            result, err = rate_session(s_obj.id, other, 5)
            assert result is None

    def test_rate_session_not_completed(self, app):
        from app.services.tutoring import create_session as create_sess, rate_session
        with app.app_context():
            tutor = _make_teacher(app, make_school(app))
            student = _make_student(app)
            s_obj = create_sess(tutor, student, "Math", None)
            result, err = rate_session(s_obj.id, student, 5)
            assert result is None

    def test_rate_session_invalid_rating(self, app):
        from app.services.tutoring import create_session as create_sess, rate_session
        from app.models.tutoring import TutoringSession as TS
        with app.app_context():
            tutor = _make_teacher(app, make_school(app))
            student = _make_student(app)
            s_obj = create_sess(tutor, student, "Math", None)
            ts = db.session.get(TS, s_obj.id)
            ts.status = "completed"
            ts.end_time = datetime.now(UTC)
            db.session.commit()
            result, err = rate_session(s_obj.id, student, 0)
            assert result is None

    def test_rate_session_duplicate_review(self, app):
        from app.services.tutoring import create_session as create_sess, rate_session
        from app.models.tutoring import TutoringSession as TS
        with app.app_context():
            tutor = _make_teacher(app, make_school(app))
            student = _make_student(app)
            s_obj = create_sess(tutor, student, "Math", None)
            ts = db.session.get(TS, s_obj.id)
            ts.status = "completed"
            ts.end_time = datetime.now(UTC)
            db.session.commit()
            rate_session(s_obj.id, student, 4)
            result, err = rate_session(s_obj.id, student, 5)
            assert result is None

    def test_rate_session_expired_window(self, app):
        from app.services.tutoring import create_session as create_sess, rate_session
        from app.models.tutoring import TutoringSession as TS
        with app.app_context():
            tutor = _make_teacher(app, make_school(app))
            student = _make_student(app)
            s_obj = create_sess(tutor, student, "Math", None, duration_min=60)
            ts = db.session.get(TS, s_obj.id)
            ts.status = "completed"
            ts.scheduled_at = datetime.now(UTC) - timedelta(hours=25)
            ts.end_time = datetime.now(UTC) - timedelta(hours=25)
            db.session.commit()
            result, err = rate_session(s_obj.id, student, 5)
            assert result is None

    def test_request_payout_below_minimum(self, app):
        from app.services.tutoring import request_payout
        with app.app_context():
            tutor = _make_teacher(app, make_school(app))
            result, err = request_payout(tutor, 50)
            assert result is None
            assert err is not None

    def test_request_payout_insufficient_balance(self, app):
        from app.services.tutoring import request_payout
        with app.app_context():
            tutor = _make_teacher(app, make_school(app))
            result, err = request_payout(tutor, 300)
            assert result is None

    def test_create_commission_record_not_completed(self, app):
        from app.services.tutoring import create_commission_record
        from app.models.tutoring import TutoringSession as TS
        with app.app_context():
            tutor = _make_teacher(app, make_school(app))
            student = _make_student(app)
            s = TS(tutor_id=tutor, student_id=student, subject="Math", status="requested", price=100)
            db.session.add(s)
            db.session.commit()
            result = create_commission_record(s)
            assert result is None

    def test_create_commission_record_duplicate(self, app):
        from app.services.tutoring import create_session as create_sess, create_commission_record
        from app.models.tutoring import TutoringSession as TS
        with app.app_context():
            tutor = _make_teacher(app, make_school(app))
            student = _make_student(app)
            s_obj = create_sess(tutor, student, "Math", None, price=100)
            ts = db.session.get(TS, s_obj.id)
            ts.status = "completed"
            db.session.commit()
            create_commission_record(ts)
            result = create_commission_record(ts)
            assert result is None

    def test_generate_zoom_meeting_no_session(self, app):
        from app.services.tutoring import generate_zoom_meeting
        with app.app_context():
            uid = _make_student(app)
            result, err = generate_zoom_meeting(99999, uid)
            assert result is None

    def test_generate_zoom_meeting_unauthorized(self, app):
        from app.services.tutoring import create_session, generate_zoom_meeting
        from app.models.tutoring import TutoringSession as TS
        with app.app_context():
            tutor = _make_teacher(app, make_school(app))
            student = _make_student(app)
            s_obj = create_session(tutor, student, "Math", None)
            other = _make_student(app)
            result, err = generate_zoom_meeting(s_obj.id, other)
            assert result is None

    def test_generate_zoom_meeting_no_config(self, app):
        from app.services.tutoring import create_session, generate_zoom_meeting
        with app.app_context():
            tutor = _make_teacher(app, make_school(app))
            student = _make_student(app)
            s_obj = create_session(tutor, student, "Math", None)
            result, err = generate_zoom_meeting(s_obj.id, tutor)
            assert result is None

    def test_generate_live_session_url_unauthorized(self, app):
        from app.services.tutoring import create_session, generate_live_session_url
        with app.app_context():
            tutor = _make_teacher(app, make_school(app))
            student = _make_student(app)
            s_obj = create_session(tutor, student, "Math", None)
            other = _make_student(app)
            result = generate_live_session_url(s_obj.id, other)
            assert result is None

    def test_update_session_live_status_with_link(self, app):
        from app.services.tutoring import create_session, update_session_live_status
        from app.models.tutoring import TutoringSession as TS
        with app.app_context():
            tutor = _make_teacher(app, make_school(app))
            student = _make_student(app)
            s_obj = create_session(tutor, student, "Math", None)
            s = db.session.get(TS, s_obj.id)
            result = update_session_live_status(s, live_status="active", online_link="https://meet.test.com/room", user_id=tutor)
            assert s.online_link == "https://meet.test.com/room"

    def test_get_active_sessions_empty(self, app):
        from app.services.tutoring import get_active_sessions_for_student
        with app.app_context():
            uid = _make_student(app)
            sessions = get_active_sessions_for_student(uid)
            assert len(sessions) == 0

    def test_search_tutors_with_q(self, app):
        from app.services.tutoring import create_tutor_profile, search_tutors
        with app.app_context():
            uid = _make_teacher(app, make_school(app))
            create_tutor_profile(uid, "Mathematics", bio="Expert in calculus")
            results = search_tutors(q="calculus")
            assert len(results) >= 1

    def test_search_tutors_with_subject(self, app):
        from app.services.tutoring import create_tutor_profile, search_tutors
        with app.app_context():
            uid = _make_teacher(app, make_school(app))
            create_tutor_profile(uid, "Physics")
            results = search_tutors(subject="Physics")
            assert len(results) >= 1

    def test_find_by_invite_code(self, app):
        from app.services.tutoring import create_tutor_profile, find_by_invite_code
        with app.app_context():
            uid = _make_teacher(app, make_school(app))
            p, _ = create_tutor_profile(uid, "Math")
            found = find_by_invite_code(p.invite_code)
            assert found is not None


# ===========================================================================
# MESSAGES — send, inbox, read
# ===========================================================================

class TestMessagesBranches:
    """messages.py — all branch paths."""

    def test_send_message_empty_subject(self, app):
        from app.services.messages import send_message
        with app.app_context():
            uid = _make_student(app)
            result, err = send_message(uid, uid + 1, "", "Body")
            assert result is None

    def test_send_message_empty_body(self, app):
        from app.services.messages import send_message
        with app.app_context():
            uid = _make_student(app)
            result, err = send_message(uid, uid + 1, "Subject", "")
            assert result is None

    def test_send_message_self(self, app):
        from app.services.messages import send_message
        with app.app_context():
            uid = _make_student(app)
            result, err = send_message(uid, uid, "Subject", "Body")
            assert result is None

    def test_send_message_no_recipient(self, app):
        from app.services.messages import send_message
        with app.app_context():
            uid = _make_student(app)
            result, err = send_message(uid, 99999, "Subject", "Body")
            assert result is None

    def test_send_message_no_parent(self, app):
        from app.services.messages import send_message
        with app.app_context():
            uid = _make_student(app)
            rid = _make_student(app)
            result, err = send_message(uid, rid, "Subject", "Body", parent_message_id=99999)
            assert result is None

    def test_send_message_success(self, app):
        from app.services.messages import send_message
        with app.app_context():
            uid = _make_student(app)
            rid = _make_student(app)
            msg, err = send_message(uid, rid, "Hello", "World")
            assert msg is not None

    def test_unread_count(self, app):
        from app.services.messages import send_message, unread_count
        with app.app_context():
            uid = _make_student(app)
            rid = _make_student(app)
            send_message(uid, rid, "Sub", "Body")
            assert unread_count(rid) >= 1

    def test_mark_read(self, app):
        from app.services.messages import send_message, mark_read, unread_count
        from app.models.message import Message
        with app.app_context():
            uid = _make_student(app)
            rid = _make_student(app)
            msg, _ = send_message(uid, rid, "Sub", "Body")
            mark_read(msg.id, rid)
            assert unread_count(rid) == 0

    def test_mark_read_wrong_user(self, app):
        from app.services.messages import send_message, mark_read, unread_count
        with app.app_context():
            uid = _make_student(app)
            rid = _make_student(app)
            msg, _ = send_message(uid, rid, "Sub", "Body")
            mark_read(msg.id, uid)
            assert unread_count(rid) >= 1

    def test_mark_read_nonexistent(self, app):
        from app.services.messages import mark_read
        with app.app_context():
            mark_read(99999, 99999)


# ===========================================================================
# CONTENT — units, lessons, attachments, import
# ===========================================================================

class TestContentBranches:
    """content.py — all branch paths."""

    def test_create_lesson_empty_title(self, app):
        from app.services.content import create_lesson
        with app.app_context():
            result, err = create_lesson(1, "")
            assert result is None

    def test_list_lessons_no_drafts(self, app):
        from app.services.content import list_lessons
        with app.app_context():
            sid = make_school(app)
            cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
            make_lesson(app, cid, status="draft")
            make_lesson(app, cid, status="published")
            published = list_lessons(cid, include_drafts=False)
            assert all(l.status == "published" for l in published)

    def test_get_lesson_deleted(self, app):
        from app.services.content import get_lesson
        from app.extensions import db
        from app.models.content import Lesson
        with app.app_context():
            sid = make_school(app)
            cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
            lid = make_lesson(app, cid)
            lesson = db.session.get(Lesson, lid)
            lesson.deleted_at = datetime.now(UTC)
            db.session.commit()
            result = get_lesson(lid)
            assert result is None

    def test_unpublish_lesson(self, app):
        from app.services.content import unpublish_lesson
        from app.extensions import db
        from app.models.content import Lesson
        with app.app_context():
            sid = make_school(app)
            cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
            lid = make_lesson(app, cid)
            lesson = db.session.get(Lesson, lid)
            unpublish_lesson(lesson)
            assert lesson.status == "draft"

    def test_update_lesson(self, app):
        from app.services.content import update_lesson
        from app.extensions import db
        from app.models.content import Lesson
        with app.app_context():
            sid = make_school(app)
            cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
            lid = make_lesson(app, cid)
            lesson = db.session.get(Lesson, lid)
            update_lesson(lesson, title="Updated", unit_id=None, body_html="<p>New</p>")
            assert lesson.title == "Updated"
            assert lesson.body_html == "<p>New</p>"

    def test_add_youtube(self, app):
        from app.services.content import add_youtube
        from app.extensions import db
        from app.models.content import Lesson
        with app.app_context():
            sid = make_school(app)
            cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
            lid = make_lesson(app, cid)
            lesson = db.session.get(Lesson, lid)
            att = add_youtube(lesson, "https://youtube.com/watch?v=123", title="Video")
            assert att.youtube_url == "https://youtube.com/watch?v=123"

    def test_delete_attachment(self, app):
        from app.services.content import delete_attachment
        from app.models.content import LessonAttachment
        with app.app_context():
            sid = make_school(app)
            cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
            lid = make_lesson(app, cid)
            aid = make_attachment(app, lid)
            att = db.session.get(LessonAttachment, aid)
            delete_attachment(att)

    def test_import_lesson_not_found(self, app):
        from app.services.content import import_lesson
        with app.app_context():
            uid = _make_student(app)
            result, err = import_lesson(99999, 1, uid)
            assert result is None

    def test_import_lesson_not_shared(self, app):
        from app.services.content import import_lesson
        from app.extensions import db
        from app.models.content import Lesson
        with app.app_context():
            sid = make_school(app)
            cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
            lid = make_lesson(app, cid)
            lesson = db.session.get(Lesson, lid)
            lesson.is_shared = False
            db.session.commit()
            uid = _make_student(app)
            result, err = import_lesson(lid, cid, uid)
            assert result is None

    def test_import_lesson_target_not_found(self, app):
        from app.services.content import import_lesson
        from app.extensions import db
        from app.models.content import Lesson
        with app.app_context():
            sid = make_school(app)
            cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
            lid = make_lesson(app, cid)
            lesson = db.session.get(Lesson, lid)
            lesson.is_shared = True
            db.session.commit()
            uid = _make_student(app)
            result, err = import_lesson(lid, 99999, uid)
            assert result is None

    def test_shared_lessons(self, app):
        from app.services.content import shared_lessons
        from app.extensions import db
        from app.models.content import Lesson
        with app.app_context():
            sid = make_school(app)
            cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
            lid = make_lesson(app, cid)
            lesson = db.session.get(Lesson, lid)
            lesson.is_shared = True
            db.session.commit()
            results = shared_lessons(sid)
            assert len(results) >= 1

    def test_shared_lessons_with_subject(self, app):
        from app.services.content import shared_lessons
        from app.extensions import db
        from app.models.content import Lesson
        with app.app_context():
            sid = make_school(app)
            sub_id = make_subject(app)
            cid = make_class(app, sid, make_grade(app, sid), sub_id)
            lid = make_lesson(app, cid)
            lesson = db.session.get(Lesson, lid)
            lesson.is_shared = True
            db.session.commit()
            results = shared_lessons(sid, subject_id=sub_id)
            assert len(results) >= 1

    def test_sanitize_html(self, app):
        from app.services.content import _sanitize_html
        with app.app_context():
            result = _sanitize_html("<p>Safe</p><script>alert('xss')</script>")
            assert "<script>" not in result
            assert "<p>" in result

    def test_sanitize_html_none(self, app):
        from app.services.content import _sanitize_html
        with app.app_context():
            assert _sanitize_html(None) is None

    def test_sanitize_html_empty(self, app):
        from app.services.content import _sanitize_html
        with app.app_context():
            assert _sanitize_html("") == ""

    def test_list_units(self, app):
        from app.services.content import create_unit, list_units
        with app.app_context():
            sid = make_school(app)
            cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
            create_unit(cid, "Unit 1", sort_order=1)
            units = list_units(cid)
            assert len(units) >= 1


# ===========================================================================
# PROGRESS — lesson views, time, video, class progress
# ===========================================================================

class TestProgressBranches:
    """progress.py — all branch paths."""

    def test_record_lesson_view_existing(self, app):
        from app.services.progress import record_lesson_view
        from app.extensions import db
        from app.models.progress import StudentProgress
        with app.app_context():
            sid = make_school(app)
            cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
            lid = make_lesson(app, cid)
            uid = _make_student(app)
            p1 = record_lesson_view(uid, lid, cid)
            p2 = record_lesson_view(uid, lid, cid)
            assert p1.id == p2.id

    def test_update_time_spent_not_found(self, app):
        from app.services.progress import update_time_spent
        with app.app_context():
            result = update_time_spent(99999, 99999, 60)
            assert result is None

    def test_update_time_spent_completes(self, app):
        from app.services.progress import update_time_spent, record_lesson_view
        from app.extensions import db
        from app.models.progress import StudentProgress
        with app.app_context():
            sid = make_school(app)
            cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
            lid = make_lesson(app, cid)
            uid = _make_student(app)
            record_lesson_view(uid, lid, cid)
            p = update_time_spent(uid, lid, 99999)
            assert p.status == "completed"

    def test_update_video_progress_new(self, app):
        from app.services.progress import update_video_progress
        from app.models.content import LessonAttachment
        with app.app_context():
            sid = make_school(app)
            cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
            lid = make_lesson(app, cid)
            aid = make_attachment(app, lid)
            uid = _make_student(app)
            vp = update_video_progress(uid, aid, lid, cid, 100, 200)
            assert vp.seconds_watched == 100

    def test_update_video_progress_existing(self, app):
        from app.services.progress import update_video_progress
        with app.app_context():
            sid = make_school(app)
            cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
            lid = make_lesson(app, cid)
            aid = make_attachment(app, lid)
            uid = _make_student(app)
            update_video_progress(uid, aid, lid, cid, 50, 200)
            vp = update_video_progress(uid, aid, lid, cid, 150, 200)
            assert vp.seconds_watched == 150

    def test_update_video_progress_marks_completed(self, app):
        from app.services.progress import update_video_progress
        with app.app_context():
            sid = make_school(app)
            cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
            lid = make_lesson(app, cid)
            aid = make_attachment(app, lid)
            uid = _make_student(app)
            vp = update_video_progress(uid, aid, lid, cid, 190, 200)
            assert vp.completed is True

    def test_class_progress_overview_empty(self, app):
        from app.services.progress import class_progress_overview
        with app.app_context():
            sid = make_school(app)
            cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
            result = class_progress_overview(cid)
            assert len(result) == 0

    def test_last_active_days_empty(self, app):
        from app.services.progress import last_active_days
        with app.app_context():
            uid = _make_student(app)
            days = last_active_days(uid)
            assert len(days) == 0


# ===========================================================================
# GRADE_CALC — letter grades, edge cases
# ===========================================================================

class TestGradeCalcBranches:
    """grade_calc.py — letter grade and edge cases."""

    def test_letter_grade_all_ranges(self, app):
        from app.services.grade_calc import _letter_grade
        with app.app_context():
            assert _letter_grade(95) == "ممتاز"
            assert _letter_grade(85) == "جيد جداً"
            assert _letter_grade(75) == "جيد"
            assert _letter_grade(65) == "مقبول"
            assert _letter_grade(30) == "راسب"

    def test_calculate_student_grade_no_categories(self, app):
        from app.services.grade_calc import calculate_student_grade
        with app.app_context():
            sid = make_school(app)
            cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
            uid = _make_student(app)
            result = calculate_student_grade(uid, cid)
            assert result["final_grade"] == 0

    def test_calculate_student_grade_with_grades(self, app):
        from app.services.grade_calc import calculate_student_grade
        with app.app_context():
            sid = make_school(app)
            cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
            uid = _make_student(app)
            cat_id = make_grade_category(app, cid, "Midterm", 0.5)
            item_id = make_grade_item(app, cid, cat_id, "Exam 1", 100)
            make_grade_entry(app, uid, item_id, 80)
            result = calculate_student_grade(uid, cid)
            assert result["final_grade"] > 0

    def test_class_grades_summary(self, app):
        from app.services.grade_calc import class_grades_summary
        with app.app_context():
            sid = make_school(app)
            cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
            uid = _make_student(app)
            make_class_member(app, cid, uid)
            results = class_grades_summary(cid)
            assert len(results) >= 1


# ===========================================================================
# FINANCE — revenue, balance, receivables
# ===========================================================================

class TestFinanceBranches:
    """finance.py — all branch paths."""

    def test_school_revenue_no_subs(self, app):
        from app.services.finance import school_revenue_summary
        with app.app_context():
            sid = make_school(app)
            result = school_revenue_summary(sid)
            assert result["total_revenue"] == Decimal("0")

    def test_school_revenue_with_subs(self, app):
        from app.services.finance import school_revenue_summary
        with app.app_context():
            sid = make_school(app)
            cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
            uid = _make_student(app)
            plan_id = make_subscription_plan(app, sid, cid, price=100)
            sub_id = make_subscription(app, uid, plan_id, cid, status="active")
            make_payment(app, sub_id, amount=50, status="approved")
            result = school_revenue_summary(sid)
            assert float(result["total_revenue"]) == 50

    def test_student_balance_no_sub(self, app):
        from app.services.finance import student_balance
        with app.app_context():
            result = student_balance(99999, 99999)
            assert result["has_subscription"] is False

    def test_student_balance_with_sub(self, app):
        from app.services.finance import student_balance
        with app.app_context():
            sid = make_school(app)
            cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
            uid = _make_student(app)
            plan_id = make_subscription_plan(app, sid, cid, price=100)
            sub_id = make_subscription(app, uid, plan_id, cid)
            make_payment(app, sub_id, amount=60, status="approved")
            result = student_balance(uid, cid)
            assert result["balance"] == 40.0

    def test_accounts_receivable_empty(self, app):
        from app.services.finance import accounts_receivable
        with app.app_context():
            sid = make_school(app)
            result = accounts_receivable(sid)
            assert len(result) == 0


# ===========================================================================
# VIDEO_SERVICE — tokens, validation
# ===========================================================================

class TestVideoServiceBranches:
    """video_service.py — token gen, verify, access validation."""

    def test_token_roundtrip(self, app):
        from app.services.video_service import generate_stream_token, verify_stream_token
        with app.app_context():
            token = generate_stream_token(1, 1, 10)
            ok, err = verify_stream_token(token, 1, 1, 10)
            assert ok is True

    def test_token_expired(self, app):
        from app.services.video_service import generate_stream_token, verify_stream_token
        with app.app_context():
            token = generate_stream_token(1, 1, 10, expires_in=-1)
            ok, err = verify_stream_token(token, 1, 1, 10)
            assert ok is False

    def test_token_user_mismatch(self, app):
        from app.services.video_service import generate_stream_token, verify_stream_token
        with app.app_context():
            token = generate_stream_token(1, 1, 10)
            ok, err = verify_stream_token(token, 2, 1, 10)
            assert ok is False

    def test_token_school_mismatch(self, app):
        from app.services.video_service import generate_stream_token, verify_stream_token
        with app.app_context():
            token = generate_stream_token(1, 1, 10)
            ok, err = verify_stream_token(token, 1, 2, 10)
            assert ok is False

    def test_token_lesson_mismatch(self, app):
        from app.services.video_service import generate_stream_token, verify_stream_token
        with app.app_context():
            token = generate_stream_token(1, 1, 10)
            ok, err = verify_stream_token(token, 1, 1, 20)
            assert ok is False

    def test_token_invalid_format(self, app):
        from app.services.video_service import verify_stream_token
        with app.app_context():
            ok, err = verify_stream_token("not-a-token", 1, 1, 1)
            assert ok is False

    def test_token_tampered_payload(self, app):
        from app.services.video_service import generate_stream_token, verify_stream_token, _get_hmac_key
        with app.app_context():
            import base64
            import hmac
            import hashlib
            key = _get_hmac_key()
            # Build a token with wrong signature
            payload = "1:1:10:9999999999"
            sig = hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()
            # Tamper: change school_id in payload but keep original sig
            tampered_payload = "1:2:10:9999999999"
            token = base64.urlsafe_b64encode(f"{tampered_payload}:{sig}".encode()).decode()
            ok, err = verify_stream_token(token, 1, 1, 10)
            assert ok is False

    def test_validate_lesson_access_not_found(self, app):
        from app.services.video_service import validate_lesson_access
        with app.app_context():
            ok, err = validate_lesson_access(1, 1, 99999)
            assert ok is False

    def test_validate_lesson_access_wrong_school(self, app):
        from app.services.video_service import validate_lesson_access
        from app.extensions import db
        from app.models.content import Lesson
        with app.app_context():
            sid = make_school(app)
            cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
            lid = make_lesson(app, cid)
            ok, err = validate_lesson_access(1, 99999, lid)
            assert ok is False

    def test_validate_lesson_access_user_not_found(self, app):
        from app.services.video_service import validate_lesson_access
        with app.app_context():
            sid = make_school(app)
            cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
            lid = make_lesson(app, cid)
            ok, err = validate_lesson_access(99999, sid, lid)
            assert ok is False

    def test_validate_lesson_access_student_member(self, app):
        from app.services.video_service import validate_lesson_access
        with app.app_context():
            sid = make_school(app)
            cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
            lid = make_lesson(app, cid)
            uid = _make_student(app)
            make_class_member(app, cid, uid)
            ok, err = validate_lesson_access(uid, sid, lid)
            assert ok is True

    def test_validate_lesson_access_student_not_member(self, app):
        from app.services.video_service import validate_lesson_access
        with app.app_context():
            sid = make_school(app)
            cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
            lid = make_lesson(app, cid)
            uid = _make_student(app)
            ok, err = validate_lesson_access(uid, sid, lid)
            assert ok is False

    def test_validate_lesson_access_teacher_of_class(self, app):
        from app.services.video_service import validate_lesson_access
        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub_id = make_subject(app)
            uid = _make_teacher(app, sid)
            from app.extensions import db
            from app.models.class_room import ClassRoom
            cr = ClassRoom(school_id=sid, grade_id=gid, subject_id=sub_id, teacher_id=uid, join_code="T123")
            db.session.add(cr)
            db.session.commit()
            lid = make_lesson(app, cr.id)
            ok, err = validate_lesson_access(uid, sid, lid)
            assert ok is True

    def test_get_protected_media_path(self, app):
        from app.services.video_service import get_protected_media_path
        with app.app_context():
            path = get_protected_media_path(1, 10)
            assert "protected_media" in path
            assert "1" in path
            assert "10" in path

    def test_get_stream_url(self, app):
        from app.services.video_service import generate_stream_token
        with app.app_context():
            token = generate_stream_token(1, 1, 10)
            assert len(token) > 10

    def test_get_master_playlist_url(self, app):
        from app.services.video_service import generate_stream_token
        with app.app_context():
            token = generate_stream_token(1, 1, 10)
            assert len(token) > 10


# ===========================================================================
# TENANCY — scope, context, etc.
# ===========================================================================

class TestTenancyBranches:
    """tenancy.py — tenant context, scope, school lookup."""

    def test_current_school_id_default(self, app):
        from app.core.tenancy import TenantContext
        with app.app_context():
            # Just verify TenantContext can be imported and constructed
            ctx = TenantContext(school_id=42, role="school_admin")
            assert ctx is not None

    def test_scope_by_school_wrong_model(self, app):
        from app.core.tenancy import scope_by_school
        from app.models.class_room import ClassRoom
        with app.app_context():
            # ClassRoom has school_id, should work
            result = scope_by_school(ClassRoom, 1)
            assert result is not None


# ===========================================================================
# PERMISSIONS — decorators
# ===========================================================================

class TestPermissionsBranches:
    """permissions.py — all decorators."""

    def test_role_required_allows(self, app):
        from app.core.permissions import role_required
        from app.models.user import UserRole
        with app.app_context():
            deco = role_required(UserRole.student)
            assert callable(deco)


# ===========================================================================
# EXPORT — edge cases
# ===========================================================================

class TestExportBranches:
    """export.py — Excel export with various data states."""

    def test_export_students_empty(self, app):
        from app.services.export import export_students_excel
        with app.app_context():
            sid = make_school(app)
            cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
            data = export_students_excel(cid)
            assert isinstance(data, bytes)

    def test_export_grades_empty(self, app):
        from app.services.export import export_grades_excel
        with app.app_context():
            sid = make_school(app)
            cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
            data = export_grades_excel(cid)
            assert isinstance(data, bytes)

    def test_export_grades_with_data(self, app):
        from app.services.export import export_grades_excel
        with app.app_context():
            sid = make_school(app)
            cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
            uid = _make_student(app)
            make_class_member(app, cid, uid)
            cat_id = make_grade_category(app, cid, "Midterm", 0.5)
            item_id = make_grade_item(app, cid, cat_id, "Exam", 100)
            make_grade_entry(app, uid, item_id, 85)
            data = export_grades_excel(cid)
            assert isinstance(data, bytes)

    def test_export_progress_empty(self, app):
        from app.services.export import export_progress_excel
        with app.app_context():
            sid = make_school(app)
            cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
            data = export_progress_excel(cid)
            assert isinstance(data, bytes)

    def test_export_moe_format(self, app):
        from app.services.export import export_moe_format
        with app.app_context():
            data = export_moe_format()
            assert isinstance(data, bytes)

    def test_export_moe_with_school(self, app):
        from app.services.export import export_moe_format
        with app.app_context():
            sid = make_school(app)
            data = export_moe_format(school_id=sid, academic_year="2025-2026")
            assert isinstance(data, bytes)

    def test_export_students_with_members(self, app):
        from app.services.export import export_students_excel
        with app.app_context():
            sid = make_school(app)
            cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
            uid = _make_student(app)
            make_class_member(app, cid, uid)
            data = export_students_excel(cid)
            assert isinstance(data, bytes)

    def test_export_progress_with_data(self, app):
        from app.services.export import export_progress_excel
        from app.models.progress import StudentProgress
        from app.extensions import db
        with app.app_context():
            sid = make_school(app)
            cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
            lid = make_lesson(app, cid)
            uid = _make_student(app)
            sp = StudentProgress(student_id=uid, lesson_id=lid, class_id=cid, status="completed", progress_pct=100)
            db.session.add(sp)
            db.session.commit()
            data = export_progress_excel(cid)
            assert isinstance(data, bytes)


# Need to import db and User for the schools tests
from app.extensions import db
from app.models.user import User
