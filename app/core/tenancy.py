"""التينانتس (SaaS) — عزل بيانات المدارس من نقطة مركزية واحدة.

المدارس لا ترى بيانات بعضها. كل استعلام أعمال يمر عبر:
  tenant_scope(model, school_id, extra_filters)
ويُمنع الوصول عبر المدارس بقيد صريح في كل مرة.
"""

from dataclasses import dataclass

from flask import abort
from flask_login import current_user

from app.models.school import School
from app.models.user import UserRole


@dataclass(frozen=True)
class TenantContext:
    school_id: int
    role: str


def current_school_id() -> int | None:
    """مدرسة المستخدم الحالي (أول دور فعّال له) أو None للمشرف الكلي."""
    if not current_user.is_authenticated:
        return None
    if current_user.role == UserRole.super_admin:
        return None  # super_admin فوق التينانتس
    return current_user.school_id


def get_school_or_404(school_id: int) -> School:
    """يجلب المدرسة مع فحص الوصول (D6: فحص على كل وصول مورد)."""
    if current_school_id() is not None and current_school_id() != school_id:
        abort(403)
    return School.query.filter_by(id=school_id).first_or_404()


def scope_by_school(model, school_id: int, *, filter_key: str = "school_id"):
    """استعلام مقصور على مدرسة واحدة (دالة نقيّة بلا فحص مستخدم)."""
    if not hasattr(model, filter_key):
        raise ValueError(f"النموذج {model.__name__} بلا عمود {filter_key} — لا عزل تينانتس.")
    return model.query.filter(getattr(model, filter_key) == school_id)


def tenant_scope(model, school_id: int, *, filter_key: str = "school_id"):
    """scope_by_school + فحص وصول المستخدم (للـ routes). 403 عند التجاوز."""
    if current_school_id() is not None and current_school_id() != school_id:
        abort(403)
    return scope_by_school(model, school_id, filter_key=filter_key)
