"""الصلاحيات — نقطة مركزية واحدة لكل فحوصات RBAC (D6: لا فحص متفرق).

كل route يستدعي decorator من هنا؛ لا يُكتب منطق صلاحيات في أماكن متعددة.
"""

from functools import wraps

from flask import abort
from flask_login import current_user

from app.models.user import UserRole

SUPER_ROLE = UserRole.super_admin


def _has_any(*roles: UserRole) -> bool:
    if not current_user.is_authenticated:
        return False
    return current_user.role in roles or current_user.role == SUPER_ROLE


def role_required(*roles: UserRole):
    """يسمح للأدوار المحددة + super_admin دائماً. غير مسجّل = 401، غير مخوّل = 403."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                abort(401)
            if not _has_any(*roles):
                abort(403)
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def any_role(*roles: UserRole):
    """مثل role_required لكن يرجع bool — للاستخدام داخل القوالب/logic."""
    return _has_any(*roles)
