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
    """مدرسة المستخدم الحالي (أول دور فعّال له) أو None للمشرف الكلي."""
    if not current_user.is_authenticated:
        return None
    if current_user.role == UserRole.super_admin:
        return None  # super_admin فوق التينانتس
    return current_user.school_id


def _set_active_class_ids() -> None:
    """Publish the actor's active classes for the hybrid-tenancy RLS arm.

    An individual subscriber holds no role link to the school that owns the
    class they paid for, so ``app.current_school_id`` alone hides it. The class
    ids they *are* enrolled in are what the content-graph policies need.

    Read from ``class_members`` before the school variable is set, which is
    safe and not circular precisely because that policy carries a
    ``user_id`` arm: the rows are visible as the actor's own, never as
    the tenant's.
    """
    from sqlalchemy import text

    from app.core.rls import _CLASS_IDS_GUC
    from app.extensions import db

    # المُعرِّف فقط يُقحم في السلسلة — ثابت من app/core/rls.py وليس مدخلات مستخدم.
    db.session.execute(
        text(
            f"""
            SELECT set_config('{_CLASS_IDS_GUC}', COALESCE(string_agg(class_id::text, ','), ''), true)
            FROM class_members
            WHERE user_id::text = current_setting('app.current_user_id', true)
              AND status = 'active'
            """  # nosec B608
        ),
    )


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


def _snapshot_request_gucs() -> None:
    """لقطة سياق الطلب في flask.g — تُكتب قبل ضبط الـGUCs لا بعدها.

    مستمع `after_begin` يعيد تثبيت السياق في بداية كل معاملة، بما فيه
    معاملة `set_config` نفسها، فأي لقطة تُكتب بعده فخاية: معاملة الضبط
    تشتغل بقيم طلب سابق (فارغة في طلب أول) ثم تُستبدل اللقطة بعد رفعها.

    شرط الاستدعاء: ``app.current_user_id`` مضبوط *قبل* هذه الدالة في
    المستخدم المصادَق — القراءات هنا كسولة (`current_user.school_id`
    يستنتج من user_role_links باستعلام حقيقي)، وهي أول معاملة يفتحها
    الطلب فستقيّم سياساتها بسياق الممثل إن ضُبط uid قبلها، وبقيم فارغة
    (تعيد لا شيء) إن لم يُضبط. تُستدعى دائماً بعد ضبط uid — انظر
    set_tenant_for_request.
    """
    from flask import g

    try:
        authenticated = current_user.is_authenticated
        if authenticated and current_user.role == UserRole.super_admin:
            snapshot = {
                "app.current_user_id": str(current_user.id),
                "app.current_class_ids": "",
                "app.is_individual": "0",
                "app.current_school_id": "0",
                "app.is_super_admin": "1",
            }
        elif authenticated:
            snapshot = {
                "app.current_user_id": str(current_user.id),
                "app.current_class_ids": "",  # يُحدثها after_begin ليقرأها class_members
                "app.is_individual": "1" if current_user.is_individual else "0",
                "app.current_school_id": str(current_user.school_id or 0),
                "app.is_super_admin": "0",
            }
        else:
            snapshot = {
                "app.current_user_id": "0",
                "app.current_class_ids": "",
                "app.is_individual": "0",
                "app.current_school_id": "0",
                "app.is_super_admin": "0",
            }
        g._rls_request_gucs = snapshot
    except Exception:
        # لا لقطة = after_begin لا يلمس المعاملة — المضبط يدوياً يحمل مسؤوليته.
        pass


def set_tenant_for_request() -> None:
    """Set PostgreSQL session variable for RLS at the start of each request.

    Called from app.before_request. Sets app.current_user_id,
    app.current_class_ids, app.is_individual, app.current_school_id and
    app.is_super_admin so that RLS policies can evaluate them.
    Uses SET LOCAL so variables auto-reset on transaction end.

    ``app.current_user_id`` exists for one reason: ``user_role_links`` is the
    table that *derives* the user's school, so a school-scoped policy on it
    would be circular (the query that resolves the tenant would be filtered by
    the tenant it is resolving). Its policy is therefore user-scoped, and the
    anonymous case sets ``'0'`` rather than leaving the variable unset — an
    unset custom GUC reads back as ``''``, which is not a valid bigint.
    """
    from sqlalchemy import text

    from app.extensions import db

    try:
        # uid أولاً في المستخدم المصادَق: القراءات الكسولة التي تليه
        # (`current_user.school_id` من user_role_links) هي ما يفتح معاملة
        # الطلب، وسياساتها بذراع user_id — بلا المعرف تعيد لا شيء وتُلقط
        # school_id=None في لقطة الطلب كلّه، فيُخفى الصف عن صاحبه (403). أخزّن
        # uid الآن، واللقطة تُؤخذ بعده فتعمل الاستعلامات الكسولة بسياقه.
        authenticated = current_user.is_authenticated
        if authenticated:
            uid = str(current_user.id)
        else:
            uid = "0"
        # uid أولاً في المستخدم المصادَق: القراءات الكسولة (``current_user.school_id``
        # من user_role_links) هي التي تفتح معاملة الطلب، وسياساتها بذراع user_id
        # تعيد لا شيء إذا لم تكن التعريفات السابقة جاهزة — فيُخفى الصف عن صاحبه
        # (403). نضع uid الآن، واللقطة تلتفت لما بعد، فتعمل الاستعلامات بسياقه.
        db.session.execute(
            text("SELECT set_config('app.current_user_id', :uid, true)"),
            {"uid": uid},
        )
        # اللقطة بعد ضبط uid: القيم التي يقرؤها after_begin لكل معاملة لاحقة.
        # `current_class_ids` هنا فارغ عمداً مازال، ويُملأ بعد الضبط في الفرع
        # غير المشرف (hy rid ten ant)؛ الشرف يتجاهل الفارغ — ويرث المالك/الطالب
        # من سياقه بواسطة school_id/SUPER_ADMIN.
        _snapshot_request_gucs()
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
            # class_members تُقرأ قبل تضييق التينانتس — سياساتها بذراع user_id
            # فترى الممثل صفوفه هو فقط، لا صفوف المدرسة كلها.
            _set_active_class_ids()
            class_ids = _read_class_ids_guc()
            _set_gucs_one_statement(
                uid=uid,
                class_ids=class_ids,
                is_individual="1" if current_user.is_individual else "0",
                school_id=str(current_user.school_id or 0),
                is_super_admin="0",
            )
            # اللقطة النهائية بالقيم الحقيقية — بعد الضبط تماماً، قبل أي
            # معاملة لاحقة للطلب، ولا استعلام إضافي هنا.
            from flask import g as _g

            _g._rls_request_gucs = {
                "app.current_user_id": uid,
                "app.current_class_ids": class_ids,
                "app.is_individual": "1" if current_user.is_individual else "0",
                "app.current_school_id": str(current_user.school_id or 0),
                "app.is_super_admin": "0",
            }
    except Exception:
        # Non-critical: if SET LOCAL fails (e.g., no active transaction yet),
        # RLS is still enforced at the DB level but without session context.
        # scope_by_school() in Python is the primary guard.
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
