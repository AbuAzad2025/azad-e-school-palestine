"""خدمات الطلاب الأفراد — كورسات عامة واشتراكات فردية."""

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import joinedload

from app.core.db import tx
from app.core.i18n import _
from app.core.rls import platform_scope
from app.extensions import db
from app.models.billing import Subscription, SubscriptionPlan
from app.models.class_room import ClassMember, ClassRoom
from app.models.user import User
from app.services.schools import is_member


def get_public_classes(subject_id=None, grade_level=None):
    query = ClassRoom.query.filter_by(is_public=True, is_active=True).options(
        joinedload(ClassRoom.subject),
        joinedload(ClassRoom.grade),
        joinedload(ClassRoom.teacher),
    )
    if subject_id:
        query = query.filter_by(subject_id=subject_id)
    if grade_level:
        from app.models.school import Grade

        query = query.join(Grade, ClassRoom.grade_id == Grade.id).filter(Grade.grade_level == grade_level)
    return query.order_by(ClassRoom.id.desc()).all()


def get_student_classes(student_id):
    return (
        ClassMember.query.filter_by(user_id=student_id, status="active")
        .join(ClassRoom, ClassMember.class_id == ClassRoom.id)
        .options(
            joinedload(ClassMember.class_room).joinedload(ClassRoom.subject),
            joinedload(ClassMember.class_room).joinedload(ClassRoom.grade),
        )
        .all()
    )


def _persist_plan(plan: SubscriptionPlan) -> int:
    """Persist the plan and return its id before the commit expires the object."""
    db.session.add(plan)
    db.session.flush()
    return plan.id


def subscribe_to_class(student_id: int, class_id: int) -> str | None:
    """Individual student subscribes to a public class.

    P-SEC-07: الاشتراك يبدأ بحالة pending — لا يُفعَّل إلا بعد الدفع.
    P-SEC-08: لا تنشئ عضوية فعّالة حتى تتم الموافقة على الدفع.
    P-SEC-09: الصفوف المجانية (بدون خطة أو سعر صفر) تنشئ اشتراكاً فورياً.
    """
    from decimal import Decimal

    cls = db.session.get(ClassRoom, class_id)
    if not cls or not cls.is_public:
        return _("هذا الكورس غير متاح.")
    user = db.session.get(User, student_id)
    if not user:
        return _("المستخدم غير موجود.")
    if is_member(cls, user):
        return _("أنت مشترك في هذا الكورس مسبقاً.")
    if cls.max_students:
        current_count = ClassMember.query.filter_by(class_id=cls.id, status="active").count()
        if current_count >= cls.max_students:
            return _("الكورس ممتلئ.")

    # كل القيم تُلتقط كسلائم *قبل* أي commit: commit الـ tx() يُقيد
    # كائنات ORM، وإعادة تحميلها لاحقاً تأتي بإطار تينانت لا يرى صفّ
    # الخطة (مدرسة أخرى) فترمي ObjectDeletedError تحت RLS مُجبر —
    # وهذا هو الـ500 الذي كان يظهر على الخادم الحقيقي فقط لا محلياً.
    cls_id = cls.id
    cls_price = float(cls.price) if cls.price else 0.0
    cls_currency = cls.currency
    cls_duration = cls.duration_days or 30

    plan = SubscriptionPlan.query.filter_by(class_id=cls_id, is_active=True).first()
    plan_id: int | None = None
    plan_price: float | None = None
    if plan is not None:
        plan_id = plan.id
        plan_price = float(plan.price)
    elif cls_price:
        # `subscriptions.plan_id` is NOT NULL, so a paid class needs a plan row
        # to point at. That row is the *school's* pricing, and the subscriber
        # has no business writing into another tenant's billing tables -- RLS
        # is right to refuse it. So the platform materialises it, inside its
        # own scope, from the class's published price. The price cannot have
        # been chosen by the subscriber: `classes` keeps a tenant-only
        # WITH CHECK, so only the owning school ever wrote it.
        plan = SubscriptionPlan(
            school_id=cls.school_id,
            class_id=cls_id,
            name=f"اشتراك {cls.name}",
            plan="individual",
            price=cls_price,
            duration_days=cls_duration,
        )
        # المعرف يُقرأ *داخل* معاملة الكتابة (flush قبل commit) — بعد
        # الـcommit لا يعاد تحميله بإطار تينانت يخفي الصف.
        with platform_scope():
            plan_id = tx(lambda: _persist_plan(plan))
        plan_price = cls_price

    # P-SEC-09: حدد: مجاني أم مدفوع — من القيم السلمية الملتقَطة لا الكائن.
    is_paid = plan_price is not None and Decimal(str(plan_price)) > 0

    def _subscribe():
        if is_paid:
            # P-SEC-07: مدفوع — اشتراك pending فقط، لا عضوية فعّالة
            now = datetime.now(UTC)
            db.session.add(
                Subscription(
                    user_id=student_id,
                    plan_id=plan_id,
                    class_id=cls_id,
                    price=cls_price,
                    currency=cls_currency,
                    start_at=None,
                    end_at=None,
                    status="pending",
                    source="individual",
                )
            )
        else:
            # P-SEC-09: مجاني — تفعيل فوري
            db.session.add(ClassMember(class_id=cls_id, user_id=student_id, status="active", joined_at=db.func.now()))
            if plan_id is not None:
                now = datetime.now(UTC)
                db.session.add(
                    Subscription(
                        user_id=student_id,
                        plan_id=plan_id,
                        class_id=cls_id,
                        price=0,
                        currency=cls_currency,
                        start_at=now,
                        end_at=now + timedelta(days=cls_duration),
                        status="active",
                        source="individual",
                    )
                )

    tx(_subscribe)
    return None
