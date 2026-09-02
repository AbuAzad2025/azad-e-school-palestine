from datetime import UTC, datetime

from app.core.tenancy import current_school_id
from app.models.user import UserRole
from app.services.schools import is_member


def _is_class_free(class_room) -> bool:
    """Check if a class is free (no paid SubscriptionPlan)."""
    from decimal import Decimal

    from app.models.billing import SubscriptionPlan

    plan = SubscriptionPlan.query.filter_by(class_id=class_room.id, is_active=True).first()
    if not plan:
        return True
    return Decimal(str(plan.price)) <= 0


def _has_valid_subscription(user_id: int, class_id: int) -> bool:
    """Check if user has an active, non-expired subscription for a class."""
    from app.models.billing import Subscription

    now = datetime.now(UTC)
    sub = Subscription.query.filter_by(user_id=user_id, class_id=class_id, status="active").first()
    if not sub:
        return False
    # P-SEC-10: تحقق من انتهاء الصلاحية
    if sub.end_at and sub.end_at < now:
        return False
    return True


def can_view_class(class_room, user) -> bool:
    """Determine if a user can view class content.

    P-SEC-11: super_admin و school_admin/teacher يحصلون على وصول كامل.
    P-SEC-12: الصفوف المجانية — العضوية كافية.
    P-SEC-13: الصفوف المدفوعة — يجب اشتراك نشط غير منتهي.
    """
    # P-SEC-11: إدارة علوية — وصول كامل دائماً
    if user.role == UserRole.super_admin:
        return True
    if current_school_id() == class_room.school_id and user.role in (UserRole.school_admin, UserRole.teacher):
        return True

    # P-SEC-12: الصف مجاني — العضوية كافية
    if _is_class_free(class_room):
        return is_member(class_room, user)

    # P-SEC-13: الصف مدفوع — يجب اشتراك نشط غير منتهي
    return _has_valid_subscription(user.id, class_room.id)


def can_teach_class(class_room, user) -> bool:
    if user.role == UserRole.super_admin:
        return True
    if user.role == UserRole.school_admin:
        return current_school_id() == class_room.school_id
    return class_room.teacher_id == user.id
