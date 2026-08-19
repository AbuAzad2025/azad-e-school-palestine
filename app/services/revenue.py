"""خدمات تتبع إيرادات المنصة — للوحة تحكم السوبر أدمن."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func

from app.extensions import db
from app.models.billing import ManualPayment, Subscription, SubscriptionPlan
from app.models.school import School


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


def get_revenue_dashboard_data(days: int = 30) -> dict:
    """بيانات كاملة للوحة تحكم الإيرادات."""
    date_to = datetime.now(UTC)
    date_from = date_to - timedelta(days=days)

    return {
        "summary": get_revenue_summary(date_from, date_to),
        "by_gateway": get_revenue_by_gateway(date_from, date_to),
        "by_school": get_revenue_by_school(date_from, date_to),
        "monthly_trend": get_monthly_revenue_trend(12),
        "growth_rate": get_growth_rate(date_from, date_to),
        "date_from": date_from,
        "date_to": date_to,
    }
