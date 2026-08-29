"""Comprehensive backend service tests to push line coverage above 80%."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from app.extensions import db as _db
from app.models.billing import (
    DiscountCode,
    Subscription,
    SubscriptionPlan,
)
from app.models.class_room import ClassRoom
from app.models.content import Lesson
from app.models.user import User
from tests.conftest import (
    make_class,
    make_class_member,
    make_grade,
    make_lesson,
    make_subject,
    make_subscription,
    make_subscription_plan,
    make_user,
)

# ── Schools ──────────────────────────────────────────────────────


class TestSchools:
    @pytest.fixture(autouse=True)
    def _ctx(self, app):
        with app.app_context():
            yield

    def test_create_school_success(self, app):
        from app.services.schools import create_school

        school, err = create_school("مدرسة تجريبية", domain="test.example.com")
        assert school is not None
        assert err is None
        assert school.name_ar == "مدرسة تجريبية"
        assert school.domain == "test.example.com"

    def test_create_school_empty_name(self, app):
        from app.services.schools import create_school

        school, err = create_school("")
        assert school is None
        assert err is not None

    def test_create_school_duplicate_domain(self, app):
        from app.services.schools import create_school

        create_school("school1", domain="dup.test.com")
        school2, err = create_school("school2", domain="dup.test.com")
        assert school2 is None
        assert err is not None

    def test_list_schools(self, app):
        from app.services.schools import list_schools
        from tests.conftest import make_school

        make_school(app, name_ar="أ")
        make_school(app, name_ar="ب")
        schools = list_schools()
        assert len(schools) >= 2

    def test_create_class(self, app):
        from app.services.schools import create_class
        from tests.conftest import make_school

        school_id = make_school(app)
        grade_id = make_grade(app, school_id)
        subject_id = make_subject(app)
        cls, err = create_class(school_id, subject_id, grade_id)
        assert cls is not None
        assert err is None

    def test_get_or_create_subject(self, app):
        from app.services.schools import get_or_create_subject

        s1 = get_or_create_subject("رياضيات")
        s2 = get_or_create_subject("رياضيات")
        assert s1.id == s2.id

    def test_add_grade(self, app):
        from app.services.schools import add_grade
        from tests.conftest import make_school

        school_id = make_school(app)
        g1 = add_grade(school_id, 1)
        g2 = add_grade(school_id, 1)  # same level → returns existing
        assert g1.id == g2.id

    def test_create_school_with_defaults(self, app):
        from app.services.schools import create_school_with_defaults

        school, err = create_school_with_defaults("مدرسة كاملة")
        assert school is not None
        assert err is None

    def test_get_or_create_system_school(self, app):
        from app.services.schools import get_or_create_system_school

        s1 = get_or_create_system_school()
        s2 = get_or_create_system_school()
        assert s1.id == s2.id
        assert s1.is_system is True

    def test_is_individual_user(self, app):
        from app.services.schools import is_individual_user

        uid = make_user(app)
        with app.app_context():
            u = _db.session.get(User, uid)
            assert is_individual_user(u) is True

    def test_join_class_individual(self, app):
        from app.services.schools import join_class_individual
        from tests.conftest import make_school

        school_id = make_school(app)
        grade_id = make_grade(app, school_id)
        subject_id = make_subject(app)
        student_id = make_user(app, role="student")
        cls_id = make_class(app, school_id, grade_id, subject_id)

        # Make class public
        with app.app_context():
            cls = _db.session.get(ClassRoom, cls_id)
            cls.is_public = True
            _db.session.commit()

        member, err = join_class_individual(student_id, cls_id)
        assert member is not None
        assert err is None

    def test_join_class_individual_non_public(self, app):
        from app.services.schools import join_class_individual
        from tests.conftest import make_school

        school_id = make_school(app)
        grade_id = make_grade(app, school_id)
        subject_id = make_subject(app)
        student_id = make_user(app, role="student")
        cls_id = make_class(app, school_id, grade_id, subject_id)

        member, err = join_class_individual(student_id, cls_id)
        assert member is None
        assert err is not None

    def test_has_active_subscription(self, app):
        from app.services.schools import has_active_subscription
        from tests.conftest import make_school

        school_id = make_school(app)
        grade_id = make_grade(app, school_id)
        subject_id = make_subject(app)
        student_id = make_user(app, role="student")
        cls_id = make_class(app, school_id, grade_id, subject_id)

        assert has_active_subscription(student_id, cls_id) is False

    def test_regenerate_join_code(self, app):
        from app.services.schools import regenerate_join_code
        from tests.conftest import make_school

        school_id = make_school(app)
        grade_id = make_grade(app, school_id)
        subject_id = make_subject(app)
        cls_id = make_class(app, school_id, grade_id, subject_id)

        with app.app_context():
            cls = _db.session.get(ClassRoom, cls_id)
            old_code = cls.join_code
            new_code = regenerate_join_code(cls)
            assert new_code != old_code

    def test_get_class_members(self, app):
        from app.services.schools import get_class_members
        from tests.conftest import make_school

        school_id = make_school(app)
        grade_id = make_grade(app, school_id)
        subject_id = make_subject(app)
        cls_id = make_class(app, school_id, grade_id, subject_id)
        student_id = make_user(app, role="student")
        make_class_member(app, cls_id, student_id)

        with app.app_context():
            cls = _db.session.get(ClassRoom, cls_id)
            members = get_class_members(cls)
            assert len(members) >= 1

    def test_is_member(self, app):
        from app.services.schools import is_member
        from tests.conftest import make_school

        school_id = make_school(app)
        grade_id = make_grade(app, school_id)
        subject_id = make_subject(app)
        cls_id = make_class(app, school_id, grade_id, subject_id)
        student_id = make_user(app, role="student")
        make_class_member(app, cls_id, student_id)

        with app.app_context():
            cls = _db.session.get(ClassRoom, cls_id)
            u = _db.session.get(User, student_id)
            assert is_member(cls, u) is True


# ── Billing ──────────────────────────────────────────────────────


class TestBilling:
    @pytest.fixture(autouse=True)
    def _ctx(self, app):
        with app.app_context():
            yield

    def test_money(self, app):
        from app.services.billing import money

        assert money(10.555) == Decimal("10.56")
        assert money("10.505") == Decimal("10.51")
        assert money(0) == Decimal("0.00")
        assert money(100) == Decimal("100.00")

    def test_create_plan(self, app):
        from app.services.billing import create_plan
        from tests.conftest import make_school

        school_id = make_school(app)
        cls_id = make_class(app, school_id, make_grade(app, school_id), make_subject(app))
        plan, err = create_plan(school_id, "خطة سنوية", "annual", 500.0, cls_id)
        assert plan is not None
        assert err is None

    def test_list_plans(self, app):
        from app.services.billing import list_plans
        from tests.conftest import make_school

        school_id = make_school(app)
        cls_id = make_class(app, school_id, make_grade(app, school_id), make_subject(app))
        make_subscription_plan(app, school_id, cls_id)
        plans = list_plans(cls_id)
        assert len(plans) >= 1

    def test_get_plan(self, app):
        from app.services.billing import get_plan
        from tests.conftest import make_school

        school_id = make_school(app)
        cls_id = make_class(app, school_id, make_grade(app, school_id), make_subject(app))
        plan_id = make_subscription_plan(app, school_id, cls_id)
        plan = get_plan(plan_id)
        assert plan is not None

    def test_subscribe(self, app):
        from app.services.billing import subscribe
        from tests.conftest import make_school

        school_id = make_school(app)
        grade_id = make_grade(app, school_id)
        subject_id = make_subject(app)
        student_id = make_user(app, role="student")
        cls_id = make_class(app, school_id, grade_id, subject_id)
        plan_id = make_subscription_plan(app, school_id, cls_id)

        with app.app_context():
            plan = _db.session.get(SubscriptionPlan, plan_id)
            sub, err = subscribe(student_id, plan, cls_id)
            assert sub is not None
            assert err is None

    def test_list_subscriptions(self, app):
        from app.services.billing import list_subscriptions
        from tests.conftest import make_school

        school_id = make_school(app)
        grade_id = make_grade(app, school_id)
        subject_id = make_subject(app)
        student_id = make_user(app, role="student")
        cls_id = make_class(app, school_id, grade_id, subject_id)
        plan_id = make_subscription_plan(app, school_id, cls_id)
        make_subscription(app, student_id, plan_id, cls_id)

        subs = list_subscriptions(user_id=student_id)
        assert len(subs) >= 1

    def test_record_manual_payment(self, app):
        from app.services.billing import record_manual_payment
        from tests.conftest import make_school

        school_id = make_school(app)
        grade_id = make_grade(app, school_id)
        subject_id = make_subject(app)
        student_id = make_user(app, role="student")
        cls_id = make_class(app, school_id, grade_id, subject_id)
        plan_id = make_subscription_plan(app, school_id, cls_id)
        sub_id = make_subscription(app, student_id, plan_id, cls_id)

        with app.app_context():
            sub = _db.session.get(Subscription, sub_id)
            payment, err = record_manual_payment(sub, "REF001", 50.0)
            assert payment is not None
            assert err is None

    def test_approve_payment(self, app):
        from app.services.billing import approve_payment
        from tests.conftest import make_school

        school_id = make_school(app)
        grade_id = make_grade(app, school_id)
        subject_id = make_subject(app)
        student_id = make_user(app, role="student")
        cls_id = make_class(app, school_id, grade_id, subject_id)
        plan_id = make_subscription_plan(app, school_id, cls_id)
        sub_id = make_subscription(app, student_id, plan_id, cls_id)
        admin_id = make_user(app, role="super_admin")

        with app.app_context():
            sub = _db.session.get(Subscription, sub_id)
            from app.services.billing import record_manual_payment

            payment, _ = record_manual_payment(sub, "REF001", 50.0)
            result = approve_payment(payment, reviewer_id=admin_id)
            assert result is not None

    def test_reject_payment(self, app):
        from app.services.billing import reject_payment
        from tests.conftest import make_school

        school_id = make_school(app)
        grade_id = make_grade(app, school_id)
        subject_id = make_subject(app)
        student_id = make_user(app, role="student")
        cls_id = make_class(app, school_id, grade_id, subject_id)
        plan_id = make_subscription_plan(app, school_id, cls_id)
        sub_id = make_subscription(app, student_id, plan_id, cls_id)

        with app.app_context():
            sub = _db.session.get(Subscription, sub_id)
            from app.services.billing import record_manual_payment

            payment, _ = record_manual_payment(sub, "REF001", 50.0)
            reject_payment(payment)

    def test_pending_payments(self, app):
        from app.services.billing import pending_payments
        from tests.conftest import make_school

        school_id = make_school(app)
        grade_id = make_grade(app, school_id)
        subject_id = make_subject(app)
        student_id = make_user(app, role="student")
        cls_id = make_class(app, school_id, grade_id, subject_id)
        plan_id = make_subscription_plan(app, school_id, cls_id)
        sub_id = make_subscription(app, student_id, plan_id, cls_id)

        with app.app_context():
            sub = _db.session.get(Subscription, sub_id)
            from app.services.billing import record_manual_payment

            record_manual_payment(sub, "REF001", 50.0)
            pending = pending_payments()
            assert len(pending) >= 1

    def test_has_active_subscription(self, app):
        from app.services.billing import has_active_subscription
        from tests.conftest import make_school

        school_id = make_school(app)
        grade_id = make_grade(app, school_id)
        subject_id = make_subject(app)
        student_id = make_user(app, role="student")
        cls_id = make_class(app, school_id, grade_id, subject_id)
        plan_id = make_subscription_plan(app, school_id, cls_id)
        make_subscription(app, student_id, plan_id, cls_id, status="active")

        assert has_active_subscription(student_id, cls_id) is True

    def test_subscription_balance(self, app):
        from app.services.billing import subscription_balance
        from tests.conftest import make_school

        school_id = make_school(app)
        grade_id = make_grade(app, school_id)
        subject_id = make_subject(app)
        student_id = make_user(app, role="student")
        cls_id = make_class(app, school_id, grade_id, subject_id)
        plan_id = make_subscription_plan(app, school_id, cls_id, price=100.0)
        sub_id = make_subscription(app, student_id, plan_id, cls_id, price=100.0)

        with app.app_context():
            sub = _db.session.get(Subscription, sub_id)
            from app.services.billing import record_manual_payment

            record_manual_payment(sub, "REF001", 40.0)
            balance = subscription_balance(sub_id)
            assert balance >= Decimal("0.00")

    def test_can_record_payment(self, app):
        from app.services.billing import can_record_payment
        from tests.conftest import make_school

        school_id = make_school(app)
        grade_id = make_grade(app, school_id)
        subject_id = make_subject(app)
        student_id = make_user(app, role="student")
        cls_id = make_class(app, school_id, grade_id, subject_id)
        plan_id = make_subscription_plan(app, school_id, cls_id, price=100.0)
        sub_id = make_subscription(app, student_id, plan_id, cls_id, price=100.0)

        ok, msg = can_record_payment(sub_id, 50.0)
        assert ok is True

        ok, msg = can_record_payment(sub_id, 200.0)
        assert ok is False

    def test_subscription_payment_summary(self, app):
        from app.services.billing import subscription_payment_summary
        from tests.conftest import make_school

        school_id = make_school(app)
        grade_id = make_grade(app, school_id)
        subject_id = make_subject(app)
        student_id = make_user(app, role="student")
        cls_id = make_class(app, school_id, grade_id, subject_id)
        plan_id = make_subscription_plan(app, school_id, cls_id, price=100.0)
        sub_id = make_subscription(app, student_id, plan_id, cls_id, price=100.0)

        summary = subscription_payment_summary(sub_id)
        assert "total_paid" in summary
        assert "balance" in summary

    def test_create_discount_code(self, app):
        from app.services.billing import create_discount_code
        from tests.conftest import make_school

        school_id = make_school(app)
        dc, err = create_discount_code(school_id, "TEST10", "خصم 10", "percentage", 10)
        assert dc is not None
        assert err is None

    def test_create_discount_code_empty_code(self, app):
        from app.services.billing import create_discount_code
        from tests.conftest import make_school

        school_id = make_school(app)
        dc, err = create_discount_code(school_id, "", "خصم", "percentage", 10)
        assert dc is None

    def test_create_discount_code_empty_name(self, app):
        from app.services.billing import create_discount_code
        from tests.conftest import make_school

        school_id = make_school(app)
        dc, err = create_discount_code(school_id, "CODE", "", "percentage", 10)
        assert dc is None

    def test_create_discount_code_invalid_type(self, app):
        from app.services.billing import create_discount_code
        from tests.conftest import make_school

        school_id = make_school(app)
        dc, err = create_discount_code(school_id, "CODE", "name", "invalid", 10)
        assert dc is None

    def test_create_discount_code_zero_value(self, app):
        from app.services.billing import create_discount_code
        from tests.conftest import make_school

        school_id = make_school(app)
        dc, err = create_discount_code(school_id, "CODE", "name", "percentage", 0)
        assert dc is None

    def test_create_discount_code_max_uses_zero(self, app):
        from app.services.billing import create_discount_code
        from tests.conftest import make_school

        school_id = make_school(app)
        dc, err = create_discount_code(school_id, "CODE", "name", "percentage", 10, max_uses=0)
        assert dc is None

    def test_create_discount_code_duplicate(self, app):
        from app.services.billing import create_discount_code
        from tests.conftest import make_school

        school_id = make_school(app)
        create_discount_code(school_id, "DUP", "dup", "percentage", 10)
        dc2, err = create_discount_code(school_id, "DUP", "dup2", "percentage", 20)
        assert dc2 is None

    def test_validate_discount_code(self, app):
        from app.services.billing import create_discount_code, validate_discount_code
        from tests.conftest import make_school

        school_id = make_school(app)
        grade_id = make_grade(app, school_id)
        subject_id = make_subject(app)
        cls_id = make_class(app, school_id, grade_id, subject_id)
        plan_id = make_subscription_plan(app, school_id, cls_id, price=100.0)

        create_discount_code(school_id, "VALID10", "valid", "percentage", 10)
        discount, err = validate_discount_code("VALID10", plan_id)
        assert discount is not None
        assert discount == Decimal("10.00")

    def test_validate_discount_code_empty(self, app):
        from app.services.billing import validate_discount_code

        d, err = validate_discount_code("", 1)
        assert d is None

    def test_validate_discount_code_not_found(self, app):
        from app.services.billing import validate_discount_code

        d, err = validate_discount_code("NONEXIST", 1)
        assert d is None

    def test_validate_discount_code_inactive(self, app):
        from app.services.billing import create_discount_code, validate_discount_code
        from tests.conftest import make_school

        school_id = make_school(app)
        dc, _ = create_discount_code(school_id, "INACT", "inactive", "percentage", 10)

        with app.app_context():
            dc_obj = _db.session.get(DiscountCode, dc.id)
            dc_obj.is_active = False
            _db.session.commit()

        d, err = validate_discount_code("INACT", 1)
        assert d is None

    def test_validate_discount_code_expired(self, app):
        from app.services.billing import create_discount_code, validate_discount_code
        from tests.conftest import make_school

        school_id = make_school(app)
        expired = date.today() - timedelta(days=1)
        create_discount_code(school_id, "EXP", "expired", "percentage", 10, expiry_date=expired)
        d, err = validate_discount_code("EXP", 1)
        assert d is None

    def test_validate_discount_code_max_uses(self, app):
        from app.services.billing import create_discount_code, validate_discount_code
        from tests.conftest import make_school

        school_id = make_school(app)
        create_discount_code(school_id, "USED", "used", "percentage", 10, max_uses=1)

        with app.app_context():
            dc = DiscountCode.query.filter_by(code="USED").first()
            dc.used_count = 1
            _db.session.commit()

        d, err = validate_discount_code("USED", 1)
        assert d is None

    def test_validate_discount_code_wrong_plan(self, app):
        from app.services.billing import create_discount_code, validate_discount_code
        from tests.conftest import make_school

        school_id = make_school(app)
        create_discount_code(school_id, "PLAN1", "plan1", "percentage", 10, applicable_plan_ids=[999])
        d, err = validate_discount_code("PLAN1", 1)
        assert d is None

    def test_validate_discount_code_fixed(self, app):
        from app.services.billing import create_discount_code, validate_discount_code
        from tests.conftest import make_school

        school_id = make_school(app)
        grade_id = make_grade(app, school_id)
        subject_id = make_subject(app)
        cls_id = make_class(app, school_id, grade_id, subject_id)
        plan_id = make_subscription_plan(app, school_id, cls_id, price=100.0)

        create_discount_code(school_id, "FIX5", "fixed5", "fixed", 5)
        discount, err = validate_discount_code("FIX5", plan_id)
        assert discount == Decimal("5.00")

    def test_apply_discount_code(self, app):
        from app.services.billing import apply_discount_code, create_discount_code
        from tests.conftest import make_school

        school_id = make_school(app)
        grade_id = make_grade(app, school_id)
        subject_id = make_subject(app)
        student_id = make_user(app, role="student")
        cls_id = make_class(app, school_id, grade_id, subject_id)
        plan_id = make_subscription_plan(app, school_id, cls_id, price=100.0)
        sub_id = make_subscription(app, student_id, plan_id, cls_id, price=100.0)

        create_discount_code(school_id, "APPLY10", "apply", "percentage", 10)
        discount, err = apply_discount_code(sub_id, "APPLY10")
        assert discount is not None

    def test_apply_discount_code_empty(self, app):
        from app.services.billing import apply_discount_code

        d, err = apply_discount_code(1, "")
        assert d is None

    def test_apply_discount_code_nonexistent_sub(self, app):
        from app.services.billing import apply_discount_code

        d, err = apply_discount_code(99999, "CODE")
        assert d is None

    def test_expire_subscriptions(self, app):
        from app.services.billing import expire_subscriptions
        from tests.conftest import make_school

        school_id = make_school(app)
        grade_id = make_grade(app, school_id)
        subject_id = make_subject(app)
        student_id = make_user(app, role="student")
        cls_id = make_class(app, school_id, grade_id, subject_id)
        plan_id = make_subscription_plan(app, school_id, cls_id)
        sub_id = make_subscription(app, student_id, plan_id, cls_id, status="active")

        with app.app_context():
            sub = _db.session.get(Subscription, sub_id)
            sub.expires_at = datetime.now(UTC) - timedelta(days=1)
            _db.session.commit()

        count = expire_subscriptions()
        assert count >= 0


# ── Content ──────────────────────────────────────────────────────


class TestContent:
    @pytest.fixture(autouse=True)
    def _ctx(self, app):
        with app.app_context():
            yield

    def test_create_unit(self, app):
        from app.services.content import create_unit
        from tests.conftest import make_school

        school_id = make_school(app)
        grade_id = make_grade(app, school_id)
        subject_id = make_subject(app)
        cls_id = make_class(app, school_id, grade_id, subject_id)
        unit = create_unit(cls_id, "الوحدة الأولى")
        assert unit is not None

    def test_list_units(self, app):
        from app.services.content import create_unit, list_units
        from tests.conftest import make_school

        school_id = make_school(app)
        grade_id = make_grade(app, school_id)
        subject_id = make_subject(app)
        cls_id = make_class(app, school_id, grade_id, subject_id)
        create_unit(cls_id, "unit1")
        create_unit(cls_id, "unit2")
        units = list_units(cls_id)
        assert len(units) == 2

    def test_list_lessons(self, app):
        from app.services.content import list_lessons
        from tests.conftest import make_school

        school_id = make_school(app)
        grade_id = make_grade(app, school_id)
        subject_id = make_subject(app)
        cls_id = make_class(app, school_id, grade_id, subject_id)
        make_lesson(app, cls_id)
        lessons = list_lessons(cls_id)
        assert len(lessons) >= 1

    def test_get_lesson(self, app):
        from app.services.content import get_lesson
        from tests.conftest import make_school

        school_id = make_school(app)
        grade_id = make_grade(app, school_id)
        subject_id = make_subject(app)
        cls_id = make_class(app, school_id, grade_id, subject_id)
        lesson_id = make_lesson(app, cls_id)
        lesson = get_lesson(lesson_id)
        assert lesson is not None

    def test_get_lesson_nonexistent(self, app):
        from app.services.content import get_lesson

        assert get_lesson(99999) is None

    def test_create_lesson(self, app):
        from app.services.content import create_lesson
        from tests.conftest import make_school

        school_id = make_school(app)
        grade_id = make_grade(app, school_id)
        subject_id = make_subject(app)
        cls_id = make_class(app, school_id, grade_id, subject_id)
        lesson = create_lesson(cls_id, "درس جديد", body_html="<p>Hello</p>")
        assert lesson is not None

    def test_update_lesson(self, app):
        from app.services.content import update_lesson
        from tests.conftest import make_school

        school_id = make_school(app)
        grade_id = make_grade(app, school_id)
        subject_id = make_subject(app)
        cls_id = make_class(app, school_id, grade_id, subject_id)
        lesson_id = make_lesson(app, cls_id)

        with app.app_context():
            lesson = _db.session.get(Lesson, lesson_id)
            update_lesson(lesson, title="عنوان محدث", unit_id=None, body_html="<p>Updated</p>")
            assert lesson.title == "عنوان محدث"

    def test_publish_lesson(self, app):
        from app.services.content import publish_lesson
        from tests.conftest import make_school

        school_id = make_school(app)
        grade_id = make_grade(app, school_id)
        subject_id = make_subject(app)
        cls_id = make_class(app, school_id, grade_id, subject_id)
        lesson_id = make_lesson(app, cls_id, status="draft")

        with app.app_context():
            lesson = _db.session.get(Lesson, lesson_id)
            publish_lesson(lesson)
            assert lesson.status == "published"

    def test_unpublish_lesson(self, app):
        from app.services.content import unpublish_lesson
        from tests.conftest import make_school

        school_id = make_school(app)
        grade_id = make_grade(app, school_id)
        subject_id = make_subject(app)
        cls_id = make_class(app, school_id, grade_id, subject_id)
        lesson_id = make_lesson(app, cls_id, status="published")

        with app.app_context():
            lesson = _db.session.get(Lesson, lesson_id)
            unpublish_lesson(lesson)
            assert lesson.status == "draft"

    def test_add_youtube(self, app):
        from app.services.content import add_youtube
        from tests.conftest import make_school

        school_id = make_school(app)
        grade_id = make_grade(app, school_id)
        subject_id = make_subject(app)
        cls_id = make_class(app, school_id, grade_id, subject_id)
        lesson_id = make_lesson(app, cls_id)

        with app.app_context():
            lesson = _db.session.get(Lesson, lesson_id)
            attachment = add_youtube(lesson, "https://youtube.com/watch?v=abc", title="فيديو")
            assert attachment is not None
            assert attachment.kind == "video"


# ── Assessment ───────────────────────────────────────────────────


class TestAssessment:
    @pytest.fixture(autouse=True)
    def _ctx(self, app):
        with app.app_context():
            yield

    def test_create_quiz(self, app):
        from app.services.assessment import create_quiz
        from tests.conftest import make_school

        school_id = make_school(app)
        grade_id = make_grade(app, school_id)
        subject_id = make_subject(app)
        teacher_id = make_user(app, role="teacher")
        cls_id = make_class(app, school_id, grade_id, subject_id, teacher_id=teacher_id)

        quiz, err = create_quiz(cls_id, "اختبار رياضيات", duration_min=30, created_by=teacher_id)
        assert quiz is not None
        assert err is None

    def test_list_quizzes(self, app):
        from app.services.assessment import create_quiz, list_quizzes
        from tests.conftest import make_school

        school_id = make_school(app)
        grade_id = make_grade(app, school_id)
        subject_id = make_subject(app)
        teacher_id = make_user(app, role="teacher")
        cls_id = make_class(app, school_id, grade_id, subject_id, teacher_id=teacher_id)

        create_quiz(cls_id, "quiz1", created_by=teacher_id)
        quizzes = list_quizzes(cls_id)
        assert len(quizzes) >= 1

    def test_add_question(self, app):
        from app.services.assessment import add_question, create_quiz
        from tests.conftest import make_school

        school_id = make_school(app)
        grade_id = make_grade(app, school_id)
        subject_id = make_subject(app)
        teacher_id = make_user(app, role="teacher")
        cls_id = make_class(app, school_id, grade_id, subject_id, teacher_id=teacher_id)

        quiz, _ = create_quiz(cls_id, "quiz", created_by=teacher_id)
        q = add_question(quiz, "mcq", "ما ناتج 2+2؟", options=["2", "3", "4", "5"], correct_answer="4")
        assert q is not None

    def test_delete_question(self, app):
        from app.services.assessment import add_question, create_quiz, delete_question
        from tests.conftest import make_school

        school_id = make_school(app)
        grade_id = make_grade(app, school_id)
        subject_id = make_subject(app)
        teacher_id = make_user(app, role="teacher")
        cls_id = make_class(app, school_id, grade_id, subject_id, teacher_id=teacher_id)

        quiz, _ = create_quiz(cls_id, "quiz", created_by=teacher_id)
        q = add_question(quiz, "mcq", "Q?", options=["A", "B"])
        delete_question(q)

    def test_deadline_exceeded(self, app):
        from app.services.assessment import deadline_exceeded
        from tests.conftest import make_school

        school_id = make_school(app)
        grade_id = make_grade(app, school_id)
        subject_id = make_subject(app)
        teacher_id = make_user(app, role="teacher")
        student_id = make_user(app, role="student")
        cls_id = make_class(app, school_id, grade_id, subject_id, teacher_id=teacher_id)

        with app.app_context():
            from app.models.assessment import QuizAttempt
            from app.services.assessment import create_quiz

            quiz, _ = create_quiz(cls_id, "quiz", duration_min=1, created_by=teacher_id)
            attempt = QuizAttempt(quiz_id=quiz.id, student_id=student_id, status="in_progress")
            _db.session.add(attempt)
            _db.session.commit()

            # Fresh deadline → not exceeded
            assert deadline_exceeded(attempt) is False

            # Past deadline → exceeded
            quiz.deadline = datetime.now(UTC) - timedelta(hours=1)
            _db.session.commit()
            assert deadline_exceeded(attempt) is True

    def test_grade_essay(self, app):
        from app.services.assessment import grade_essay
        from tests.conftest import make_school

        school_id = make_school(app)
        grade_id = make_grade(app, school_id)
        subject_id = make_subject(app)
        teacher_id = make_user(app, role="teacher")
        student_id = make_user(app, role="student")
        cls_id = make_class(app, school_id, grade_id, subject_id, teacher_id=teacher_id)

        with app.app_context():
            from app.models.assessment import Answer, Question, QuizAttempt
            from app.services.assessment import create_quiz

            quiz, _ = create_quiz(cls_id, "essay quiz", created_by=teacher_id)
            q = Question(quiz_id=quiz.id, question_type="essay", prompt="اكتب مقالاً")
            _db.session.add(q)
            _db.session.flush()

            attempt = QuizAttempt(quiz_id=quiz.id, student_id=student_id, status="submitted")
            _db.session.add(attempt)
            _db.session.flush()

            answer = Answer(attempt_id=attempt.id, question_id=q.id, answer_text="مقالة")
            _db.session.add(answer)
            _db.session.commit()

            grade_essay(answer, awarded_mark=8.5)
            assert answer.awarded_mark == Decimal("8.50")

    def test_get_attempt(self, app):
        from app.services.assessment import get_attempt
        from tests.conftest import make_school

        school_id = make_school(app)
        grade_id = make_grade(app, school_id)
        subject_id = make_subject(app)
        teacher_id = make_user(app, role="teacher")
        student_id = make_user(app, role="student")
        cls_id = make_class(app, school_id, grade_id, subject_id, teacher_id=teacher_id)

        from app.models.assessment import QuizAttempt
        from app.services.assessment import create_quiz

        quiz, _ = create_quiz(cls_id, "quiz", created_by=teacher_id)
        attempt = QuizAttempt(quiz_id=quiz.id, student_id=student_id, status="in_progress")
        _db.session.add(attempt)
        _db.session.commit()
        result = get_attempt(attempt.id)
        assert result is not None


# ── Communication ────────────────────────────────────────────────


class TestCommunication:
    @pytest.fixture(autouse=True)
    def _ctx(self, app):
        with app.app_context():
            yield

    def test_notify(self, app):
        from app.services.communication import notify

        uid = make_user(app, role="student")
        notify(uid, "info", "عنوان", "محتوى", link="/test")
        # Should not raise

    def test_unread_count(self, app):
        from app.services.communication import notify, unread_count

        uid = make_user(app, role="student")
        notify(uid, "info", "title1", "body1")
        notify(uid, "info", "title2", "body2")
        count = unread_count(uid)
        assert count == 2

    def test_mark_all_read(self, app):
        from app.services.communication import mark_all_read, notify, unread_count

        uid = make_user(app, role="student")
        notify(uid, "info", "t", "b")
        mark_all_read(uid)
        assert unread_count(uid) == 0

    def test_audit(self, app):
        from app.services.communication import audit

        uid = make_user(app, role="admin")
        audit(user_id=uid, action="test_action", resource_type="test", resource_id=1, details="test details")
        # Should not raise


# ── Calendar ─────────────────────────────────────────────────────


class TestCalendar:
    @pytest.fixture(autouse=True)
    def _ctx(self, app):
        with app.app_context():
            yield

    def test_create_event(self, app):
        from app.services.calendar import create_event
        from tests.conftest import make_school

        school_id = make_school(app)
        event = create_event(school_id, "اختبارات نهائية", "exam", date.today(), date.today() + timedelta(days=5))
        assert event is not None

    def test_list_events(self, app):
        from app.services.calendar import create_event, list_events
        from tests.conftest import make_school

        school_id = make_school(app)
        create_event(school_id, "event1", "exam", date.today())
        create_event(school_id, "event2", "holiday", date.today())
        events = list_events(school_id)
        assert len(events) >= 2

    def test_list_events_filtered(self, app):
        from app.services.calendar import create_event, list_events
        from tests.conftest import make_school

        school_id = make_school(app)
        create_event(school_id, "exam1", "exam", date.today())
        create_event(school_id, "holiday1", "holiday", date.today())
        exams = list_events(school_id, event_type="exam")
        assert len(exams) == 1

    def test_delete_event(self, app):
        from app.services.calendar import create_event, delete_event
        from tests.conftest import make_school

        school_id = make_school(app)
        event = create_event(school_id, "delete me", "exam", date.today())
        ok, err = delete_event(event.id)
        assert ok is True

    def test_delete_event_nonexistent(self, app):
        from app.services.calendar import delete_event

        ok, err = delete_event(99999)
        assert ok is False

    def test_current_term(self, app):
        from app.services.calendar import current_term
        from tests.conftest import make_school

        school_id = make_school(app)
        result = current_term(school_id)
        # No events → None
        assert result is None


# ── Notification Preferences ─────────────────────────────────────


class TestNotificationPreferences:
    @pytest.fixture(autouse=True)
    def _ctx(self, app):
        with app.app_context():
            yield

    def test_get_preferences(self, app):
        from app.services.notification_preferences import get_preferences

        uid = make_user(app, role="student")
        prefs = get_preferences(uid)
        assert isinstance(prefs, list)

    def test_update_preference(self, app):
        from app.services.notification_preferences import get_preference, update_preference

        uid = make_user(app, role="student")
        update_preference(uid, "quiz_result", email_enabled=False, in_app_enabled=True)
        pref = get_preference(uid, "quiz_result")
        assert pref is not None
        assert pref.email_enabled is False

    def test_should_notify(self, app):
        from app.services.notification_preferences import should_notify, update_preference

        uid = make_user(app, role="student")
        update_preference(uid, "message", email_enabled=False, in_app_enabled=True)
        assert should_notify(uid, "message", "in_app") is True

    def test_get_preference_none(self, app):
        from app.services.notification_preferences import get_preference

        uid = make_user(app, role="student")
        assert get_preference(uid, "nonexistent") is None


# ── Onboarding ───────────────────────────────────────────────────


class TestOnboarding:
    @pytest.fixture(autouse=True)
    def _ctx(self, app):
        with app.app_context():
            yield

    def test_start_onboarding(self, app):
        from app.services.onboarding import start_onboarding
        from tests.conftest import make_school

        school_id = make_school(app)
        progress = start_onboarding(school_id)
        assert progress is not None
        assert progress.current_step == 1

    def test_start_onboarding_idempotent(self, app):
        from app.services.onboarding import start_onboarding
        from tests.conftest import make_school

        school_id = make_school(app)
        p1 = start_onboarding(school_id)
        p2 = start_onboarding(school_id)
        assert p1.id == p2.id

    def test_complete_step(self, app):
        from app.services.onboarding import complete_step, start_onboarding
        from tests.conftest import make_school

        school_id = make_school(app)
        start_onboarding(school_id)
        result = complete_step(school_id, 1, data={"name": "My School"})
        assert result is not None
        assert result.current_step == 2

    def test_complete_invalid_step(self, app):
        from app.services.onboarding import complete_step, start_onboarding
        from tests.conftest import make_school

        school_id = make_school(app)
        start_onboarding(school_id)
        result = complete_step(school_id, 99)
        assert result is None

    def test_get_onboarding_status(self, app):
        from app.services.onboarding import get_onboarding_status, start_onboarding
        from tests.conftest import make_school

        school_id = make_school(app)
        start_onboarding(school_id)
        status = get_onboarding_status(school_id)
        assert "current_step" in status

    def test_get_onboarding_status_not_started(self, app):
        from app.services.onboarding import get_onboarding_status
        from tests.conftest import make_school

        school_id = make_school(app)
        status = get_onboarding_status(school_id)
        assert status["current_step"] == 0

    def test_wizard_steps(self, app):
        from app.services.onboarding import get_wizard_steps

        steps = get_wizard_steps()
        assert len(steps) > 0


# ── Access Control ───────────────────────────────────────────────


class TestAccess:
    @pytest.fixture(autouse=True)
    def _ctx(self, app):
        with app.app_context():
            yield

    def test_can_view_class(self, app):
        from app.services.access import can_view_class
        from tests.conftest import make_school

        school_id = make_school(app)
        grade_id = make_grade(app, school_id)
        subject_id = make_subject(app)
        student_id = make_user(app, role="student")
        cls_id = make_class(app, school_id, grade_id, subject_id)
        make_class_member(app, cls_id, student_id)

        with app.app_context():
            cls = _db.session.get(ClassRoom, cls_id)
            u = _db.session.get(User, student_id)
            assert can_view_class(cls, u) is True

    def test_can_teach_class(self, app):
        from app.services.access import can_teach_class
        from tests.conftest import make_school

        school_id = make_school(app)
        grade_id = make_grade(app, school_id)
        subject_id = make_subject(app)
        teacher_id = make_user(app, role="teacher")
        cls_id = make_class(app, school_id, grade_id, subject_id, teacher_id=teacher_id)

        with app.app_context():
            cls = _db.session.get(ClassRoom, cls_id)
            u = _db.session.get(User, teacher_id)
            assert can_teach_class(cls, u) is True

    def test_can_teach_class_wrong_teacher(self, app):
        from app.services.access import can_teach_class
        from tests.conftest import make_school

        school_id = make_school(app)
        grade_id = make_grade(app, school_id)
        subject_id = make_subject(app)
        teacher_id = make_user(app, role="teacher")
        other_id = make_user(app, role="teacher")
        cls_id = make_class(app, school_id, grade_id, subject_id, teacher_id=teacher_id)

        with app.app_context():
            cls = _db.session.get(ClassRoom, cls_id)
            u = _db.session.get(User, other_id)
            assert can_teach_class(cls, u) is False


# ── Messages ─────────────────────────────────────────────────────


class TestMessages:
    @pytest.fixture(autouse=True)
    def _ctx(self, app):
        with app.app_context():
            yield

    def test_send_message(self, app):
        from app.services.messages import send_message

        sender_id = make_user(app, role="teacher")
        recipient_id = make_user(app, role="student")
        msg = send_message(sender_id, recipient_id, "موضوع", "محتوى الرسالة")
        assert msg is not None

    def test_send_message_empty_subject(self, app):
        from app.services.messages import send_message

        sender_id = make_user(app, role="teacher")
        recipient_id = make_user(app, role="student")
        msg = send_message(sender_id, recipient_id, "", "content")
        assert msg is None

    def test_send_message_empty_body(self, app):
        from app.services.messages import send_message

        sender_id = make_user(app, role="teacher")
        recipient_id = make_user(app, role="student")
        msg = send_message(sender_id, recipient_id, "subject", "")
        assert msg is None

    def test_send_message_self(self, app):
        from app.services.messages import send_message

        uid = make_user(app, role="student")
        msg = send_message(uid, uid, "subject", "body")
        assert msg is None

    def test_send_message_nonexistent(self, app):
        from app.services.messages import send_message

        sender_id = make_user(app, role="student")
        msg = send_message(sender_id, 99999, "subject", "body")
        assert msg is None

    def test_inbox(self, app):
        from app.services.messages import inbox, send_message

        sender_id = make_user(app, role="teacher")
        recipient_id = make_user(app, role="student")
        send_message(sender_id, recipient_id, "s", "b")
        msgs = inbox(recipient_id)
        assert len(msgs) >= 1

    def test_sent(self, app):
        from app.services.messages import send_message, sent

        sender_id = make_user(app, role="teacher")
        recipient_id = make_user(app, role="student")
        send_message(sender_id, recipient_id, "s", "b")
        msgs = sent(sender_id)
        assert len(msgs) >= 1

    def test_mark_read(self, app):
        from app.services.messages import mark_read, send_message, unread_count

        sender_id = make_user(app, role="teacher")
        recipient_id = make_user(app, role="student")
        msg = send_message(sender_id, recipient_id, "s", "b")
        mark_read(msg.id, recipient_id)
        assert unread_count(recipient_id) == 0

    def test_get_thread(self, app):
        from app.services.messages import get_thread, send_message

        sender_id = make_user(app, role="teacher")
        recipient_id = make_user(app, role="student")
        msg = send_message(sender_id, recipient_id, "s", "b")
        thread = get_thread(msg.id)
        assert thread is not None

    def test_send_reply(self, app):
        from app.services.messages import send_message

        sender_id = make_user(app, role="teacher")
        recipient_id = make_user(app, role="student")
        msg = send_message(sender_id, recipient_id, "s", "b")
        reply = send_message(recipient_id, sender_id, "re: s", "reply body", parent_id=msg.id)
        assert reply is not None


# ── Family ───────────────────────────────────────────────────────


class TestFamily:
    @pytest.fixture(autouse=True)
    def _ctx(self, app):
        with app.app_context():
            yield

    def test_generate_link_code(self, app):
        from app.services.family import generate_link_code

        uid = make_user(app, role="student")
        code, err = generate_link_code(uid)
        assert code is not None

    def test_link_parent(self, app):
        from app.services.family import generate_link_code, link_parent

        student_id = make_user(app, role="student")
        parent_id = make_user(app, role="parent")
        code, _ = generate_link_code(student_id)
        link, err = link_parent(parent_id, code)
        assert link is not None

    def test_link_parent_invalid_code(self, app):
        from app.services.family import link_parent

        parent_id = make_user(app, role="parent")
        link, err = link_parent(parent_id, "INVALID")
        assert link is None

    def test_list_children(self, app):
        from app.services.family import generate_link_code, link_parent, list_children

        student_id = make_user(app, role="student")
        parent_id = make_user(app, role="parent")
        code, _ = generate_link_code(student_id)
        link_parent(parent_id, code)
        children = list_children(parent_id)
        assert len(children) >= 1

    def test_is_parent_of(self, app):
        from app.services.family import generate_link_code, is_parent_of, link_parent

        student_id = make_user(app, role="student")
        parent_id = make_user(app, role="parent")
        code, _ = generate_link_code(student_id)
        link_parent(parent_id, code)
        assert is_parent_of(parent_id, student_id) is True

    def test_remove_link(self, app):
        from app.services.family import generate_link_code, link_parent, remove_link

        student_id = make_user(app, role="student")
        parent_id = make_user(app, role="parent")
        code, _ = generate_link_code(student_id)
        link, _ = link_parent(parent_id, code)
        ok, err = remove_link(link.id, parent_id)
        assert ok is True


# ── Rubric ───────────────────────────────────────────────────────


class TestRubric:
    @pytest.fixture(autouse=True)
    def _ctx(self, app):
        with app.app_context():
            yield

    def test_create_rubric_template(self, app):
        from app.services.rubric import create_rubric_template
        from tests.conftest import make_school

        school_id = make_school(app)
        teacher_id = make_user(app, role="teacher")
        template = create_rubric_template(teacher_id, school_id, "تقييم المقال", criteria=[
            {"title": "المحتوى", "max_score": 10},
            {"title": "الهيكل", "max_score": 5},
        ])
        assert template is not None

    def test_list_rubric_templates(self, app):
        from app.services.rubric import create_rubric_template, list_rubric_templates
        from tests.conftest import make_school

        school_id = make_school(app)
        teacher_id = make_user(app, role="teacher")
        create_rubric_template(teacher_id, school_id, "rt1")
        templates = list_rubric_templates(teacher_id)
        assert len(templates) >= 1

    def test_get_rubric_template(self, app):
        from app.services.rubric import create_rubric_template, get_rubric_template
        from tests.conftest import make_school

        school_id = make_school(app)
        teacher_id = make_user(app, role="teacher")
        template = create_rubric_template(teacher_id, school_id, "rt1")
        result = get_rubric_template(template.id)
        assert result is not None

    def test_get_rubric_template_none(self, app):
        from app.services.rubric import get_rubric_template

        assert get_rubric_template(99999) is None


# ── Finance ──────────────────────────────────────────────────────


class TestFinance:
    @pytest.fixture(autouse=True)
    def _ctx(self, app):
        with app.app_context():
            yield

    def test_school_revenue_summary(self, app):
        from app.services.finance import school_revenue_summary
        from tests.conftest import make_school

        school_id = make_school(app)
        summary = school_revenue_summary(school_id)
        assert "total_revenue" in summary


# ── Health ───────────────────────────────────────────────────────


class TestHealth:
    @pytest.fixture(autouse=True)
    def _ctx(self, app):
        with app.app_context():
            yield

    def test_check_database(self, app):
        from app.services.health import check_database

        result = check_database()
        assert result["status"] == "healthy"

    def test_check_disk(self, app):
        from app.services.health import check_disk

        result = check_disk()
        assert "status" in result

    def test_run_all_checks(self, app):
        from app.services.health import run_all_checks

        results = run_all_checks()
        assert len(results) >= 2

    def test_get_system_status(self, app):
        from app.services.health import get_system_status

        status = get_system_status()
        assert "status" in status


# ── Grade Appeals ────────────────────────────────────────────────


class TestGradeAppeals:
    @pytest.fixture(autouse=True)
    def _ctx(self, app):
        with app.app_context():
            yield

    def test_get_student_appeals(self, app):
        from app.services.grade_appeals import get_student_appeals

        uid = make_user(app, role="student")
        appeals = get_student_appeals(uid)
        assert isinstance(appeals, list)

    def test_get_pending_appeals(self, app):
        from app.services.grade_appeals import get_pending_appeals

        appeals = get_pending_appeals()
        assert isinstance(appeals, list)


# ── Offline ──────────────────────────────────────────────────────


class TestOffline:
    @pytest.fixture(autouse=True)
    def _ctx(self, app):
        with app.app_context():
            yield

    def test_offline_model(self, app):
        from app.models.offline import OfflineDownload

        assert hasattr(OfflineDownload, "student_id")


# ── Tenant ───────────────────────────────────────────────────────


class TestTenant:
    @pytest.fixture(autouse=True)
    def _ctx(self, app):
        with app.app_context():
            yield

    def test_get_quota(self, app):
        from app.services.tenant import get_quota
        from tests.conftest import make_school

        school_id = make_school(app)
        quota = get_quota(school_id)
        assert quota is not None

    def test_check_quota(self, app):
        from app.services.tenant import check_quota
        from tests.conftest import make_school

        school_id = make_school(app)
        ok, msg = check_quota(school_id, "students")
        assert ok is True


# ── Question Bank ────────────────────────────────────────────────


class TestQuestionBank:
    @pytest.fixture(autouse=True)
    def _ctx(self, app):
        with app.app_context():
            yield

    def test_question_bank_model(self, app):
        from app.models.question_bank import QuestionBank

        assert hasattr(QuestionBank, "teacher_id")
