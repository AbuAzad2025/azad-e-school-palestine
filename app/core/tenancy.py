"""التينانتس (SaaS) — عزل بيانات المدارس من نقطة مركزية واحدة.

المدارس لا ترى بيانات بعضها. كل استعلام أعمال يمر عبر:
  tenant_scope(model, school_id, extra_filters)
ويُمنع الوصول عبر المدارس بقيد صريح في كل مرة.

P3-02: Each request sets PostgreSQL session variables for RLS enforcement.
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
    """مدرسة المستخدم الحالي (أول دور فعّال له) أو None للمشرف الكلي.

    تقرأ من GUC ``app.current_school_id`` أولاً (مُضبوط في
    ``set_tenant_for_request``) لتجنب الاستعلام الكسولي على
    ``user_role_links`` كلما أمكن. نعيد ``None`` إن كان المشرف

    الكلي أو إن لم تكن للمستخدم علاقة دور فعّالة.
    """
    from sqlalchemy import text

    from app.core.rls import _SCHOOL_ID_GUC
    from app.extensions import db

    try:
        if not getattr(current_user, "is_authenticated", False):
            return None
        if getattr(current_user, "role", None) == UserRole.super_admin:
            return None  # super_admin فوق التينانتس
        # قراءة من GUC أولاً — هذه القيمة مُضبوطة في set_tenant_for_request
        # ولا تحتاج إلى استعلام قاعدة إضافي
        raw = db.session.execute(text(f"SELECT current_setting('{_SCHOOL_ID_GUC}', true)")).scalar()
        val = int(raw) if raw and raw != "0" else None
        if val:
            return val
        # نزول إلى استعلام relationship كحالة أخيرة
        return getattr(current_user, "school_id", None)
    except Exception:
        return None


def _set_active_class_ids(*, user_id: int | None = None) -> str:
    """نشر معرّفات الصفوف النشطة للممثلarm الـRLS الهجين.

    المشترك الفردي لا يملك علاقة دور إلى مدرسة الصف الذي دفعه، لذلك

    ``app.current_school_id`` لوحده يخبئه. معرّفات الصفوف التي *يدخل*ها

    هي ما تحتاجه سياسات الرسم البياني للمحتوى.

    تُقرأ من ``class_members`` قبل ضبط متغير المدرسة، وهو آمن وغير دائري

    لأن السياسة تحمل arm ``user_id``: الصفوف المرئية هي صفوف الممثل نفسه،

    لا صفوف المدرسة كلها.

    인수 ``user_id`` يُعطى صراحةً لتجنب إعادة قراءة GUC ``app.current_user_id``

    داخل جملة SARGable — استخدام العمود الصحيح ``user_id = :uid`` أسرع من

    ``user_id::text = current_setting(...)`` ويتجنب مشاكل التطابق النصي.
    """
    from sqlalchemy import text

    from app.core.rls import _CLASS_IDS_GUC
    from app.extensions import db

    uid = user_id if user_id is not None else current_user.id
    result = db.session.execute(
        text(
            f"""
            SELECT set_config('{_CLASS_IDS_GUC}',
                   COALESCE(string_agg(class_id::text, ','), ''), true)
            FROM class_members
            WHERE user_id = :uid AND status = 'active'
            """  # nosec B608 — اسم GUC ثابت من rls.py، :uid مُربَط
        ),
        {"uid": uid},
    )
    return str(result.scalar() or "")


def _read_class_ids_guc() -> str:
    """اقرأ قيمة GUC المعرّفات المُفعّلة التي ضبطها _set_active_class_ids."""
    from sqlalchemy import text

    from app.core.rls import _CLASS_IDS_GUC
    from app.extensions import db

    # اسم GUC ثابت من rls.py — لا مدخلات مستخدم في التداخل.
    raw = db.session.execute(
        text(f"SELECT current_setting('{_CLASS_IDS_GUC}', true)")  # nosec B608
    ).scalar()
    return str(raw or "")


def _set_gucs_one_statement(
    *,
    uid: str,
    class_ids: str,
    is_individual: str,
    school_id: str,
    is_super_admin: str,
) -> None:
    """اجمع كل متغيرات RLS في استعلام واحد — كل طلب يدفع استعلامًا لا خمسة.

    ميزانيات الاستعلامات (test_performance / test_query_performance /
    whatsapp) مبنية على عدد الجولات للقاعدة؛ ستة SET LOCAL منفصلة كانت
    تلتهم السقف بعد hybrid tenancy. set_config مع is_local=true مكافئ
    تمامًا لـ SET LOCAL. الترتيب محفوظ: user_id أولًا (user_role_links
    يُشتق منه المدرسة)، والمدرسة آخرًا بعد اشتقاق class_ids.
    """
    from sqlalchemy import text

    from app.core.rls import _CLASS_IDS_GUC, _INDIVIDUAL_GUC
    from app.extensions import db

    db.session.execute(
        text(
            """
            SELECT set_config('app.current_user_id', :uid, true),
                   set_config(:class_ids_guc, :class_ids, true),
                   set_config(:individual_guc, :is_individual, true),
                   set_config('app.current_school_id', :school_id, true),
                   set_config('app.is_super_admin', :is_super_admin, true)
            """  # nosec B608 — أسماء GUCs ثوابت من rls.py، القيم مُربوطة
        ),
        {
            "uid": uid,
            "class_ids_guc": _CLASS_IDS_GUC,
            "class_ids": class_ids,
            "individual_guc": _INDIVIDUAL_GUC,
            "is_individual": is_individual,
            "school_id": school_id,
            "is_super_admin": is_super_admin,
        },
    )


def _snapshot_request_gucs(*, school_id: int | None = None) -> dict[str, str]:
    """لقطة سياق الطلب — قيم GUC التي سيضبطها set_tenant_for_request.

    تُرجع القيم دون كتابتها، وتصاعد الدعوة ``after_begin`` إعادة تثبيت
    السياق في كل معاملة يفتحها الطلب (بما فيها معاملة ``set_config``
    ذاتها). اللقطة تُؤخذ بعد ضبط ``app.current_user_id`` فقط، قبل الضبط
    الكامل، لأن القراءات الكسولة (``current_user.school_id`` من
    user_role_links) هي ما يفتح معاملة الطلب، وسياساتها بذراع user_id
    تعيد لا شيء إن لم يضبَط المعرف قبلاً.

    인수 ``school_id`` يُعطى صراحةً من المُرِِئ، وليس من property
    ``current_user.school_id`` الكسول، لذلك يتجنب استعلامًا隠اً على
    user_role_links قد يفشل في سياقات RLS أو عندما تكون الجلسة
    منتهية الصلاحية.
    """
    if school_id is None and getattr(current_user, "is_authenticated", False) and getattr(current_user, "role", None) != UserRole.super_admin:
        school_id = getattr(current_user, "school_id", None)
    sid_val = str(school_id) if school_id else "0"
    if not getattr(current_user, "is_authenticated", False):
        return {
            "app.current_user_id": "0",
            "app.current_class_ids": "",
            "app.is_individual": "0",
            "app.current_school_id": "0",
            "app.is_super_admin": "0",
        }
    if current_user.role == UserRole.super_admin:
        return {
            "app.current_user_id": str(current_user.id),
            "app.current_class_ids": "",
            "app.is_individual": "0",
            "app.current_school_id": "0",
            "app.is_super_admin": "1",
        }
    return {
        "app.current_user_id": str(current_user.id),
        "app.current_class_ids": "",
        "app.is_individual": "1" if current_user.is_individual else "0",
        "app.current_school_id": sid_val,
        "app.is_super_admin": "0",
    }


def set_tenant_for_request() -> None:
    """Set PostgreSQL session variable for RLS at the start of each request.

    Called from app.before_request. Sets app.current_school_id and
    app.is_super_admin so that RLS policies can evaluate them.
    Uses SET LOCAL so variables auto-reset on transaction end.
    """
    from flask import g as _g
    from sqlalchemy import text

    from app.extensions import db

    try:
        authenticated = current_user.is_authenticated
        uid = str(current_user.id) if authenticated else "0"

        # Step 1: set user id first — lazy reads that follow need it.
        db.session.execute(
            text("SELECT set_config('app.current_user_id', :uid, false)"),
            {"uid": uid},
        )

        # Step 2: snapshot GUC values (for after_begin replay) after uid is set.
        # school_id is passed explicitly from the caller (the view layer resolved
        # it via role_links before this point) to avoid a lazy SELECT on
        # user_role_links inside this function.
        school_id = getattr(current_user, "_cached_school_id", None)
        snap = _snapshot_request_gucs(school_id=school_id)
        _g._rls_request_gucs = snap

        if not authenticated:
            _set_gucs_one_statement(
                uid="0",
                class_ids="",
                is_individual="0",
                school_id="0",
                is_super_admin="0",
            )
        elif current_user.role == UserRole.super_admin:
            _set_gucs_one_statement(
                uid=str(current_user.id),
                class_ids="",
                is_individual="0",
                school_id="0",
                is_super_admin="1",
            )
        else:
            # class_members read before tenant narrowing — its policy has a
            # user_id arm, so it sees only the actor's own rows.
            # Single combined query: set class_ids GUC from class_members AND
            # all other GUCs in one round-trip (saves a query vs. separate
            # _set_active_class_ids + _set_gucs_one_statement calls).
            from sqlalchemy import text as _text

            from app.core.rls import _CLASS_IDS_GUC, _INDIVIDUAL_GUC

            _class_ids_expr = (
                "COALESCE((SELECT string_agg(class_id::text, ',') "
                "FROM class_members WHERE user_id = :uid AND status = 'active'), '')"
            )
            _res = db.session.execute(
                _text(
                    "SELECT set_config('app.current_user_id', :uid, true), "
                    f"set_config(:class_ids_guc, {_class_ids_expr}, true), "
                    "set_config(:individual_guc, :is_individual, true), "
                    "set_config('app.current_school_id', :school_id, true), "
                    "set_config('app.is_super_admin', '0', true)"
                ),
                {
                    "uid": uid,
                    "class_ids_guc": _CLASS_IDS_GUC,
                    "individual_guc": _INDIVIDUAL_GUC,
                    "is_individual": "1" if current_user.is_individual else "0",
                    "school_id": snap["app.current_school_id"],
                },
            ).fetchone()
            class_ids = str(_res[1] or "") if _res else "" 
            # Update snapshot with derived class_ids so after_begin replay keeps them
            snap["app.current_class_ids"] = class_ids
            _g._rls_request_gucs = snap
    except Exception:
        # Non-critical: if SET LOCAL fails (e.g. no transaction yet), RLS is
        # still enforced at the DB level but without session context. The Python
        # guard ``scope_by_school()`` is the primary defence.
        return


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
