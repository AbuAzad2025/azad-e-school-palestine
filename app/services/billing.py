"""خدمات الاشتراك والدفع اليدوي (D12 — لا بوابات؛ اعتماد بشري)."""

from datetime import UTC, datetime, timedelta

from app.core.db import TxError, tx
from app.core.uploads import save_upload
from app.extensions import db
from app.models.billing import ManualPayment, PaymentReceipt, Subscription, SubscriptionPlan


def create_plan(
    school_id: int,
    name: str,
    plan: str,
    price: float,
    class_id: int | None = None,
    currency: str = "ILS",
    duration_days: int | None = None,
    benefits: dict | None = None,
) -> tuple[SubscriptionPlan | None, str | None]:
    name = (name or "").strip()
    if not name or price is None:
        return None, "الاسم والسعر مطلوبان."
    if plan not in ("first_term", "second_term", "annual"):
        return None, "نوع خطة غير صالح."

    def _create():
        return SubscriptionPlan(
            school_id=school_id,
            class_id=class_id,
            name=name,
            plan=plan,
            price=price,
            currency=currency,
            duration_days=duration_days,
            benefits=benefits,
        )

    return tx(_create), None


def list_plans(class_id: int | None = None):
    query = SubscriptionPlan.query.filter_by(is_active=True)
    if class_id:
        query = query.filter((SubscriptionPlan.class_id == class_id) | (SubscriptionPlan.class_id.is_(None)))
    return query.order_by(SubscriptionPlan.price.asc()).all()


def get_plan(plan_id: int) -> SubscriptionPlan | None:
    return db.session.get(SubscriptionPlan, plan_id)


def subscribe(user_id: int, plan: SubscriptionPlan, class_id: int) -> tuple[Subscription | None, str | None]:
    """يبدأ اشتراكاً بحالة pending — لا يُفعَّل إلا بعد اعتماد دفع يدوي."""
    active = Subscription.query.filter_by(user_id=user_id, class_id=class_id, status="active").first()
    if active:
        return None, "لديك اشتراك نشط في هذا الصف."

    def _create():
        return Subscription(
            user_id=user_id,
            plan_id=plan.id,
            class_id=class_id,
            price=plan.price,
            currency=plan.currency,
            status="pending",
            source="manual",
        )

    return tx(_create), None


def list_subscriptions(user_id: int | None = None, class_id: int | None = None, status: str | None = None):
    query = Subscription.query
    if user_id:
        query = query.filter_by(user_id=user_id)
    if class_id:
        query = query.filter_by(class_id=class_id)
    if status:
        query = query.filter_by(status=status)
    return query.order_by(Subscription.created_at.desc()).all()


def record_manual_payment(
    subscription: Subscription, reference: str, amount: float, note: str | None = None, receipt_file=None
) -> tuple[ManualPayment | None, str | None]:
    reference = (reference or "").strip()
    if not reference or amount is None or amount <= 0:
        return None, "المرجع والمبلغ مطلوبان."

    stored = None
    original = None
    mime = None
    size = None
    if receipt_file:
        try:
            stored = save_upload(receipt_file, subfolder="receipts")
            original = receipt_file.filename
            mime = receipt_file.mimetype
            size = receipt_file.content_length or 0
        except TxError as exc:
            return None, str(exc)

    def _record():
        payment = ManualPayment(
            subscription_id=subscription.id,
            reference=reference,
            amount=amount,
            note=note,
        )
        db.session.add(payment)
        if stored:
            db.session.add(
                PaymentReceipt(
                    manual_payment_id=payment.id,
                    stored_name=stored,
                    original_name=original,
                    mime=mime,
                    size_bytes=size,
                )
            )
        return payment

    return tx(_record), None


def _activate(subscription: Subscription, duration_days: int | None = None) -> None:
    days = duration_days or subscription.plan.duration_days or 180
    now = datetime.now(UTC)
    subscription.start_at = now
    subscription.end_at = now + timedelta(days=days)
    subscription.status = "active"


def approve_payment(payment: ManualPayment, reviewer_id: int | None = None) -> Subscription:
    """اعتماد الدفع اليدوي → تفعيل الاشتراك (ذرّية)."""

    def _approve():
        payment.status = "approved"
        payment.reviewed_by = reviewer_id
        payment.reviewed_at = db.func.now()
        sub = payment.subscription
        _activate(sub)
        # إن كان لدى الطالب عضوية بالصف؟ لا نلزم؛ الاشتراك مكمل للعضوية.
        return sub

    return tx(_approve)


def reject_payment(payment: ManualPayment, reviewer_id: int | None = None) -> None:
    def _reject():
        payment.status = "rejected"
        payment.reviewed_by = reviewer_id
        payment.reviewed_at = db.func.now()

    tx(_reject)


def pending_payments():
    return ManualPayment.query.filter_by(status="pending").order_by(ManualPayment.created_at.desc()).all()


def expire_subscriptions() -> int:
    """يُنهي الاشتراكات المنتهية (يُستدعى عند عرض الاشتراكات — بدون مؤقت خارجي)."""
    count = 0

    def _expire():
        nonlocal count
        rows = Subscription.query.filter_by(status="active").all()
        now = datetime.now(UTC)
        for sub in rows:
            if sub.end_at and sub.end_at <= now:
                sub.status = "expired"
                count += 1

    tx(_expire)
    return count


def has_active_subscription(user_id: int, class_id: int) -> bool:
    sub = Subscription.query.filter_by(user_id=user_id, class_id=class_id, status="active").first()
    return sub is not None
