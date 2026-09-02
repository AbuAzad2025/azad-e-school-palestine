"""خدمات الطلاب الأفراد — كورسات عامة واشتراكات فردية."""

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import joinedload

from app.core.db import tx
from app.core.i18n import _
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

    plan = SubscriptionPlan.query.filter_by(class_id=cls.id, is_active=True).first()
    if not plan and cls.price:
        plan = SubscriptionPlan(
            school_id=cls.school_id,
            class_id=cls.id,
            name=f"اشتراك {cls.name or cls.subject.name_ar}",
            plan="individual",
            price=float(cls.price),
            duration_days=cls.duration_days or 30,
        )
        db.session.add(plan)
        db.session.flush()

    # P-SEC-09: حدد: مجاني أم مدفوع
    is_paid = plan and Decimal(str(plan.price)) > 0

    def _subscribe():
        if is_paid:
            # P-SEC-07: مدفوع — اشتراك pending فقط، لا عضوية فعّالة
            now = datetime.now(UTC)
            db.session.add(
                Subscription(
                    user_id=student_id,
                    plan_id=plan.id,
                    class_id=cls.id,
                    price=float(cls.price or 0),
                    currency=cls.currency,
                    start_at=None,
                    end_at=None,
                    status="pending",
                    source="individual",
                )
            )
        else:
            # P-SEC-09: مجاني — تفعيل فوري
            db.session.add(ClassMember(class_id=cls.id, user_id=student_id, status="active", joined_at=db.func.now()))
            if plan:
                now = datetime.now(UTC)
                db.session.add(
                    Subscription(
                        user_id=student_id,
                        plan_id=plan.id,
                        class_id=cls.id,
                        price=0,
                        currency=cls.currency,
                        start_at=now,
                        end_at=now + timedelta(days=cls.duration_days or 30),
                        status="active",
                        source="individual",
                    )
                )

    tx(_subscribe)
    return None
