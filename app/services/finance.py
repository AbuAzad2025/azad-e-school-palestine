"""السجل المالي — ملخص الإيرادات والرصيد لكل مدرسة/طالب."""

from decimal import Decimal

from sqlalchemy import func

from app.extensions import db
from app.models.billing import ManualPayment, Subscription, SubscriptionPlan


def school_revenue_summary(school_id: int) -> dict:
    """ملخص إيرادات المدرسة."""
    subs = (
        Subscription.query.join(SubscriptionPlan, Subscription.plan_id == SubscriptionPlan.id)
        .filter(SubscriptionPlan.school_id == school_id)
        .all()
    )
    sub_ids = [s.id for s in subs]

    if not sub_ids:
        return {
            "total_revenue": Decimal("0"),
            "pending_amount": Decimal("0"),
            "overdue_count": 0,
            "active_count": 0,
        }

    active_count = sum(1 for s in subs if s.status == "active")
    overdue_count = sum(1 for s in subs if s.status == "expired")

    total_collected = db.session.query(func.sum(ManualPayment.amount)).filter(
        ManualPayment.subscription_id.in_(sub_ids),
        ManualPayment.status == "approved",
    ).scalar() or Decimal("0")

    total_pending = db.session.query(func.sum(ManualPayment.amount)).filter(
        ManualPayment.subscription_id.in_(sub_ids),
        ManualPayment.status == "pending",
    ).scalar() or Decimal("0")

    return {
        "total_revenue": total_collected,
        "pending_amount": total_pending,
        "overdue_count": overdue_count,
        "active_count": active_count,
    }


def student_balance(student_id: int, class_id: int) -> dict:
    """رصيد الطالب في صف معين."""
    sub = Subscription.query.filter_by(user_id=student_id, class_id=class_id).first()
    if not sub:
        return {"has_subscription": False, "balance": 0, "total_paid": 0, "total_price": 0}

    paid = db.session.query(func.sum(ManualPayment.amount)).filter(
        ManualPayment.subscription_id == sub.id,
        ManualPayment.status == "approved",
    ).scalar() or Decimal("0")

    return {
        "has_subscription": True,
        "subscription_status": sub.status,
        "total_price": float(sub.price),
        "total_paid": float(paid),
        "balance": float(sub.price) - float(paid),
    }


def accounts_receivable(school_id: int) -> list[dict]:
    """جميع الأرصدة المستحقة في المدرسة."""
    subs = Subscription.query.filter(
        Subscription.school_id == school_id,
        Subscription.status.in_(["pending", "active"]),
    ).all()

    results = []
    for sub in subs:
        paid = db.session.query(func.sum(ManualPayment.amount)).filter(
            ManualPayment.subscription_id == sub.id,
            ManualPayment.status == "approved",
        ).scalar() or Decimal("0")
        balance = float(sub.price) - float(paid)
        if balance > 0:
            results.append(
                {
                    "student_id": sub.user_id,
                    "student": sub.user,
                    "subscription_id": sub.id,
                    "total_price": float(sub.price),
                    "total_paid": float(paid),
                    "balance": balance,
                    "status": sub.status,
                }
            )
    results.sort(key=lambda x: x["balance"], reverse=True)
    return results
