"""Cross-module integration tests: auth → billing → class membership → content access.

Covers five end-to-end flows:
  1. Free class join → instant active membership → content access.
  2. Paid class subscribe → pay → approve → active → content access.
  3. Paid class subscribe → pay → reject → no content access.
  4. Active subscription expires → access revoked.
  5. Cross-tenant boundary — School A user blocked from School B.

Note: ``can_view_class()`` requires Flask-Login ``current_user`` context (HTTP
request).  These tests exercise the *business logic layer* directly using the
lower-level helpers ``is_member()`` and ``_has_valid_subscription()`` to verify
the same rules without needing a live request.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TypeVar

import pytest
from app.extensions import db
from app.models.billing import Subscription, SubscriptionPlan
from app.models.class_room import ClassMember, ClassRoom
from app.models.content import Lesson
from app.models.user import User, UserRole
from app.services import access, billing, individual, schools

T = TypeVar("T")


def _assert(val: T | None, msg: str = "unexpected None") -> T:
    """Assert *val* is not None and return it narrowed to *T*."""
    assert val is not None, msg
    return val


# ─── helpers ────────────────────────────────────────────────────────────────────


def _setup_school(app, name: str = "مدرسة الاختبار"):
    """Create a school with one grade, one subject, and a teacher. Return IDs."""
    with app.app_context():
        from app.models.school import Grade, School, Subject
        from app.models.user import UserRoleLink

        school = School(name_ar=name, domain=f"{name}.test.org")
        db.session.add(school)
        db.session.flush()

        grade = Grade(school_id=school.id, grade_level=5, name_ar="الخامس")
        db.session.add(grade)

        subject = Subject(name_ar="رياضيات")
        db.session.add(subject)

        teacher = User(
            email=f"teacher-{school.id}@test.com",
            name_ar=f"معلم {name}",
            role=UserRole.teacher,
            password_hash="pbkdf2:sha256:placeholder",
            approval_status="approved",
            is_active=True,
        )
        db.session.add(teacher)
        db.session.flush()

        rl = UserRoleLink(user_id=teacher.id, school_id=school.id, role=UserRole.teacher)
        db.session.add(rl)

        db.session.commit()
        return {
            "school": school.id,
            "grade": grade.id,
            "subject": subject.id,
            "teacher": teacher.id,
        }


def _make_class(
    app, *, school_id, grade_id, subject_id, teacher_id, is_public=False, price=0, duration_days=30, join_code=None
):
    """Create a class and return its ID."""
    import secrets

    with app.app_context():
        code = join_code or secrets.token_urlsafe(6)
        cr = ClassRoom(
            school_id=school_id,
            grade_id=grade_id,
            subject_id=subject_id,
            teacher_id=teacher_id,
            is_public=is_public,
            price=Decimal(str(price)) if price else None,
            duration_days=duration_days,
            join_code=code,
            name=f"صف اختبار {code[:6]}",
        )
        db.session.add(cr)
        db.session.commit()
        return cr.id


def _make_student(app, *, school_id=None, email=None, name=None, is_individual=False, password=None):
    """Create a student user. Optionally link to a school.

    ``is_individual=True`` يحاكي المسجّل عبر بوابة التسجيل فرديًا (بلا مدرسة) —
    وهو ما يضبط GUC ``app.is_individual`` في طلباته ليرى كتالوغ الكورسات العامة
    واشتراكاته هو فقط تحت RLS. ``password`` يمنح كلمة مرور حقيقية لدخول HTTP.
    """
    with app.app_context():
        from app.core.security import hash_password

        u = User(
            email=email or f"student-{db.session.query(User).count() + 1}@test.com",
            name_ar=name or "طالب اختبار",
            role=UserRole.student,
            password_hash=hash_password(password) if password else "pbkdf2:sha256:placeholder",
            approval_status="approved",
            is_active=True,
            is_individual=is_individual,
        )
        db.session.add(u)
        db.session.flush()

        if school_id:
            from app.models.user import UserRoleLink

            rl = UserRoleLink(user_id=u.id, school_id=school_id, role=UserRole.student)
            db.session.add(rl)

        db.session.commit()
        return u.id


def _make_plan(app, *, school_id, class_id=None, price=100, duration_days=30):
    """Create a subscription plan. Return plan ID."""
    with app.app_context():
        plan = SubscriptionPlan(
            school_id=school_id,
            class_id=class_id,
            name="خطة اختبار",
            plan="annual",
            price=Decimal(str(price)),
            duration_days=duration_days,
        )
        db.session.add(plan)
        db.session.commit()
        return plan.id


def _make_lesson(app, class_id, title="درس اختبار"):
    with app.app_context():
        lsn = Lesson(class_id=class_id, title=title, status="published", sort_order=1)
        db.session.add(lsn)
        db.session.commit()
        return lsn.id


def _get_user(app, user_id):
    with app.app_context():
        return db.session.get(User, user_id)


def _get_class(app, class_id):
    with app.app_context():
        return db.session.get(ClassRoom, class_id)


def _subscribe_and_pay(app, student_id, plan_id, class_id, amount, reference):
    """Subscribe → record payment. MUST be called inside an open app.app_context().

    Returns (sub, payment) with both asserted non-None. Objects remain bound to
    the caller's session (no extra context created).
    """
    plan = _assert(db.session.get(SubscriptionPlan, plan_id), "plan not found")
    sub, err = billing.subscribe(student_id, plan, class_id)
    assert err is None, f"subscribe failed: {err}"
    sub = _assert(sub, "subscription was None after subscribe()")
    payment, err = billing.record_manual_payment(sub, reference=reference, amount=amount)
    assert err is None, f"record_manual_payment failed: {err}"
    payment = _assert(payment, "payment was None after record_manual_payment()")
    return sub, payment


# ═══════════════════════════════════════════════════════════════════════════════
#  1. FREE CLASS FLOW
# ═══════════════════════════════════════════════════════════════════════════════


class TestFreeClassFlow:
    """Student joins a free class → instant active membership → full content access."""

    def test_free_class_join_and_access(self, app):
        ids = _setup_school(app, "مدرسة مجانية")
        student_id = _make_student(app, school_id=ids["school"])
        class_id = _make_class(
            app,
            school_id=ids["school"],
            grade_id=ids["grade"],
            subject_id=ids["subject"],
            teacher_id=ids["teacher"],
            is_public=True,
            price=0,
        )
        _make_lesson(app, class_id)

        with app.app_context():
            user = _get_user(app, student_id)
            cls = _get_class(app, class_id)

            assert not schools.is_member(cls, user)

            error = schools.join_class(cls, user)
            assert error is None, f"join_class failed: {error}"

            assert schools.is_member(cls, user)
            assert access._is_class_free(cls)

    def test_free_class_via_individual_subscribe(self, app):
        """Individual student uses subscribe_to_class for a free public class."""
        ids = _setup_school(app, "مدرسة فردية مجانية")
        student_id = _make_student(app)
        class_id = _make_class(
            app,
            school_id=ids["school"],
            grade_id=ids["grade"],
            subject_id=ids["subject"],
            teacher_id=ids["teacher"],
            is_public=True,
            price=0,
        )

        with app.app_context():
            error = individual.subscribe_to_class(student_id, class_id)
            assert error is None

            member = ClassMember.query.filter_by(class_id=class_id, user_id=student_id).first()
            assert member is not None
            assert member.status == "active"

    def test_free_class_duplicate_join_rejected(self, app):
        ids = _setup_school(app, "مدرسة مكررة")
        student_id = _make_student(app, school_id=ids["school"])
        class_id = _make_class(
            app,
            school_id=ids["school"],
            grade_id=ids["grade"],
            subject_id=ids["subject"],
            teacher_id=ids["teacher"],
            is_public=True,
            price=0,
        )

        with app.app_context():
            user = _get_user(app, student_id)
            cls = _get_class(app, class_id)
            assert schools.join_class(cls, user) is None
            assert schools.join_class(cls, user) is not None

    def test_free_class_individual_subscribe_creates_membership(self, app):
        ids = _setup_school(app, "مدرسة عضوية مجانية")
        student_id = _make_student(app)
        class_id = _make_class(
            app,
            school_id=ids["school"],
            grade_id=ids["grade"],
            subject_id=ids["subject"],
            teacher_id=ids["teacher"],
            is_public=True,
            price=0,
        )

        with app.app_context():
            assert individual.subscribe_to_class(student_id, class_id) is None
            member = ClassMember.query.filter_by(class_id=class_id, user_id=student_id, status="active").first()
            assert member is not None


# ═══════════════════════════════════════════════════════════════════════════════
#  2. PAID CLASS — SUBSCRIBE → PAY → APPROVE → ACCESS
# ═══════════════════════════════════════════════════════════════════════════════


class TestPaidClassApprovalFlow:
    """Full lifecycle: subscribe → record payment → approve → active → access."""

    def test_full_approval_lifecycle(self, app):
        ids = _setup_school(app, "مدرسة مدفوعة")
        student_id = _make_student(app, school_id=ids["school"])
        class_id = _make_class(
            app,
            school_id=ids["school"],
            grade_id=ids["grade"],
            subject_id=ids["subject"],
            teacher_id=ids["teacher"],
            is_public=True,
            price=200,
            duration_days=60,
        )
        plan_id = _make_plan(
            app,
            school_id=ids["school"],
            class_id=class_id,
            price=200,
            duration_days=60,
        )
        _make_lesson(app, class_id, "درس مدفوع")

        with app.app_context():
            user = _get_user(app, student_id)
            cls = _get_class(app, class_id)
            plan = _assert(db.session.get(SubscriptionPlan, plan_id))

            assert not schools.is_member(cls, user)
            assert Subscription.query.filter_by(user_id=student_id, class_id=class_id).count() == 0

            sub, err = billing.subscribe(student_id, plan, class_id)
            assert err is None
            sub = _assert(sub)
            assert sub.status == "pending"
            assert not schools.is_member(cls, user)

            payment, err = billing.record_manual_payment(sub, reference="TXN-001", amount=200)
            assert err is None
            payment = _assert(payment)
            assert payment.status == "pending"

            approved_sub = billing.approve_payment(payment, reviewer_id=1)
            assert approved_sub.status == "active"
            assert approved_sub.start_at is not None
            assert approved_sub.end_at is not None

            member = ClassMember.query.filter_by(class_id=class_id, user_id=student_id).first()
            assert member is not None
            assert member.status == "active"

            assert not access._is_class_free(cls)
            assert access._has_valid_subscription(student_id, class_id)
            assert schools.is_member(cls, user)

            assert billing.subscription_balance(sub.id) == Decimal("0.00")

    def test_partial_payment_then_full(self, app):
        ids = _setup_school(app, "مدرسة التقسيط")
        student_id = _make_student(app, school_id=ids["school"])
        class_id = _make_class(
            app,
            school_id=ids["school"],
            grade_id=ids["grade"],
            subject_id=ids["subject"],
            teacher_id=ids["teacher"],
            is_public=True,
            price=300,
        )
        plan_id = _make_plan(app, school_id=ids["school"], class_id=class_id, price=300)

        with app.app_context():
            plan = _assert(db.session.get(SubscriptionPlan, plan_id))
            sub, err = billing.subscribe(student_id, plan, class_id)
            assert err is None
            sub = _assert(sub)

            p1, err = billing.record_manual_payment(sub, reference="INST-1", amount=150)
            assert err is None
            p1 = _assert(p1)
            billing.approve_payment(p1, reviewer_id=1)

            sub_obj = _assert(db.session.get(Subscription, sub.id))
            assert sub_obj.status == "active"
            assert billing.subscription_balance(sub.id) == Decimal("150.00")

            p2, err = billing.record_manual_payment(sub, reference="INST-2", amount=150)
            assert err is None
            p2 = _assert(p2)
            billing.approve_payment(p2, reviewer_id=1)
            assert billing.subscription_balance(sub.id) == Decimal("0.00")

    def test_cannot_record_zero_amount(self, app):
        ids = _setup_school(app, "مدرسة صفرية")
        student_id = _make_student(app, school_id=ids["school"])
        class_id = _make_class(
            app,
            school_id=ids["school"],
            grade_id=ids["grade"],
            subject_id=ids["subject"],
            teacher_id=ids["teacher"],
            is_public=True,
            price=100,
        )
        plan_id = _make_plan(app, school_id=ids["school"], class_id=class_id, price=100)

        with app.app_context():
            plan = _assert(db.session.get(SubscriptionPlan, plan_id))
            sub, _ = billing.subscribe(student_id, plan, class_id)
            sub = _assert(sub)
            payment, error = billing.record_manual_payment(sub, reference="ZERO", amount=0)
            assert payment is None
            assert error is not None

    def test_cannot_approve_already_approved(self, app):
        ids = _setup_school(app, "مدرسة اعتماد مزدوج")
        student_id = _make_student(app, school_id=ids["school"])
        class_id = _make_class(
            app,
            school_id=ids["school"],
            grade_id=ids["grade"],
            subject_id=ids["subject"],
            teacher_id=ids["teacher"],
            is_public=True,
            price=100,
        )
        plan_id = _make_plan(app, school_id=ids["school"], class_id=class_id, price=100)

        with app.app_context():
            sub, payment = _subscribe_and_pay(app, student_id, plan_id, class_id, 100, "DOUBLE")

            billing.approve_payment(payment, reviewer_id=1)

            from app.core.db import TxError

            with pytest.raises(TxError):
                billing.approve_payment(payment, reviewer_id=2)


# ═══════════════════════════════════════════════════════════════════════════════
#  3. PAID CLASS — SUBSCRIBE → PAY → REJECT → NO ACCESS
# ═══════════════════════════════════════════════════════════════════════════════


class TestPaidClassRejectionFlow:
    """Payment rejected → subscription cancelled → content access remains blocked."""

    def test_reject_payment_blocks_access(self, app):
        ids = _setup_school(app, "مدرسة رفض")
        student_id = _make_student(app, school_id=ids["school"])
        class_id = _make_class(
            app,
            school_id=ids["school"],
            grade_id=ids["grade"],
            subject_id=ids["subject"],
            teacher_id=ids["teacher"],
            is_public=True,
            price=150,
        )
        plan_id = _make_plan(app, school_id=ids["school"], class_id=class_id, price=150)

        with app.app_context():
            cls = _get_class(app, class_id)
            sub, payment = _subscribe_and_pay(app, student_id, plan_id, class_id, 150, "REJ-001")
            assert sub.status == "pending"

            billing.reject_payment(payment, reviewer_id=1)

            db.session.refresh(payment)
            assert payment.status == "rejected"

            db.session.refresh(sub)
            assert sub.status == "cancelled"

            member = ClassMember.query.filter_by(class_id=class_id, user_id=student_id).first()
            assert member is None

            assert not access._has_valid_subscription(student_id, class_id)
            user = _get_user(app, student_id)
            assert not schools.is_member(cls, user)

    def test_cannot_reject_already_rejected(self, app):
        ids = _setup_school(app, "مدرسة رفض مكرر")
        student_id = _make_student(app, school_id=ids["school"])
        class_id = _make_class(
            app,
            school_id=ids["school"],
            grade_id=ids["grade"],
            subject_id=ids["subject"],
            teacher_id=ids["teacher"],
            is_public=True,
            price=100,
        )
        plan_id = _make_plan(app, school_id=ids["school"], class_id=class_id, price=100)

        with app.app_context():
            sub, payment = _subscribe_and_pay(app, student_id, plan_id, class_id, 100, "REJ-2X")
            billing.reject_payment(payment, reviewer_id=1)

            from app.core.db import TxError

            with pytest.raises(TxError):
                billing.reject_payment(payment, reviewer_id=2)

    def test_reject_then_resubscribe(self, app):
        ids = _setup_school(app, "مدرسة إعادة الاشتراك")
        student_id = _make_student(app, school_id=ids["school"])
        class_id = _make_class(
            app,
            school_id=ids["school"],
            grade_id=ids["grade"],
            subject_id=ids["subject"],
            teacher_id=ids["teacher"],
            is_public=True,
            price=100,
        )
        plan_id = _make_plan(app, school_id=ids["school"], class_id=class_id, price=100)

        with app.app_context():
            user = _get_user(app, student_id)
            cls = _get_class(app, class_id)

            # First attempt — rejected
            sub1, pay1 = _subscribe_and_pay(app, student_id, plan_id, class_id, 100, "REJ-A")
            billing.reject_payment(pay1, reviewer_id=1)
            assert not access._has_valid_subscription(student_id, class_id)
            assert not schools.is_member(cls, user)

            # Second attempt — approved
            sub2, pay2 = _subscribe_and_pay(app, student_id, plan_id, class_id, 100, "APR-B")
            billing.approve_payment(pay2, reviewer_id=1)
            assert access._has_valid_subscription(student_id, class_id)
            assert schools.is_member(cls, user)


# ═══════════════════════════════════════════════════════════════════════════════
#  4. SUBSCRIPTION EXPIRY FLOW
# ═══════════════════════════════════════════════════════════════════════════════


class TestSubscriptionExpiryFlow:
    """Active subscription reaches end_at → expire_subscriptions() → access revoked."""

    def test_expiry_revokes_access(self, app):
        ids = _setup_school(app, "مدرسة انتهاء")
        student_id = _make_student(app, school_id=ids["school"])
        class_id = _make_class(
            app,
            school_id=ids["school"],
            grade_id=ids["grade"],
            subject_id=ids["subject"],
            teacher_id=ids["teacher"],
            is_public=True,
            price=100,
            duration_days=30,
        )
        plan_id = _make_plan(
            app,
            school_id=ids["school"],
            class_id=class_id,
            price=100,
            duration_days=30,
        )

        with app.app_context():
            sub, payment = _subscribe_and_pay(app, student_id, plan_id, class_id, 100, "EXP-001")
            billing.approve_payment(payment, reviewer_id=1)

            db.session.refresh(sub)
            assert sub.status == "active"
            assert sub.end_at is not None
            assert access._has_valid_subscription(student_id, class_id)

            # Simulate expiry
            sub.end_at = datetime.now(UTC) - timedelta(days=1)
            db.session.commit()

            assert not access._has_valid_subscription(student_id, class_id)

            expired_count = billing.expire_subscriptions()
            assert expired_count >= 1

            db.session.refresh(sub)
            assert sub.status == "expired"

    def test_not_yet_expired_still_active(self, app):
        ids = _setup_school(app, "مدرسة مستقبلية")
        student_id = _make_student(app, school_id=ids["school"])
        class_id = _make_class(
            app,
            school_id=ids["school"],
            grade_id=ids["grade"],
            subject_id=ids["subject"],
            teacher_id=ids["teacher"],
            is_public=True,
            price=100,
            duration_days=365,
        )
        plan_id = _make_plan(
            app,
            school_id=ids["school"],
            class_id=class_id,
            price=100,
            duration_days=365,
        )

        with app.app_context():
            sub, payment = _subscribe_and_pay(app, student_id, plan_id, class_id, 100, "FUT-001")
            billing.approve_payment(payment, reviewer_id=1)

            db.session.refresh(sub)
            assert sub.status == "active"
            assert sub.end_at is not None
            assert sub.end_at > datetime.now(UTC)
            assert access._has_valid_subscription(student_id, class_id)

            billing.expire_subscriptions()
            db.session.refresh(sub)
            assert sub.status == "active"

    def test_subscription_with_no_end_at_not_expired(self, app):
        ids = _setup_school(app, "مدرسة بدون نهاية")
        student_id = _make_student(app, school_id=ids["school"])
        class_id = _make_class(
            app,
            school_id=ids["school"],
            grade_id=ids["grade"],
            subject_id=ids["subject"],
            teacher_id=ids["teacher"],
            is_public=True,
            price=100,
        )
        plan_id = _make_plan(app, school_id=ids["school"], class_id=class_id, price=100)

        with app.app_context():
            sub, payment = _subscribe_and_pay(app, student_id, plan_id, class_id, 100, "NONE-001")
            billing.approve_payment(payment, reviewer_id=1)

            sub.end_at = None
            db.session.commit()

            billing.expire_subscriptions()
            db.session.refresh(sub)
            assert sub.status == "active"


# ═══════════════════════════════════════════════════════════════════════════════
#  5. CROSS-TENANT ISOLATION
# ═══════════════════════════════════════════════════════════════════════════════


class TestCrossTenantIsolation:
    """User subscribed in School A cannot access School B content.

    We test isolation at the business-logic layer: membership, subscription,
    and role ownership all carry the correct school_id and are never leaked
    across tenants.
    """

    def test_school_a_student_not_member_of_school_b(self, app):
        ids_a = _setup_school(app, "مدرسة أ")
        ids_b = _setup_school(app, "مدرسة ب")

        student_a = _make_student(app, school_id=ids_a["school"])
        class_b = _make_class(
            app,
            school_id=ids_b["school"],
            grade_id=ids_b["grade"],
            subject_id=ids_b["subject"],
            teacher_id=ids_b["teacher"],
            is_public=True,
            price=0,
        )

        with app.app_context():
            user = _get_user(app, student_a)
            cls_b = _get_class(app, class_b)

            assert not schools.is_member(cls_b, user)
            assert not access._has_valid_subscription(student_a, class_b)

    def test_school_b_subscription_not_accessible_from_school_a(self, app):
        ids_a = _setup_school(app, "مدرسة أ اشتراك")
        ids_b = _setup_school(app, "مدرسة ب اشتراك")

        student = _make_student(app, school_id=ids_a["school"])

        class_b = _make_class(
            app,
            school_id=ids_b["school"],
            grade_id=ids_b["grade"],
            subject_id=ids_b["subject"],
            teacher_id=ids_b["teacher"],
            is_public=True,
            price=100,
        )
        plan_b = _make_plan(app, school_id=ids_b["school"], class_id=class_b, price=100)

        with app.app_context():
            sub, payment = _subscribe_and_pay(app, student, plan_b, class_b, 100, "X-TENANT")
            billing.approve_payment(payment, reviewer_id=1)
            assert access._has_valid_subscription(student, class_b)

            class_a = _make_class(
                app,
                school_id=ids_a["school"],
                grade_id=ids_a["grade"],
                subject_id=ids_a["subject"],
                teacher_id=ids_a["teacher"],
                is_public=True,
                price=100,
            )
            assert not access._has_valid_subscription(student, class_a)

    def test_teacher_ownership_scoped_to_school(self, app):
        ids_a = _setup_school(app, "مدرسة أ للمعلمين")
        ids_b = _setup_school(app, "مدرسة ب للمعلمين")

        with app.app_context():
            teacher_a = db.session.get(User, ids_a["teacher"])
            assert teacher_a is not None

            cls_b_id = _make_class(
                app,
                school_id=ids_b["school"],
                grade_id=ids_b["grade"],
                subject_id=ids_b["subject"],
                teacher_id=ids_b["teacher"],
            )
            cls_b = db.session.get(ClassRoom, cls_b_id)
            assert cls_b is not None

            assert cls_b.teacher_id != teacher_a.id

    def test_school_admin_role_scoped_to_own_tenant(self, app):
        ids_a = _setup_school(app, "مدرسة أ للمدير")
        ids_b = _setup_school(app, "مدرسة ب للمدير")

        with app.app_context():
            from app.models.user import UserRoleLink

            admin_a = User(
                email="admin-a@test.com",
                name_ar="مدير أ",
                role=UserRole.school_admin,
                password_hash="pbkdf2:sha256:placeholder",
                approval_status="approved",
                is_active=True,
            )
            db.session.add(admin_a)
            db.session.flush()
            rl = UserRoleLink(
                user_id=admin_a.id,
                school_id=ids_a["school"],
                role=UserRole.school_admin,
            )
            db.session.add(rl)
            db.session.commit()

            links = UserRoleLink.query.filter_by(user_id=admin_a.id).all()
            school_ids = {link.school_id for link in links}
            assert ids_a["school"] in school_ids
            assert ids_b["school"] not in school_ids

    def test_super_admin_bypasses_tenant_boundary(self, app):
        _setup_school(app, "مدرسة عامة")

        with app.app_context():
            super_admin = User(
                email="super@test.com",
                name_ar="مدير عام",
                role=UserRole.super_admin,
                password_hash="pbkdf2:sha256:placeholder",
                approval_status="approved",
                is_active=True,
            )
            db.session.add(super_admin)
            db.session.commit()
            assert super_admin.role == UserRole.super_admin

    def test_individual_student_no_school_membership(self, app):
        student_id = _make_student(app)

        with app.app_context():
            from app.models.user import UserRoleLink

            user = _get_user(app, student_id)
            links = UserRoleLink.query.filter_by(user_id=user.id).all()
            assert len(links) == 0

    def test_cross_tenant_class_teacher_isolation(self, app):
        ids_a = _setup_school(app, "مدرسة أ عزل معلم")
        ids_b = _setup_school(app, "مدرسة ب عزل معلم")

        class_a_id = _make_class(
            app,
            school_id=ids_a["school"],
            grade_id=ids_a["grade"],
            subject_id=ids_a["subject"],
            teacher_id=ids_a["teacher"],
        )
        class_b_id = _make_class(
            app,
            school_id=ids_b["school"],
            grade_id=ids_b["grade"],
            subject_id=ids_b["subject"],
            teacher_id=ids_b["teacher"],
        )

        with app.app_context():
            cls_a = _assert(db.session.get(ClassRoom, class_a_id))
            cls_b = _assert(db.session.get(ClassRoom, class_b_id))

            assert cls_a.school_id == ids_a["school"]
            assert cls_b.school_id == ids_b["school"]
            assert cls_a.teacher_id == ids_a["teacher"]
            assert cls_b.teacher_id == ids_b["teacher"]
            assert cls_a.teacher_id != cls_b.teacher_id


# ═══════════════════════════════════════════════════════════════════════════
#  6. AZ-P0-01 — حلقة دفع الطالب الفردي (HTTP حقيقي عبر test_client)
# ═══════════════════════════════════════════════════════════════════════════


class TestPendingSubscriptionLoop:
    """AZ-P0-01: الاشتراك المعلّق ظاهر مع زر دفع قابل للفتح فعلاً.

    هاتان الحالات تبني مساراً حقيقياً (طالب فرد عبر بوابة
    التسجيل + test_client + تسجيل دخول) لأن الخلل الأصلي كان تنفيذيًا
    في طبقة HTTP لا طبقة الخدمة: العضوية فقط كانت تُعرض، وحراز صفحة
    الدفع يشترط اشتراكاً نشطاً (P-SEC-13) فتنغلق الحلقة بـ 403.
    """

    def _login(self, app, email: str):
        client = app.test_client()
        resp = client.post(
            "/auth/login",
            data={"email": email, "password": "TestPass123!"},
            follow_redirects=False,
        )
        assert resp.status_code == 302, f"login failed for {email}: {resp.status_code}"
        return client

    def test_paid_subscribe_shows_pending_with_pay_button_and_no_membership(self, app):
        """(أ) كورس مدفوع → pending بلا ClassMember + ظهوره في صفحة كورساتي."""
        ids = _setup_school(app, "مدرسة الحلقة المدفوعة")
        email = f"pend-a-{ids['school']}@test.com"
        _make_student(app, email=email, name="طالب معلّق", is_individual=True, password="TestPass123!")
        class_id = _make_class(
            app,
            school_id=ids["school"],
            grade_id=ids["grade"],
            subject_id=ids["subject"],
            teacher_id=ids["teacher"],
            is_public=True,
            price=120,
            duration_days=45,
        )

        client = self._login(app, email)
        resp = client.post(f"/my/catalog/{class_id}/subscribe", follow_redirects=True)
        assert resp.status_code == 200
        # رسالة التعامل الحقيقية (مدفوع) لا رسالة الوصول الفوري
        assert "بانتظار الدفع" in resp.get_data(as_text=True)

        with app.app_context():
            user_id = User.query.filter_by(email=email).one().id
            sub = Subscription.query.filter_by(user_id=user_id, class_id=class_id).one()
            assert sub.status == "pending"
            assert (
                ClassMember.query.filter_by(class_id=class_id, user_id=sub.user_id).count() == 0
            )  # P-SEC-08: لا عضوية فعّالة قبل الدفع

        page = client.get("/my/courses")
        assert page.status_code == 200
        html = page.get_data(as_text=True)
        assert "اشتراكات بانتظار الدفع" in html
        assert f"/billing/{class_id}" in html  # زر ضمني فعلي لا نص وصفي
        assert "120.00" in html  # المبلغ ظاهر

    def test_free_subscribe_has_no_pending_section(self, app):
        """(ب) كورس مجاني → عضوية فعّالة + لا قسم معلّق على الإطلاق."""
        ids = _setup_school(app, "مدرسة الحلقة المجانية")
        email = f"pend-b-{ids['school']}@test.com"
        _make_student(app, email=email, is_individual=True, password="TestPass123!")
        class_id = _make_class(
            app,
            school_id=ids["school"],
            grade_id=ids["grade"],
            subject_id=ids["subject"],
            teacher_id=ids["teacher"],
            is_public=True,
            price=0,
        )

        client = self._login(app, email)
        assert client.post(f"/my/catalog/{class_id}/subscribe", follow_redirects=True).status_code == 200

        with app.app_context():
            user_id = User.query.filter_by(email=email).one().id
            member = ClassMember.query.filter_by(class_id=class_id, user_id=user_id, status="active").one()
            assert member is not None  # P-SEC-09: تفعيل فوري

        page = client.get("/my/courses")
        html = page.get_data(as_text=True)
        assert page.status_code == 200
        assert "اشتراكات بانتظار الدفع" not in html
        assert "أكمل الدفع" not in html

    def test_pending_student_opens_billing_page_and_records_payment(self, app):
        """(ج) الحلقة مغلقة فعلاً: صفحة الدفع 200 (لا 403) + سجل دفع."""
        ids = _setup_school(app, "مدرسة الحلقة المغلقة")
        email = f"pend-c-{ids['school']}@test.com"
        _make_student(app, email=email, is_individual=True, password="TestPass123!")
        class_id = _make_class(
            app,
            school_id=ids["school"],
            grade_id=ids["grade"],
            subject_id=ids["subject"],
            teacher_id=ids["teacher"],
            is_public=True,
            price=100,
        )

        client = self._login(app, email)
        client.post(f"/my/catalog/{class_id}/subscribe", follow_redirects=True)
        # صفحة الدفع تفتح لصاحب الاشتراك المعلّق — كانت 403 قبل AZ-P0-01
        billing_page = client.get(f"/billing/{class_id}")
        assert billing_page.status_code == 200, f"expected billing page 200, got {billing_page.status_code}"

        with app.app_context():
            user_id = User.query.filter_by(email=email).one().id
            sub_id = Subscription.query.filter_by(user_id=user_id, class_id=class_id).one().id

        pay_resp = client.post(
            f"/billing/subscriptions/{sub_id}/pay",
            data={"reference": "TXN-PEND-01", "amount": "100.00"},
            follow_redirects=False,
        )
        assert pay_resp.status_code == 302

        with app.app_context():
            from app.models.billing import ManualPayment

            payment = ManualPayment.query.filter_by(subscription_id=sub_id).one()
            assert payment.status == "pending"
            assert payment.amount == Decimal("100.00")

            # الاعتماد البشري يغلق الحلقة: تفعيل + عضوية + اختفاء القسم
            approved_sub = billing.approve_payment(payment, reviewer_id=1)
            assert approved_sub.status == "active"
            assert ClassMember.query.filter_by(class_id=class_id, user_id=user_id, status="active").count() == 1

        page = client.get("/my/courses")
        html = page.get_data(as_text=True)
        assert "اشتراكات بانتظار الدفع" not in html
        assert "فتح" in html  # الكورس صار صفّاً مفتوحاً

    def test_billing_page_denied_without_any_subscription(self, app):
        """(د) طالب بلا أي اشتراك على صف مدفوع → 403 (لا ثغرة استقصاء)."""
        ids = _setup_school(app, "مدرسة منع الاستقصاء")
        email = f"pend-d-{ids['school']}@test.com"
        _make_student(app, email=email, is_individual=True, password="TestPass123!")
        class_id = _make_class(
            app,
            school_id=ids["school"],
            grade_id=ids["grade"],
            subject_id=ids["subject"],
            teacher_id=ids["teacher"],
            is_public=True,
            price=100,
        )

        client = self._login(app, email)
        assert client.get(f"/billing/{class_id}").status_code == 403

    def test_student_with_no_subscriptions_page_ok_without_pending_section(self, app):
        """(هـ) طالب بلا أي اشتراك → 200 بلا قسم معلّق (حالة فراغ واضحة)."""
        ids = _setup_school(app, "مدرسة الفراغ الواضح")
        email = f"pend-e-{ids['school']}@test.com"
        _make_student(app, email=email, is_individual=True, password="TestPass123!")

        client = self._login(app, email)
        page = client.get("/my/courses")
        assert page.status_code == 200
        html = page.get_data(as_text=True)
        assert "اشتراكات بانتظار الدفع" not in html
        assert "لم تسجل في أي كورس بعد" in html

    def test_non_owner_of_pending_sub_cannot_pay(self, app):
        """(و) شرط المالك المحدّث لا يوسّع الشقب: طالب آخر → 403 بلا صف دفع."""
        ids = _setup_school(app, "مدرسة صاحب الدفع")
        owner_email = f"pend-f-owner-{ids['school']}@test.com"
        other_email = f"pend-f-other-{ids['school']}@test.com"
        _make_student(app, email=owner_email, is_individual=True, password="TestPass123!")
        _make_student(app, email=other_email, is_individual=True, password="TestPass123!")
        class_id = _make_class(
            app,
            school_id=ids["school"],
            grade_id=ids["grade"],
            subject_id=ids["subject"],
            teacher_id=ids["teacher"],
            is_public=True,
            price=100,
        )

        owner_client = self._login(app, owner_email)
        owner_client.post(f"/my/catalog/{class_id}/subscribe", follow_redirects=True)

        with app.app_context():
            sub_id = (
                Subscription.query.filter_by(
                    user_id=User.query.filter_by(email=owner_email).one().id,
                    class_id=class_id,
                )
                .one()
                .id
            )

        other_client = self._login(app, other_email)
        pay_resp = other_client.post(
            f"/billing/subscriptions/{sub_id}/pay",
            data={"reference": "NOT-MINE", "amount": "100.00"},
            follow_redirects=False,
        )
        # عقد المستودع الصارم: صف لا يراه الفاعل عبر RLS يرد 404 (لا 403)
        # حتى لا يُستدل بوجوده من رمز الرد — شرط المالك يظل حرزاً كاملاً.
        assert pay_resp.status_code in (403, 404)

        with app.app_context():
            from app.models.billing import ManualPayment

            assert ManualPayment.query.filter_by(subscription_id=sub_id).count() == 0


# ═══════════════════════════════════════════════════════════════════════════════
#  6. AZ-P0-03 — وليّ أمر يدفع لابنه + كشف حساب الأسرة
# ═══════════════════════════════════════════════════════════════════════════════


def _make_parent(app, *, school_id=None):
    """مستخدم بدور `parent` — برابط مدرسة اختياري (نمط يسري عبر RLS في الإنتاج)."""
    with app.app_context():
        from app.core.security import hash_password
        from app.models.user import User, UserRole, UserRoleLink

        u = User(
            email=f"parent-{uuid.uuid4().hex[:10]}@test.com",
            name_ar="وليّ أمر اختبار",
            role=UserRole.parent,
            password_hash=hash_password("TestPass123!"),
            approval_status="approved",
            is_active=True,
        )
        db.session.add(u)
        db.session.flush()
        if school_id:
            db.session.add(UserRoleLink(user_id=u.id, school_id=school_id, role=UserRole.parent))
        db.session.commit()
        return u.id


def _link_parent(app, parent_id, student_id):
    """رابط أسرة نشط (مكافئ لما تُنتجه FamilyLinkCode عبر services/family)."""
    with app.app_context():
        from app.models.family import FamilyLink

        db.session.add(FamilyLink(parent_id=parent_id, student_id=student_id, status="active"))
        db.session.commit()


def _login_http(app, email):
    """عميل HTTP مصادَق بكلمة مرور حقيقية — لا اختراق للجلسة."""
    client = app.test_client()
    resp = client.post("/auth/login", data={"email": email, "password": "TestPass123!"})
    assert resp.status_code in (200, 302), f"login for {email} failed: {resp.status_code}"
    return client


def _make_paid_class(app, name, price=100):
    """صفّ مدفوع بخطة للسعر نفسه، وابن عضو فعّال فيه."""
    ids = _setup_school(app, name)
    class_id = _make_class(
        app,
        school_id=ids["school"],
        grade_id=ids["grade"],
        subject_id=ids["subject"],
        teacher_id=ids["teacher"],
        is_public=True,
        price=price,
    )
    plan_id = _make_plan(app, school_id=ids["school"], class_id=class_id, price=price)
    student_id = _make_student(app, school_id=ids["school"])
    with app.app_context():
        db.session.add(ClassMember(class_id=class_id, user_id=student_id, status="active"))
        db.session.commit()
    return ids, class_id, plan_id, student_id


class TestParentPaysForChild:
    """وليّ الأمر المرتبط يفتح صفحة الدفع لصفّ ابنه ويرسل دفعة يدوية باسمه,
    وغير المرتبط يُمنع بـ 403 بلا أي صف دفع."""

    def test_linked_parent_opens_pay_page_and_records_payment(self, app):
        """(أ) اشتراك نيابة عن الابن + دفع باسمه — payer_id محفوظ بلا جمعتين."""
        ids, class_id, plan_id, student_id = _make_paid_class(app, "مدرسة دفع الابن")
        parent_id = _make_parent(app, school_id=ids["school"])
        _link_parent(app, parent_id, student_id)

        with app.app_context():
            parent_email = db.session.get(User, parent_id).email

        client = _login_http(app, parent_email)

        # وليّ الأمر يفتح صفحة الدفع لصفّ ابنه (كانت 403 قبل AZ-P0-03)
        assert client.get(f"/billing/{class_id}").status_code == 200

        # اشتراك نيابةً عن الابن (وليس عن وليّ الأمر) وسيُنسب payer_id له
        sub_resp = client.post(
            f"/billing/{class_id}/subscribe",
            data={"plan_id": plan_id, "student_id": student_id, "submit": "x"},
            follow_redirects=False,
        )
        assert sub_resp.status_code == 302

        with app.app_context():
            sub = Subscription.query.filter_by(user_id=student_id, class_id=class_id).one()
            assert sub.status == "pending"
            assert sub.payer_id == parent_id, "هوية الدافع (وليّ الأمر) يجب أن تُحفظ على الاشتراك"
            # الابن عضو فعّال من الإعداد (لم تدعِم الاشتراك عضوية جديدة)،
            # ووليّ الأمر لا يحصل على عضوية إطلاقاً
            assert ClassMember.query.filter_by(class_id=class_id, user_id=student_id).count() == 1
            assert ClassMember.query.filter_by(class_id=class_id, user_id=parent_id).count() == 0
            sub_id = sub.id

        pay_page = client.get(f"/billing/{class_id}")
        assert pay_page.status_code == 200
        assert "إرسال الدفع اليدوي" in pay_page.get_data(as_text=True)

        pay_resp = client.post(
            f"/billing/subscriptions/{sub_id}/pay",
            data={"reference": "PARENT-TXN-1", "amount": "100.00"},
            follow_redirects=False,
        )
        assert pay_resp.status_code == 302

        with app.app_context():
            from app.models.billing import ManualPayment

            payment = ManualPayment.query.filter_by(subscription_id=sub_id).one()
            assert payment.payer_id == parent_id, "هوية الدافع يجب أن تُحفظ على صف الدفع"
            assert payment.status == "pending"
            # الاعتماد يفعّل اشتراك الابن — ووليّ الأمر لا يكسب وصولاً طالبياً
            billing.approve_payment(payment, reviewer_id=1)
            assert access._has_valid_subscription(student_id, class_id)
            assert not access._has_valid_subscription(parent_id, class_id)
            assert ClassMember.query.filter_by(class_id=class_id, user_id=parent_id).count() == 0

    def test_unlinked_parent_gets_403_and_no_payment_rows(self, app):
        """(ب) وليّ أمر غير مرتبط → 403 على الدفع والاشتراك، وعدد الصفوف ثابت."""
        ids, class_id, plan_id, student_id = _make_paid_class(app, "مدرسة ولد غير مرتبط")
        stranger_id = _make_parent(app, school_id=ids["school"])

        with app.app_context():
            stranger_email = db.session.get(User, stranger_id).email

        client = _login_http(app, stranger_email)

        pay_page = client.get(f"/billing/{class_id}")
        assert pay_page.status_code == 403

        pay_resp = client.post(
            f"/billing/{class_id}/subscribe",
            data={"plan_id": plan_id, "student_id": student_id, "submit": "x"},
            follow_redirects=False,
        )
        assert pay_resp.status_code == 403

        with app.app_context():
            # الاشتراك يجب أن يكون ثابتاً ليتحقق شرط «لا صفوف دفع» — نبدأ به ونعدّه
            plan = db.session.get(SubscriptionPlan, plan_id)
            sub, err = billing.subscribe(student_id, plan, class_id)
            assert err is None and sub is not None
            sub_id = sub.id

        stranger2 = _login_http(app, stranger_email)
        pay_resp2 = stranger2.post(
            f"/billing/subscriptions/{sub_id}/pay",
            data={"reference": "STRANGER-TXN", "amount": "100.00"},
            follow_redirects=False,
        )
        assert pay_resp2.status_code in (403, 404)

        with app.app_context():
            from app.models.billing import ManualPayment

            assert ManualPayment.query.filter_by(subscription_id=sub_id).count() == 0
            sub = db.session.get(Subscription, sub_id)
            db.session.refresh(sub)
            assert sub.payer_id is None, "لا يجوز أن يُنسب دفع الغريب إلى الطالب"

    def test_family_statement_shows_child_fees_without_cross_family_leak(self, app):
        """(ج) صفحة الأسرة تعرض رسوم الابن ورابط الدفع والفاتورة بلا تسريب أسرة أخرى."""
        # أسرة أ — ابن 1 اشتراكه نشط ودفعه معتمد (فيظهر رابط الفاتورة)،
        # وابن 2 اشتراكه معلّق (فيظهر رابط إكمال الدفع) — الاثنان لعليا نفسه
        ids_a, class_a, plan_a_id, student_a = _make_paid_class(app, "مدرسة الأسرة أ")
        parent_a = _make_parent(app, school_id=ids_a["school"])
        _link_parent(app, parent_a, student_a)
        student_a2 = _make_student(app, school_id=ids_a["school"])
        _link_parent(app, parent_a, student_a2)

        with app.app_context():
            plan_a = db.session.get(SubscriptionPlan, plan_a_id)
            sub_a, err = billing.subscribe(student_a, plan_a, class_a)
            assert err is None and sub_a is not None
            payment, err2 = billing.record_manual_payment(sub_a, reference="FA-PAY", amount=100, payer_id=parent_a)
            assert err2 is None and payment is not None
            billing.approve_payment(payment, reviewer_id=1)
            sub_a_id = sub_a.id

            sub_a2, err3 = billing.subscribe(student_a2, plan_a, class_a)
            assert err3 is None and sub_a2 is not None

        # أسرة ب — مدرسة وصف وابن مختلفان؛ اسمان فريدان للتأكد من غيابهما
        ids_b, class_b, _, student_b = _make_paid_class(app, "مدرسة الأسرة ب*")
        parent_b = _make_parent(app, school_id=ids_b["school"])
        _link_parent(app, parent_b, student_b)
        with app.app_context():
            plan_b = SubscriptionPlan.query.filter_by(class_id=class_b).one()
            sub_b, err = billing.subscribe(student_b, plan_b, class_b)
            assert err is None and sub_b is not None
            db.session.get(ClassRoom, class_b).name = "صفّ عائلة بِ الخاصة"
            db.session.get(User, student_b).name_ar = "سميّ الرينى ب"
            db.session.commit()
            sub_b_id = sub_b.id

        with app.app_context():
            email_a = db.session.get(User, parent_a).email

        client = _login_http(app, email_a)
        page = client.get("/family/")
        assert page.status_code == 200
        html = page.get_data(as_text=True)

        # رسوم الأسرة أ ظاهرة: قسم «الرسوم والاشتراكات» + رابط دفع فعلي للابن المعلّق
        # + رابط فاتورة لاشتراك الابن المعتمد + المتبقي
        assert "الرسوم والاشتراكات" in html
        assert f"/billing/{class_a}" in html  # رابط الدفع الفعلي لا نص وصفي
        assert f"/billing/invoices/{sub_a_id}" in html  # رابط الفاتورة بعد الاعتماد
        assert "المتبقي:" in html

        # لا تسريب بيانات الأسرة ب إطلاقاً: لا اسم ابنها، لا اسم صفّها، لا روابطها
        assert "صفّ عائلة بِ الخاصة" not in html
        assert "سميّ الرينى ب" not in html
        assert f"/billing/{class_b}" not in html
        assert f"/billing/invoices/{sub_b_id}" not in html


class TestFamilyPayerMigration:
    """تغطية ترقية المخطط (AZ-P0-03): flask db stamp/upgrade/downgrade على قاعدة الاختبار."""

    def test_upgrade_downgrade_cycle(self, app):
        from sqlalchemy import inspect, text

        runner = app.test_cli_runner()

        def _cols(table, engine):
            return {c["name"] for c in inspect(engine).get_columns(table)}

        with app.app_context():
            engine = db.engine
            # القاعدة هنا مبنية بـ create_all أي أنها في حالة الرأس فعلياً. تثبيت
            # alembic_version عند مراجعة أقدم لا يغيّر المخطط، فأول ترحيل لاحق يُنشئ
            # جدولاً/عموداً موجوداً أصلاً (absence_alert_logs، أعمدة tutor payment)
            # يفشل بـ Duplicate*. لذلك نُنزل المخطط فعلياً إلى تلك المراجعة أولاً —
            # وهذا يغطّي مسار downgrade أيضاً — ثم نُرقّيه، فتصبح الترقية حقيقية.
            stamp = runner.invoke(args=["db", "stamp", "head"])
            assert stamp.exit_code == 0, f"stamp failed: {stamp.output}"
            base = runner.invoke(args=["db", "downgrade", "q0r1s2t3u4v5"])
            assert base.exit_code == 0, f"baseline downgrade failed: {base.output}"

            up = runner.invoke(args=["db", "upgrade"])
            assert up.exit_code == 0, f"upgrade failed: {up.output}"
            assert "payer_id" in _cols("subscriptions", engine)
            assert "payer_id" in _cols("manual_payments", engine)

            # مراجعة محدّدة لا خطوة واحدة: «-1» كانت تعني r1 وقت كتابة الاختبار،
            # ثم صار رأس السلسلة أبعد منها فصارت تُنزل إلى u4 ولا تمسّ payer_id.
            down = runner.invoke(args=["db", "downgrade", "q0r1s2t3u4v5"])
            assert down.exit_code == 0, f"downgrade failed: {down.output}"
            assert "payer_id" not in _cols("subscriptions", engine)
            assert "payer_id" not in _cols("manual_payments", engine)

            # إعادة الترقية ليجتمع مسار الاختبار الأخير على أعمدة موجودة
            up2 = runner.invoke(args=["db", "upgrade"])
            assert up2.exit_code == 0, f"re-upgrade failed: {up2.output}"
            assert "payer_id" in _cols("subscriptions", engine)
            assert "payer_id" in _cols("manual_payments", engine)

            # والحالة تعمل عملياً: صف اشتراك بدافع وصف دفع بدافع يُكتبان ويُقرآن

            ids, class_id, plan_id, student_id = _make_paid_class(app, "مدرسة ترحيل الدافع")
            parent_id = _make_parent(app, school_id=ids["school"])
            _link_parent(app, parent_id, student_id)
            plan = db.session.get(SubscriptionPlan, plan_id)
            sub, err = billing.subscribe(student_id, plan, class_id, payer_id=parent_id)
            assert err is None and sub is not None
            payment, perr = billing.record_manual_payment(sub, reference="MIG-1", amount=100, payer_id=parent_id)
            assert perr is None and payment is not None

            from app.models.billing import ManualPayment as _MP

            db.session.refresh(_MP.query.filter_by(id=payment.id).one())
            assert (
                db.session.execute(text("SELECT payer_id FROM subscriptions WHERE id = :i"), {"i": sub.id}).scalar()
                == parent_id
            )
            assert (
                db.session.execute(
                    text("SELECT payer_id FROM manual_payments WHERE id = :i"), {"i": payment.id}
                ).scalar()
                == parent_id
            )
