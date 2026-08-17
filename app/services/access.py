"""فحوص وصول مشتركة بين الوحدات — نقطة واحدة لا تكرار."""

from app.core.tenancy import current_school_id
from app.models.user import UserRole
from app.services.schools import is_member


def can_view_class(class_room, user) -> bool:
    """عرض الصف/محتواه: أعضاء + معلم/مشرف مدرسته + super_admin."""
    if user.role == UserRole.super_admin:
        return True
    if current_school_id() == class_room.school_id and user.role in (UserRole.school_admin, UserRole.teacher):
        return True
    return is_member(class_room, user)


def can_teach_class(class_room, user) -> bool:
    """إدارة صف: معلم الصف + مشرف مدرسته + super_admin."""
    if user.role == UserRole.super_admin:
        return True
    if user.role == UserRole.school_admin:
        return current_school_id() == class_room.school_id
    return class_room.teacher_id == user.id
