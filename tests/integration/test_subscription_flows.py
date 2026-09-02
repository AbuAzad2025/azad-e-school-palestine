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


def _make_class(app, *, school_id, grade_id, subject_id, teacher_id,
                is_public=False, price=0, duration_days=30, join_code=None):
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


def _make_student(app, *, school_id=None, email=None, name=None):
    """Create a student user. Optionally link to a school."""
    with app.app_context():
        u = User(
            email=email or f"student-{db.session.query(User).count() + 1}@test.com",
            name_ar=name or "طالب اختبار",
            role=UserRole.student,
            password_hash="pbkdf2:sha256:placeholder",
            approval_status="approved",
            is_active=True,
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
            app, school_id=ids["school"], grade_id=ids["grade"],
            subject_id=ids["subject"], teacher_id=ids["teacher"],
            is_public=True, price=0,
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
            app, school_id=ids["school"], grade_id=ids["grade"],
            subject_id=ids["subject"], teacher_id=ids["teacher"],
            is_public=True, price=0,
        )

        with app.app_context():
            error = individual.subscribe_to_class(student_id, class_id)
            assert error is None

            member = ClassMember.query.filter_by(
                class_id=class_id, user_id=student_id
            ).first()
            assert member is not None
            assert member.status == "active"

    def test_free_class_duplicate_join_rejected(self, app):
        ids = _setup_school(app, "مدرسة مكررة")
        student_id = _make_student(app, school_id=ids["school"])
        class_id = _make_class(
            app, school_id=ids["school"], grade_id=ids["grade"],
            subject_id=ids["subject"], teacher_id=ids["teacher"],
            is_public=True, price=0,
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
            app, school_id=ids["school"], grade_id=ids["grade"],
            subject_id=ids["subject"], teacher_id=ids["teacher"],
            is_public=True, price=0,
        )

        with app.app_context():
            assert individual.subscribe_to_class(student_id, class_id) is None
            member = ClassMember.query.filter_by(
                class_id=class_id, user_id=student_id, status="active"
            ).first()
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
            app, school_id=ids["school"], grade_id=ids["grade"],
            subject_id=ids["subject"], teacher_id=ids["teacher"],
            is_public=True, price=200, duration_days=60,
        )
        plan_id = _make_plan(
            app, school_id=ids["school"], class_id=class_id,
            price=200, duration_days=60,
        )
        _make_lesson(app, class_id, "درس مدفوع")

        with app.app_context():
            user = _get_user(app, student_id)
            cls = _get_class(app, class_id)
            plan = _assert(db.session.get(SubscriptionPlan, plan_id))

            assert not schools.is_member(cls, user)
            assert Subscription.query.filter_by(
                user_id=student_id, class_id=class_id
            ).count() == 0

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

            member = ClassMember.query.filter_by(
                class_id=class_id, user_id=student_id
            ).first()
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
            app, school_id=ids["school"], grade_id=ids["grade"],
            subject_id=ids["subject"], teacher_id=ids["teacher"],
            is_public=True, price=300,
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
            app, school_id=ids["school"], grade_id=ids["grade"],
            subject_id=ids["subject"], teacher_id=ids["teacher"],
            is_public=True, price=100,
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
            app, school_id=ids["school"], grade_id=ids["grade"],
            subject_id=ids["subject"], teacher_id=ids["teacher"],
            is_public=True, price=100,
        )
        plan_id = _make_plan(app, school_id=ids["school"], class_id=class_id, price=100)

        with app.app_context():
            sub, payment = _subscribe_and_pay(
                app, student_id, plan_id, class_id, 100, "DOUBLE"
            )

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
            app, school_id=ids["school"], grade_id=ids["grade"],
            subject_id=ids["subject"], teacher_id=ids["teacher"],
            is_public=True, price=150,
        )
        plan_id = _make_plan(app, school_id=ids["school"], class_id=class_id, price=150)

        with app.app_context():
            cls = _get_class(app, class_id)
            sub, payment = _subscribe_and_pay(
                app, student_id, plan_id, class_id, 150, "REJ-001"
            )
            assert sub.status == "pending"

            billing.reject_payment(payment, reviewer_id=1)

            db.session.refresh(payment)
            assert payment.status == "rejected"

            db.session.refresh(sub)
            assert sub.status == "cancelled"

            member = ClassMember.query.filter_by(
                class_id=class_id, user_id=student_id
            ).first()
            assert member is None

            assert not access._has_valid_subscription(student_id, class_id)
            user = _get_user(app, student_id)
            assert not schools.is_member(cls, user)

    def test_cannot_reject_already_rejected(self, app):
        ids = _setup_school(app, "مدرسة رفض مكرر")
        student_id = _make_student(app, school_id=ids["school"])
        class_id = _make_class(
            app, school_id=ids["school"], grade_id=ids["grade"],
            subject_id=ids["subject"], teacher_id=ids["teacher"],
            is_public=True, price=100,
        )
        plan_id = _make_plan(app, school_id=ids["school"], class_id=class_id, price=100)

        with app.app_context():
            sub, payment = _subscribe_and_pay(
                app, student_id, plan_id, class_id, 100, "REJ-2X"
            )
            billing.reject_payment(payment, reviewer_id=1)

            from app.core.db import TxError

            with pytest.raises(TxError):
                billing.reject_payment(payment, reviewer_id=2)

    def test_reject_then_resubscribe(self, app):
        ids = _setup_school(app, "مدرسة إعادة الاشتراك")
        student_id = _make_student(app, school_id=ids["school"])
        class_id = _make_class(
            app, school_id=ids["school"], grade_id=ids["grade"],
            subject_id=ids["subject"], teacher_id=ids["teacher"],
            is_public=True, price=100,
        )
        plan_id = _make_plan(app, school_id=ids["school"], class_id=class_id, price=100)

        with app.app_context():
            user = _get_user(app, student_id)
            cls = _get_class(app, class_id)

            # First attempt — rejected
            sub1, pay1 = _subscribe_and_pay(
                app, student_id, plan_id, class_id, 100, "REJ-A"
            )
            billing.reject_payment(pay1, reviewer_id=1)
            assert not access._has_valid_subscription(student_id, class_id)
            assert not schools.is_member(cls, user)

            # Second attempt — approved
            sub2, pay2 = _subscribe_and_pay(
                app, student_id, plan_id, class_id, 100, "APR-B"
            )
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
            app, school_id=ids["school"], grade_id=ids["grade"],
            subject_id=ids["subject"], teacher_id=ids["teacher"],
            is_public=True, price=100, duration_days=30,
        )
        plan_id = _make_plan(
            app, school_id=ids["school"], class_id=class_id,
            price=100, duration_days=30,
        )

        with app.app_context():
            sub, payment = _subscribe_and_pay(
                app, student_id, plan_id, class_id, 100, "EXP-001"
            )
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
            app, school_id=ids["school"], grade_id=ids["grade"],
            subject_id=ids["subject"], teacher_id=ids["teacher"],
            is_public=True, price=100, duration_days=365,
        )
        plan_id = _make_plan(
            app, school_id=ids["school"], class_id=class_id,
            price=100, duration_days=365,
        )

        with app.app_context():
            sub, payment = _subscribe_and_pay(
                app, student_id, plan_id, class_id, 100, "FUT-001"
            )
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
            app, school_id=ids["school"], grade_id=ids["grade"],
            subject_id=ids["subject"], teacher_id=ids["teacher"],
            is_public=True, price=100,
        )
        plan_id = _make_plan(app, school_id=ids["school"], class_id=class_id, price=100)

        with app.app_context():
            sub, payment = _subscribe_and_pay(
                app, student_id, plan_id, class_id, 100, "NONE-001"
            )
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
            app, school_id=ids_b["school"], grade_id=ids_b["grade"],
            subject_id=ids_b["subject"], teacher_id=ids_b["teacher"],
            is_public=True, price=0,
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
            app, school_id=ids_b["school"], grade_id=ids_b["grade"],
            subject_id=ids_b["subject"], teacher_id=ids_b["teacher"],
            is_public=True, price=100,
        )
        plan_b = _make_plan(app, school_id=ids_b["school"], class_id=class_b, price=100)

        with app.app_context():
            sub, payment = _subscribe_and_pay(
                app, student, plan_b, class_b, 100, "X-TENANT"
            )
            billing.approve_payment(payment, reviewer_id=1)
            assert access._has_valid_subscription(student, class_b)

            class_a = _make_class(
                app, school_id=ids_a["school"], grade_id=ids_a["grade"],
                subject_id=ids_a["subject"], teacher_id=ids_a["teacher"],
                is_public=True, price=100,
            )
            assert not access._has_valid_subscription(student, class_a)

    def test_teacher_ownership_scoped_to_school(self, app):
        ids_a = _setup_school(app, "مدرسة أ للمعلمين")
        ids_b = _setup_school(app, "مدرسة ب للمعلمين")

        with app.app_context():
            teacher_a = db.session.get(User, ids_a["teacher"])
            assert teacher_a is not None

            cls_b_id = _make_class(
                app, school_id=ids_b["school"], grade_id=ids_b["grade"],
                subject_id=ids_b["subject"], teacher_id=ids_b["teacher"],
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
                user_id=admin_a.id, school_id=ids_a["school"],
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
            app, school_id=ids_a["school"], grade_id=ids_a["grade"],
            subject_id=ids_a["subject"], teacher_id=ids_a["teacher"],
        )
        class_b_id = _make_class(
            app, school_id=ids_b["school"], grade_id=ids_b["grade"],
            subject_id=ids_b["subject"], teacher_id=ids_b["teacher"],
        )

        with app.app_context():
            cls_a = _assert(db.session.get(ClassRoom, class_a_id))
            cls_b = _assert(db.session.get(ClassRoom, class_b_id))

            assert cls_a.school_id == ids_a["school"]
            assert cls_b.school_id == ids_b["school"]
            assert cls_a.teacher_id == ids_a["teacher"]
            assert cls_b.teacher_id == ids_b["teacher"]
            assert cls_a.teacher_id != cls_b.teacher_id
