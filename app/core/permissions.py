"""الصلاحيات — نقطة مركزية واحدة لكل فحوصات RBAC (D6: لا فحص متفرق).

كل route يستدعي decorator من هنا؛ لا يُكتب منطق صلاحيات في أماكن متعددة.
"""

from functools import wraps

from flask import abort
from flask_login import current_user

from app.core.i18n import _
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

        class_id = kwargs.get("class_id") or (_req.view_args or {}).get("class_id")
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

        class_id = kwargs.get("class_id") or (_req.view_args or {}).get("class_id")
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

        student_id = kwargs.get("student_id") or (_req.view_args or {}).get("student_id")
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


# ═══════════════════════════════════════════════════════════════════════════
# AI Quota Guard — tenant_ai_quota() + require_ai_quota decorator
# يمنع تنفيذ أي طلب AI قبل التحقق من باقة المدرسة (ai_enabled + الحد الشهري).
# ═══════════════════════════════════════════════════════════════════════════


def tenant_ai_quota() -> tuple[bool, str, str]:
    """فحص حصة AI للمدرسة الحالية.

    Sequence:
        1. super_admin بلا مدرسة → مسموح (فوق التينانتس).
        2. بلا مدرسة (فردي/غير منتمٍ) → AI_DISABLED_FOR_TENANT.
        3. tenant_quotas.ai_enabled == False → AI_DISABLED_FOR_TENANT.
        4. استهلاك الشهر الحالي ≥ max_ai_tokens_monthly → AI_QUOTA_EXCEEDED.

    Returns:
        (allowed, sub_code, message) — sub_code "" عندما allowed.
    """
    from app.core.cache import get as cache_get
    from app.core.cache import set as cache_set
    from app.core.tenancy import current_school_id

    if current_user.role == UserRole.super_admin:
        return True, "", ""

    school_id = current_school_id()
    if school_id is None:
        return False, "AI_DISABLED_FOR_TENANT", _("خدمة الذكاء الاصطناعي متاحة للمدارس المسجلة فقط.")

    # الحصة مخزّنة مؤقتاً 30 ثانية لتقليل استعلامات كل طلب AI
    cache_key = f"ai_quota:{school_id}"
    cached = cache_get(cache_key)
    if cached is not None:
        allowed, sub_code = bool(cached["allowed"]), str(cached["sub_code"])
        return allowed, sub_code, ("" if allowed else _("تم استهلاك حصة الذكاء الاصطناعي."))

    from app.services.ai_usage import monthly_tokens_used
    from app.services.tenant import get_quota

    quota = get_quota(school_id)
    if not quota.ai_enabled:
        result = (False, "AI_DISABLED_FOR_TENANT")
    elif monthly_tokens_used(school_id) >= quota.max_ai_tokens_monthly:
        result = (False, "AI_QUOTA_EXCEEDED")
    else:
        result = (True, "")

    cache_set(cache_key, {"allowed": result[0], "sub_code": result[1]}, ttl=30)
    allowed, sub_code = result
    return allowed, sub_code, ("" if allowed else _("تم استهلاك حصة الذكاء الاصطناعي."))


def invalidate_ai_quota_cache(school_id: int) -> None:
    """إبطال كاش الحصة (بعد تغيير الباقة أو الترقية)."""
    from app.core.cache import delete as cache_delete

    cache_delete(f"ai_quota:{school_id}")


def require_ai_quota(fn):
    """@login_required + tenant_ai_quota() gate.

    JSON routes (Accept: application/json or /api/ path) get a structured
    error body with sub-code; web routes abort with 403.
    """
    from flask import jsonify, request
    from flask_login import login_required

    @login_required
    @wraps(fn)
    def wrapper(*args, **kwargs):
        allowed, sub_code, message = tenant_ai_quota()
        if allowed:
            return fn(*args, **kwargs)
        wants_json = (
            request.path.startswith("/api/")
            or request.is_json
            or request.accept_mimetypes.best == "application/json"
        )
        if wants_json:
            resp = jsonify({"error": {"message": message, "code": sub_code}})
            resp.status_code = 403
            return resp
        abort(403, description=message)

    return wrapper
