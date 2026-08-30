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


# ═══════════════════════════════════════════════════════════════════════════
# Composite Guards — Security Decoders for Common Patterns
# Each guard bundles @login_required + specific authorization logic.
# ═══════════════════════════════════════════════════════════════════════════


def class_access_required(fn):
    """@login_required + can_view_class(class_room, current_user).

    Expects the route to accept a ``class_id`` keyword argument.
    Fetches the ClassRoom and passes it as ``class_room`` kwarg.
    """
    from flask import request as _req
    from flask_login import login_required

    @login_required
    @wraps(fn)
    def wrapper(*args, **kwargs):
        from app.models.class_room import ClassRoom
        from app.services.access import can_view_class

        class_id = kwargs.get("class_id") or _req.view_args.get("class_id")
        if class_id is None:
            abort(400)
        class_room = ClassRoom.query.filter_by(id=class_id, deleted_at=None).first()
        if class_room is None:
            abort(404)
        if not can_view_class(class_room, current_user):
            abort(403)
        kwargs["class_room"] = class_room
        return fn(*args, **kwargs)

    return wrapper


def class_teach_required(fn):
    """@login_required + can_teach_class(class_room, current_user).

    Expects the route to accept a ``class_id`` keyword argument.
    """
    from flask import request as _req
    from flask_login import login_required

    @login_required
    @wraps(fn)
    def wrapper(*args, **kwargs):
        from app.models.class_room import ClassRoom
        from app.services.access import can_teach_class

        class_id = kwargs.get("class_id") or _req.view_args.get("class_id")
        if class_id is None:
            abort(400)
        class_room = ClassRoom.query.filter_by(id=class_id, deleted_at=None).first()
        if class_room is None:
            abort(404)
        if not can_teach_class(class_room, current_user):
            abort(403)
        kwargs["class_room"] = class_room
        return fn(*args, **kwargs)

    return wrapper


def parent_of_required(fn):
    """@role_required(parent) + is_parent_of(current_user, student_id).

    Expects the route to accept a ``student_id`` keyword argument.
    """
    from flask import request as _req

    @role_required(UserRole.parent)
    @wraps(fn)
    def wrapper(*args, **kwargs):
        from app.services.family import is_parent_of

        student_id = kwargs.get("student_id") or _req.view_args.get("student_id")
        if student_id is None:
            abort(400)
        if not is_parent_of(current_user.id, student_id):
            abort(403)
        return fn(*args, **kwargs)

    return wrapper


def student_only(fn):
    """@login_required + student role only."""
    from flask_login import login_required

    @login_required
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if current_user.role != UserRole.student:
            abort(403)
        return fn(*args, **kwargs)

    return wrapper
