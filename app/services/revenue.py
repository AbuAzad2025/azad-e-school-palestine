"""خدمات تتبع إيرادات المنصة — للوحة تحكم السوبر أدمن."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func

from app.extensions import db
from app.models.billing import ManualPayment, Subscription, SubscriptionPlan
from app.models.school import School
from app.models.tutoring import TutorCommission
from app.models.user import UserRole, UserRoleLink


def get_revenue_summary(date_from: datetime | None = None, date_to: datetime | None = None) -> dict:
    """ملخص الإيرادات الكلي."""
    if date_from is None:
        date_from = datetime.now(UTC) - timedelta(days=30)
    if date_to is None:
        date_to = datetime.now(UTC)

    payments = ManualPayment.query.filter(
        ManualPayment.status == "approved",
        ManualPayment.created_at >= date_from,
        ManualPayment.created_at <= date_to,
    ).all()

    total_revenue = sum(float(p.amount) for p in payments)
    transaction_count = len(payments)

    return {
        "total_revenue": round(total_revenue, 2),
        "transaction_count": transaction_count,
        "currency": "ILS",
        "date_from": date_from,
        "date_to": date_to,
    }


def get_revenue_by_gateway(date_from: datetime | None = None, date_to: datetime | None = None) -> list[dict]:
    """الإيرادات مقسمة حسب بوابة الدفع."""
    if date_from is None:
        date_from = datetime.now(UTC) - timedelta(days=30)
    if date_to is None:
        date_to = datetime.now(UTC)

    results = (
        db.session.query(
            ManualPayment.gateway,
            func.count(ManualPayment.id).label("count"),
            func.sum(ManualPayment.amount).label("total"),
        )
        .filter(
            ManualPayment.status == "approved",
            ManualPayment.created_at >= date_from,
            ManualPayment.created_at <= date_to,
            ManualPayment.gateway.isnot(None),
        )
        .group_by(ManualPayment.gateway)
        .all()
    )

    return [
        {
            "gateway": r.gateway or "unknown",
            "count": r.count,
            "total": round(float(r.total or 0), 2),
        }
        for r in results
    ]


def get_revenue_by_school(
    date_from: datetime | None = None, date_to: datetime | None = None, limit: int = 10
) -> list[dict]:
    """الإيرادات مقسمة حسب المدرسة (أعلى 10 مدارس)."""
    if date_from is None:
        date_from = datetime.now(UTC) - timedelta(days=30)
    if date_to is None:
        date_to = datetime.now(UTC)

    results = (
        db.session.query(
            School.id.label("school_id"),
            School.name_ar.label("school_name"),
            func.count(ManualPayment.id).label("count"),
            func.sum(ManualPayment.amount).label("total"),
        )
        .join(Subscription, ManualPayment.subscription_id == Subscription.id)
        .join(SubscriptionPlan, Subscription.plan_id == SubscriptionPlan.id)
        .join(School, SubscriptionPlan.school_id == School.id)
        .filter(
            ManualPayment.status == "approved",
            ManualPayment.created_at >= date_from,
            ManualPayment.created_at <= date_to,
        )
        .group_by(School.id, School.name_ar)
        .order_by(func.sum(ManualPayment.amount).desc())
        .limit(limit)
        .all()
    )

    return [
        {
            "school_id": r.school_id,
            "school_name": r.school_name,
            "count": r.count,
            "total": round(float(r.total or 0), 2),
        }
        for r in results
    ]


def get_monthly_revenue_trend(months: int = 12) -> list[dict]:
    """اتجاه الإيرادات شهرياً (آخر N أشهر)."""
    end_date = datetime.now(UTC)
    start_date = end_date - timedelta(days=months * 30)

    results = (
        db.session.query(
            func.date_trunc("month", ManualPayment.created_at).label("month"),
            func.count(ManualPayment.id).label("count"),
            func.sum(ManualPayment.amount).label("total"),
        )
        .filter(
            ManualPayment.status == "approved",
            ManualPayment.created_at >= start_date,
            ManualPayment.created_at <= end_date,
        )
        .group_by(func.date_trunc("month", ManualPayment.created_at))
        .order_by(func.date_trunc("month", ManualPayment.created_at))
        .all()
    )

    return [
        {
            "month": r.month.strftime("%Y-%m") if r.month else "unknown",
            "count": r.count,
            "total": round(float(r.total or 0), 2),
        }
        for r in results
    ]


def get_growth_rate(date_from: datetime | None = None, date_to: datetime | None = None) -> float:
    """معدل النمو الشهري (مقارنة بالشهر السابق)."""
    if date_from is None:
        date_from = datetime.now(UTC) - timedelta(days=60)
    if date_to is None:
        date_to = datetime.now(UTC)

    mid_point = date_from + (date_to - date_from) / 2

    current_period = (
        db.session.query(func.sum(ManualPayment.amount))
        .filter(
            ManualPayment.status == "approved",
            ManualPayment.created_at >= mid_point,
            ManualPayment.created_at <= date_to,
        )
        .scalar()
        or 0
    )

    previous_period = (
        db.session.query(func.sum(ManualPayment.amount))
        .filter(
            ManualPayment.status == "approved",
            ManualPayment.created_at >= date_from,
            ManualPayment.created_at < mid_point,
        )
        .scalar()
        or 0
    )

    if previous_period == 0:
        return 0.0

    growth = ((float(current_period) - float(previous_period)) / float(previous_period)) * 100
    return round(growth, 2)


# ════════════════════════════════════════════════════════════════════
# عمولة الدروس الخصوصية (AZ-P1-06)
# ════════════════════════════════════════════════════════════════════
# القيود تُكتب فعلاً عند إتمام كل جلسة (app/services/tutoring.py —
# ``_append_commission_ledger``) وكانت بلا أي واجهة تقرأها: المالك لا يرى
# إيراد المنصة من العمولة رغم أنه مُسجَّل في الدفتر.
#
# الإسناد إلى مدرسة: سوق الدروس الخصوصية خارج عزل المدارس عمداً
# (app/models/tutoring.py: بلا school_id، والحاجز هو المنصة). فقيد العمولة لا
# يحمل مدرسة بنفسه، والتجميع «لكل مدرسة» هنا **إسناد** لا ملكية: تُنسب عمولة
# المعلّم إلى مدرسته عبر رابطه النشط بدور ``teacher``. حين يكون للمعلّم أكثر
# من رابط واحد يُختار أصغر معرّف (``min``) — اختيار حتمي يمنع احتساب القيد
# مرتين، ولا يغيّر المجموع الكلي. والمجاميع لا تعتمد على هذا الإسناد أبداً،
# فقيد معلّم بلا رابط مدرسي يظهر في الإجمالي ولا يختفي من التقرير.


def _commission_school_links():
    """مدرسة كل معلّم (رابط نشط بدور teacher) — مدرسة واحدة لكل معلّم."""
    return (
        db.session.query(
            UserRoleLink.user_id.label("user_id"),
            func.min(UserRoleLink.school_id).label("school_id"),
        )
        .filter(UserRoleLink.role == UserRole.teacher, UserRoleLink.is_active.is_(True))
        .group_by(UserRoleLink.user_id)
        .subquery()
    )


def _commission_scope(date_from: datetime | None, date_to: datetime | None):
    """نافذة زمنية موحّدة + فلتر النطاق (مدرسة واحدة عند تمريرها)."""
    if date_from is None:
        date_from = datetime.now(UTC) - timedelta(days=30)
    if date_to is None:
        date_to = datetime.now(UTC)
    return date_from, date_to


def get_commission_summary(
    date_from: datetime | None = None, date_to: datetime | None = None, school_id: int | None = None
) -> dict:
    """إجمالي عمولة المنصة من الدروس الخصوصية في النافذة الزمنية.

    ``school_id`` يقصر النتيجة على عمولات معلّمي مدرسة واحدة — يستخدمه أي
    سياق مدرسي، فلا يُعاد إليه مجموع مدارس أخرى.
    """
    from app.services.tutoring import COMMISSION_RATE

    date_from, date_to = _commission_scope(date_from, date_to)

    query = db.session.query(
        # الاسم `total_count` لا `count`: `count` يحجب دالة Query.count()
        # على صفوف Row فيصرخ mypy (truthy-function) بلا سبب حقيقي.
        func.count(TutorCommission.id).label("total_count"),
        func.sum(TutorCommission.commission_amount).label("total"),
        func.sum(TutorCommission.session_amount).label("session_total"),
        func.count(TutorCommission.id).filter(TutorCommission.status == "pending").label("pending_count"),
        func.sum(TutorCommission.commission_amount).filter(TutorCommission.status == "pending").label("pending_total"),
    ).filter(TutorCommission.created_at >= date_from, TutorCommission.created_at <= date_to)

    if school_id is not None:
        links = _commission_school_links()
        query = query.join(links, links.c.user_id == TutorCommission.tutor_id).filter(links.c.school_id == school_id)

    row = query.one()

    return {
        "total_commission": round(float(row.total or 0), 2),
        "session_total": round(float(row.session_total or 0), 2),
        "transaction_count": row.total_count or 0,
        "pending_commission": round(float(row.pending_total or 0), 2),
        "pending_count": row.pending_count or 0,
        # نسبة المنصة تأتي من مكانها الواحد في طبقة الدروس الخصوصية، وفي
        # استيراد مؤجّل حتى لا يربط وحدة الإيرادات بدورة استيراد الدروس.
        "commission_rate": COMMISSION_RATE,
        "currency": "ILS",
        "date_from": date_from,
        "date_to": date_to,
        "school_id": school_id,
    }


def get_commission_by_school(
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = 10,
    school_id: int | None = None,
) -> list[dict]:
    """العمولة موزّعة على المدارس (إسناد المعلّم إلى مدرسته)."""
    date_from, date_to = _commission_scope(date_from, date_to)
    links = _commission_school_links()

    query = (
        db.session.query(
            School.id.label("school_id"),
            School.name_ar.label("school_name"),
            func.count(TutorCommission.id).label("count"),
            func.sum(TutorCommission.commission_amount).label("total"),
        )
        .join(links, links.c.user_id == TutorCommission.tutor_id)
        .join(School, School.id == links.c.school_id)
        .filter(TutorCommission.created_at >= date_from, TutorCommission.created_at <= date_to)
        .group_by(School.id, School.name_ar)
    )

    # فلتر النطاق قبل limit — SQLAlchemy يرفض filter() بعد limit().
    if school_id is not None:
        query = query.filter(links.c.school_id == school_id)

    query = query.order_by(func.sum(TutorCommission.commission_amount).desc()).limit(limit)

    return [
        {
            "school_id": r.school_id,
            "school_name": r.school_name,
            "count": r.count,
            "total": round(float(r.total or 0), 2),
        }
        for r in query.all()
    ]


def get_commission_monthly_trend(months: int = 12, school_id: int | None = None) -> list[dict]:
    """اتجاه العمولة شهرياً — الصفر يظهر صراحة كصف صفري لا كفراغ."""
    end_date = datetime.now(UTC)
    start_date = end_date - timedelta(days=months * 30)

    query = (
        db.session.query(
            func.date_trunc("month", TutorCommission.created_at).label("month"),
            func.count(TutorCommission.id).label("count"),
            func.sum(TutorCommission.commission_amount).label("total"),
        )
        .filter(TutorCommission.created_at >= start_date, TutorCommission.created_at <= end_date)
        .group_by(func.date_trunc("month", TutorCommission.created_at))
        .order_by(func.date_trunc("month", TutorCommission.created_at))
    )

    if school_id is not None:
        links = _commission_school_links()
        query = query.join(links, links.c.user_id == TutorCommission.tutor_id).filter(links.c.school_id == school_id)

    return [
        {
            "month": r.month.strftime("%Y-%m") if r.month else "unknown",
            "count": r.count,
            "total": round(float(r.total or 0), 2),
        }
        for r in query.all()
    ]


def get_revenue_dashboard_data(days: int = 30, school_id: int | None = None) -> dict:
    """بيانات كاملة للوحة تحكم الإيرادات.

    ``school_id`` اختياري: بلا تمرير يرى أدمن المنصة كل شيء، ومع تمريره يُقصر
    تقرير العمولة على مدرسة واحدة (لا شيء غير العمولة يُقصر، لأن اشتراكات
    الطلاب ومعاملاتها تُقرأ أصلاً من نطاق المدرسة في لوحة أدمن المدرسة).
    """
    date_to = datetime.now(UTC)
    date_from = date_to - timedelta(days=days)

    return {
        "summary": get_revenue_summary(date_from, date_to),
        "by_gateway": get_revenue_by_gateway(date_from, date_to),
        "by_school": get_revenue_by_school(date_from, date_to),
        "monthly_trend": get_monthly_revenue_trend(12),
        "growth_rate": get_growth_rate(date_from, date_to),
        "commission": {
            "summary": get_commission_summary(date_from, date_to, school_id=school_id),
            "by_school": get_commission_by_school(date_from, date_to, school_id=school_id),
            "monthly_trend": get_commission_monthly_trend(12, school_id=school_id),
        },
        "date_from": date_from,
        "date_to": date_to,
    }
