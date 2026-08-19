"""خدمات الاشتراك والدفع اليدوي (D12 — لا بوابات؛ اعتماد بشري)."""

from datetime import UTC, datetime, timedelta
from datetime import date as date_

from sqlalchemy import func
from sqlalchemy.orm import joinedload

from app.core.db import TxError, tx
from app.core.uploads import save_upload
from app.extensions import db
from app.models.billing import DiscountCode, ManualPayment, PaymentReceipt, Subscription, SubscriptionPlan


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


def _activate(subscription: Subscription, duration_days: int | None = None, auto_activate: bool = False) -> None:
    days = duration_days or subscription.plan.duration_days or 180
    now = datetime.now(UTC)
    subscription.start_at = now
    subscription.end_at = now + timedelta(days=days)
    subscription.status = "active"
    if auto_activate:
        subscription.auto_activated_at = now
        subscription.source = "gateway"


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
    return (
        ManualPayment.query.filter_by(status="pending")
        .options(
            joinedload(ManualPayment.subscription).joinedload(Subscription.user),
            joinedload(ManualPayment.subscription).joinedload(Subscription.plan),
            joinedload(ManualPayment.receipts),
        )
        .order_by(ManualPayment.created_at.desc())
        .all()
    )


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


def subscription_balance(subscription_id: int) -> float:
    """الرصيد المتبقي للاشتراك = السعر - مجموع الدفعات المعتمدة."""
    sub = db.session.get(Subscription, subscription_id)
    if not sub:
        return 0
    paid = (
        db.session.query(func.sum(ManualPayment.amount))
        .filter(
            ManualPayment.subscription_id == subscription_id,
            ManualPayment.status == "approved",
        )
        .scalar()
        or 0
    )
    return float(sub.price) - float(paid)


def can_record_payment(subscription_id: int, amount: float) -> tuple[bool, str]:
    """يتحقق مما إذا كان المبلغ لا يتجاوز الرصيد المتبقي."""
    balance = subscription_balance(subscription_id)
    if amount <= 0:
        return False, "المبلغ يجب أن يكون أكبر من صفر."
    if amount > balance:
        return False, f"المبلغ ({amount}) يتجاوز الرصيد المتبقي ({balance})."
    return True, ""


def subscription_payment_summary(subscription_id: int) -> dict:
    """ملخص الدفعات للاشتراك."""
    sub = db.session.get(Subscription, subscription_id)
    if not sub:
        return {}
    payments = ManualPayment.query.filter_by(subscription_id=subscription_id).all()
    approved = [p for p in payments if p.status == "approved"]
    pending = [p for p in payments if p.status == "pending"]
    total_paid = sum(float(p.amount) for p in approved)
    return {
        "total_price": float(sub.price),
        "total_paid": total_paid,
        "balance": float(sub.price) - total_paid,
        "approved_count": len(approved),
        "pending_count": len(pending),
    }


def create_discount_code(
    school_id: int,
    code: str,
    name: str,
    type_: str,
    value: float,
    max_uses: int = 1,
    expiry_date: date_ | None = None,
    applicable_plan_ids: list[int] | None = None,
    school_id_limit: int | None = None,
) -> tuple[DiscountCode | None, str | None]:
    """إنشاء كود خصم جديد."""
    code = (code or "").strip().upper()
    name = (name or "").strip()
    if not code:
        return None, "كود الخصم مطلوب."
    if not name:
        return None, "اسم الخصم مطلوب."
    if type_ not in ("percentage", "fixed"):
        return None, "نوع الخصم غير صالح (percentage/fixed)."
    if value <= 0:
        return None, "قيمة الخصم يجب أن تكون أكبر من صفر."
    if max_uses < 1:
        return None, "الحد الأقصى للاستخدام يجب أن يكون 1 على الأقل."
    if expiry_date and expiry_date < date_.today():
        return None, "تاريخ الانتهاء لا يمكن أن يكون في الماضي."

    if DiscountCode.query.filter_by(code=code).first():
        return None, "كود الخصم موجود مسبقاً."

    def _create():
        dc = DiscountCode(
            code=code,
            name=name,
            type=type_,
            value=value,
            max_uses=max_uses,
            expiry_date=expiry_date,
            applicable_plan_ids=applicable_plan_ids,
            school_id=school_id_limit,
        )
        db.session.add(dc)
        return dc

    return tx(_create), None


def validate_discount_code(code: str, plan_id: int) -> tuple[float | None, str | None]:
    """التحقق من صلاحية كود الخصم وإرجاع مبلغ الخصم."""
    code = (code or "").strip().upper()
    if not code:
        return None, "كود الخصم مطلوب."

    dc = DiscountCode.query.filter_by(code=code).first()
    if not dc:
        return None, "كود الخصم غير صالح."
    if not dc.is_active:
        return None, "كود الخصم غير مفعل."
    if dc.expiry_date and dc.expiry_date < date_.today():
        return None, "كود الخصم منتهي الصلاحية."
    if dc.used_count >= dc.max_uses:
        return None, "تم استنفاد عدد استخدامات كود الخصم."
    if dc.applicable_plan_ids and plan_id not in dc.applicable_plan_ids:
        return None, "كود الخصم غير صالح لهذه الخطة."
    if dc.school_id:
        # School check will be done at subscription level
        pass

    # Calculate discount amount
    plan = db.session.get(SubscriptionPlan, plan_id)
    if not plan:
        return None, "الخطة غير موجودة."

    plan_price = float(plan.price)
    if dc.type == "percentage":
        discount = plan_price * (float(dc.value) / 100)
    else:
        discount = float(dc.value)

    # Cap discount at plan price
    discount = min(discount, plan_price)
    return discount, None


def apply_discount_code(subscription_id: int, code: str) -> tuple[float | None, str | None]:
    """تطبيق كود خصم على اشتراك."""
    code = (code or "").strip().upper()
    if not code:
        return None, "كود الخصم مطلوب."

    sub = db.session.get(Subscription, subscription_id)
    if not sub:
        return None, "الاشتراك غير موجود."

    discount, error = validate_discount_code(code, sub.plan_id)
    if error:
        return None, error

    def _apply():
        # Store discount info in subscription (could add fields to Subscription model)
        # For now, we'll adjust the subscription price
        assert discount is not None
        sub.price = float(sub.price) - discount
        dc = DiscountCode.query.filter_by(code=code.upper()).first()
        if dc:
            dc.used_count += 1
        return discount

    return tx(_apply), None
