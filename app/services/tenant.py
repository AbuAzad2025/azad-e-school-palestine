"""خدمات حدود التينانتس — فحص الحدود قبل إضافة موارد."""

from app.core.db import tx
from app.core.i18n import _
from app.extensions import db
from app.models.class_room import ClassMember, ClassRoom
from app.models.tenant import TenantQuota
from app.models.user import User, UserRole

TIER_DEFAULTS = {
    "free": {
        "max_students": 50,
        "max_teachers": 10,
        "max_classes": 20,
        "max_storage_mb": 1024,
        "ai_enabled": False,
        "max_ai_tokens_monthly": 0,
    },
    "basic": {
        "max_students": 200,
        "max_teachers": 50,
        "max_classes": 100,
        "max_storage_mb": 5120,
        "ai_enabled": False,
        "max_ai_tokens_monthly": 0,
    },
    "pro": {
        "max_students": 500,
        "max_teachers": 100,
        "max_classes": 300,
        "max_storage_mb": 20480,
        "ai_enabled": True,
        "max_ai_tokens_monthly": 100000,
    },
    "enterprise": {
        "max_students": 999999,
        "max_teachers": 999999,
        "max_classes": 999999,
        "max_storage_mb": 999999,
        "ai_enabled": True,
        "max_ai_tokens_monthly": 9999999,
    },
}


def get_quota(school_id: int) -> TenantQuota:
    """يجلب أو ينشئ حصة افتراضية للمدرسة."""
    quota = TenantQuota.query.filter_by(school_id=school_id).first()
    if not quota:
        defaults = TIER_DEFAULTS["free"]

        def _create():
            return TenantQuota(school_id=school_id, tier="free", **defaults)

        quota = tx(_create)
    return quota


def check_quota(school_id: int, resource: str) -> tuple[bool, str]:
    """يتحقق مما إذا كان بإمكان المدرسة إضافة مورد."""
    quota = get_quota(school_id)

    if resource == "students":
        current = (
            db.session.query(db.func.count(User.id))
            .join(ClassMember, User.id == ClassMember.user_id)
            .join(ClassRoom, ClassMember.class_id == ClassRoom.id)
            .filter(ClassRoom.school_id == school_id, ClassMember.status == "active", User.role == UserRole.student)
            .scalar()
            or 0
        )
        if current >= quota.max_students:
            return False, _("تم الوصول للحد الأقصى للطلاب (%(max)s).", max=quota.max_students)

    elif resource == "teachers":
        current = (
            User.query.join(User.role_links)
            .filter(User.role_links.any(school_id=school_id, role=UserRole.teacher))
            .count()
        )
        if current >= quota.max_teachers:
            return False, _("تم الوصول للحد الأقصى للمعلمين (%(max)s).", max=quota.max_teachers)

    elif resource == "classes":
        current = ClassRoom.query.filter_by(school_id=school_id, deleted_at=None).count()
        if current >= quota.max_classes:
            return False, _("تم الوصول للحد الأقصى للصفوف (%(max)s).", max=quota.max_classes)

    elif resource == "ai":
        if not quota.ai_enabled:
            return False, _("خدمة الذكاء الاصطناعي غير مفعّلة في باقتك.")

    return True, ""


def set_tier(school_id: int, tier: str) -> tuple[TenantQuota | None, str | None]:
    """تحديث باقة المدرسة."""
    if tier not in TIER_DEFAULTS:
        return None, _("الباقة غير صالحة.")

    defaults = TIER_DEFAULTS[tier]
    quota = TenantQuota.query.filter_by(school_id=school_id).first()

    def _update():
        if not quota:
            return TenantQuota(school_id=school_id, tier=tier, **defaults)
        quota.tier = tier
        for key, value in defaults.items():
            setattr(quota, key, value)
        return quota

    return tx(_update), None
