from app.core.tenancy import current_school_id
from app.models.user import UserRole
from app.services.schools import has_active_subscription, is_member


def can_view_class(class_room, user) -> bool:
    if user.role == UserRole.super_admin:
        return True
    if current_school_id() == class_room.school_id and user.role in (UserRole.school_admin, UserRole.teacher):
        return True
    if is_member(class_room, user):
        return True
    if has_active_subscription(user.id, class_room.id):
        return True
    return False


def can_teach_class(class_room, user) -> bool:
    if user.role == UserRole.super_admin:
        return True
    if user.role == UserRole.school_admin:
        return current_school_id() == class_room.school_id
    return class_room.teacher_id == user.id
