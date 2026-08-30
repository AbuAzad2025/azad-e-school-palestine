"""خدمات الاشتراك والدفع اليدوي (D12 — لا بوابات؛ اعتماد بشري).

P1-08: كل الحسابات المالية Decimal(10,2) بتقريب ROUND_HALF_UP — لا Float إطلاقاً.
"""

from datetime import UTC, datetime, timedelta
from datetime import date as date_
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, update
from sqlalchemy.orm import joinedload

from app.core.db import TxError, tx
from app.core.i18n import _
from app.core.uploads import save_upload
from app.extensions import db
from app.models.billing import DiscountCode, ManualPayment, PaymentReceipt, Subscription, SubscriptionPlan

CENT = Decimal("0.01")


def money(value: Decimal | float | int | str) -> Decimal:
    """يطبّع أي مدخل مالي إلى Decimal مقرّباً لأقرب قرش (ROUND_HALF_UP)."""
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def create_plan(
    school_id: int,
    name: str,
    plan: str,
    price: Decimal | float | int | str,
    class_id: int | None = None,
    currency: str = "ILS",
    duration_days: int | None = None,
    benefits: dict | None = None,
) -> tuple[SubscriptionPlan | None, str | None]:
    name = (name or "").strip()
    if not name or price is None:
        return None, _("الاسم والسعر مطلوبان.")
    if plan not in ("first_term", "second_term", "annual"):
        return None, _("نوع خطة غير صالح.")

    def _create():
        p = SubscriptionPlan(
            school_id=school_id,
            class_id=class_id,
            name=name,
            plan=plan,
            price=money(price),
            currency=currency,
            duration_days=duration_days,
            benefits=benefits,
        )
        db.session.add(p)
        return p

    return tx(_create), None


def list_plans(class_id: int | None = None):
    query = SubscriptionPlan.query.filter_by(is_active=True)
    if class_id:
        query = query.filter((SubscriptionPlan.class_id == class_id) | (SubscriptionPlan.class_id.is_(None)))
    return query.order_by(SubscriptionPlan.price.asc()).all()


def get_plan(plan_id: int) -> SubscriptionPlan | None:
    return db.session.get(SubscriptionPlan, plan_id)


def subscribe(user_id: int, plan: SubscriptionPlan, class_id: int) -> tuple[Subscription | None, str | None]:
    """يبدأ اشتراكاً بحالة pending — لا يُفعَّل إلا بعد اعتماد دفع يدوي.

    P0-10: FOR UPDATE على صف الاشتراك النشط لمنع اشتراك مزدوج تحت التزامن.
    """
    active = Subscription.query.filter_by(user_id=user_id, class_id=class_id, status="active").with_for_update().first()
    if active:
        return None, _("لديك اشتراك نشط في هذا الصف.")

    def _create():
        sub = Subscription(
            user_id=user_id,
            plan_id=plan.id,
            class_id=class_id,
            price=plan.price,
            currency=plan.currency,
            status="pending",
            source="manual",
        )
        db.session.add(sub)
        return sub

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
    subscription: Subscription,
    reference: str,
    amount: Decimal | float | int | str,
    note: str | None = None,
    receipt_file=None,
) -> tuple[ManualPayment | None, str | None]:
    reference = (reference or "").strip()
    amount_dec = money(amount) if amount is not None else None
    if not reference or amount_dec is None or amount_dec <= 0:
        return None, _("المرجع والمبلغ مطلوبان.")

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
            amount=amount_dec,
            note=note,
        )
        db.session.add(payment)
        # P0-04: flush داخل نفس المعاملة ليُحسم payment.id قبل ربط الإيصال
        db.session.flush()
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
    """اعتماد الدفع اليدوي → تفعيل الاشتراك (ذرّية + حماية من الاعتماد المكرر).

    P0-10: FOR UPDATE على صف الدفع لمنع اعتماد مزدوج تحت التزامن.
    """

    def _approve():
        # P2-10: منع إعادة الاعتماد (توسيع الاشتراك مجاناً)
        locked = db.session.execute(
            db.select(ManualPayment).where(ManualPayment.id == payment.id).with_for_update()
        ).scalar_one()
        if locked.status != "pending":
            raise TxError(_("تمت مراجعة هذا الدفع مسبقاً."))
        locked.status = "approved"
        locked.reviewed_by = reviewer_id
        locked.reviewed_at = db.func.now()
        sub = locked.subscription
        _activate(sub)
        return sub

    return tx(_approve)


def reject_payment(payment: ManualPayment, reviewer_id: int | None = None) -> None:
    """P0-10: FOR UPDATE على صف الدفع لمنع رفض مزدوج تحت التزامن."""

    def _reject():
        locked = db.session.execute(
            db.select(ManualPayment).where(ManualPayment.id == payment.id).with_for_update()
        ).scalar_one()
        if locked.status != "pending":
            raise TxError(_("تمت مراجعة هذا الدفع مسبقاً."))
        locked.status = "rejected"
        locked.reviewed_by = reviewer_id
        locked.reviewed_at = db.func.now()

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
    """يُنهي الاشتراكات المنتهية — تُستدعى من CLI/cron (P3-15) لا من عرض الصفحات."""

    def _expire():
        now = datetime.now(UTC)
        stmt = (
            update(Subscription)
            .where(Subscription.status == "active")
            .where(Subscription.end_at <= now)
            .values(status="expired")
        )
        result = db.session.execute(stmt)
        return result.rowcount  # type: ignore[attr-defined]

    return tx(_expire)


def has_active_subscription(user_id: int, class_id: int) -> bool:
    sub = Subscription.query.filter_by(user_id=user_id, class_id=class_id, status="active").first()
    return sub is not None


def subscription_balance(subscription_id: int) -> Decimal:
    """الرصيد المتبقي للاشتراك = السعر - مجموع الدفعات المعتمدة (Decimal)."""
    sub = db.session.get(Subscription, subscription_id)
    if not sub:
        return Decimal("0.00")
    paid = db.session.query(func.sum(ManualPayment.amount)).filter(
        ManualPayment.subscription_id == subscription_id,
        ManualPayment.status == "approved",
    ).scalar() or Decimal("0")
    return (sub.price - paid).quantize(CENT, rounding=ROUND_HALF_UP)


def can_record_payment(subscription_id: int, amount: Decimal | float | int | str) -> tuple[bool, str]:
    """يتحقق مما إذا كان المبلغ لا يتجاوز الرصيد المتبقي."""
    amount_dec = money(amount)
    balance = subscription_balance(subscription_id)
    if amount_dec <= 0:
        return False, _("المبلغ يجب أن يكون أكبر من صفر.")
    if amount_dec > balance:
        return False, _("المبلغ (%(amount)s) يتجاوز الرصيد المتبقي (%(balance)s).", amount=amount_dec, balance=balance)
    return True, ""


def subscription_payment_summary(subscription_id: int) -> dict:
    """ملخص الدفعات للاشتراك."""
    sub = db.session.get(Subscription, subscription_id)
    if not sub:
        return {}
    payments = ManualPayment.query.filter_by(subscription_id=subscription_id).all()
    approved = [p for p in payments if p.status == "approved"]
    pending = [p for p in payments if p.status == "pending"]
    total_paid = sum((p.amount for p in approved), Decimal("0.00")).quantize(CENT, rounding=ROUND_HALF_UP)
    balance = (sub.price - total_paid).quantize(CENT, rounding=ROUND_HALF_UP)
    return {
        "total_price": sub.price.quantize(CENT, rounding=ROUND_HALF_UP),
        "total_paid": total_paid,
        "balance": balance,
        "approved_count": len(approved),
        "pending_count": len(pending),
    }


def create_discount_code(
    school_id: int,
    code: str,
    name: str,
    type_: str,
    value: Decimal | float | int | str,
    max_uses: int = 1,
    expiry_date: date_ | None = None,
    applicable_plan_ids: list[int] | None = None,
    school_id_limit: int | None = None,
) -> tuple[DiscountCode | None, str | None]:
    """إنشاء كود خصم جديد."""
    code = (code or "").strip().upper()
    name = (name or "").strip()
    if not code:
        return None, _("كود الخصم مطلوب.")
    if not name:
        return None, _("اسم الخصم مطلوب.")
    if type_ not in ("percentage", "fixed"):
        return None, _("نوع الخصم غير صالح (percentage/fixed).")
    if money(value) <= 0:
        return None, _("قيمة الخصم يجب أن تكون أكبر من صفر.")
    if max_uses < 1:
        return None, _("الحد الأقصى للاستخدام يجب أن يكون 1 على الأقل.")
    if expiry_date and expiry_date < date_.today():
        return None, _("تاريخ الانتهاء لا يمكن أن يكون في الماضي.")

    if DiscountCode.query.filter_by(code=code).first():
        return None, _("كود الخصم موجود مسبقاً.")

    def _create():
        dc = DiscountCode(
            code=code,
            name=name,
            type=type_,
            value=money(value),
            max_uses=max_uses,
            expiry_date=expiry_date,
            applicable_plan_ids=applicable_plan_ids,
            school_id=school_id_limit,
        )
        db.session.add(dc)
        return dc

    return tx(_create), None


def validate_discount_code(code: str, plan_id: int) -> tuple[Decimal | None, str | None]:
    """التحقق من صلاحية كود الخصم وإرجاع مبلغ الخصم (Decimal)."""
    code = (code or "").strip().upper()
    if not code:
        return None, _("كود الخصم مطلوب.")

    dc = DiscountCode.query.filter_by(code=code).first()
    if not dc:
        return None, _("كود الخصم غير صالح.")
    if not dc.is_active:
        return None, _("كود الخصم غير مفعل.")
    if dc.expiry_date and dc.expiry_date < date_.today():
        return None, _("كود الخصم منتهي الصلاحية.")
    if dc.used_count >= dc.max_uses:
        return None, _("تم استنفاد عدد استخدامات كود الخصم.")
    if dc.applicable_plan_ids and plan_id not in dc.applicable_plan_ids:
        return None, _("كود الخصم غير صالح لهذه الخطة.")
    if dc.school_id:
        # School check will be done at subscription level
        pass

    # Calculate discount amount
    plan = db.session.get(SubscriptionPlan, plan_id)
    if not plan:
        return None, _("الخطة غير موجودة.")

    plan_price: Decimal = plan.price.quantize(CENT, rounding=ROUND_HALF_UP)
    if dc.type == "percentage":
        discount = (plan_price * dc.value / Decimal("100")).quantize(CENT, rounding=ROUND_HALF_UP)
    else:
        discount = dc.value.quantize(CENT, rounding=ROUND_HALF_UP)

    # Cap discount at plan price
    discount = min(discount, plan_price)
    return discount, None


def apply_discount_code(subscription_id: int, code: str) -> tuple[Decimal | None, str | None]:
    """تطبيق كود خصم على اشتراك (ذرّي — P1-09: لا تجاوز لحد الاستخدام تحت التزامن)."""
    code = (code or "").strip().upper()
    if not code:
        return None, _("كود الخصم مطلوب.")

    sub = db.session.get(Subscription, subscription_id)
    if not sub:
        return None, _("الاشتراك غير موجود.")

    discount, error = validate_discount_code(code, sub.plan_id)
    if error:
        return None, error

    def _apply():
        if discount is None:
            raise ValueError("Discount cannot be None")
        # P1-09: زيادة ذرّية مشروطة — تفشل إن استُنفد الحد بين التحقق والتطبيق
        result = db.session.execute(
            update(DiscountCode)
            .where(DiscountCode.code == code.upper(), DiscountCode.used_count < DiscountCode.max_uses)
            .values(used_count=DiscountCode.used_count + 1)
        )
        if result.rowcount != 1:  # type: ignore[attr-defined]
            raise TxError(_("تم استنفاد عدد استخدامات كود الخصم."))
        new_price = (sub.price - discount).quantize(CENT, rounding=ROUND_HALF_UP)
        if new_price < 0:
            raise TxError(_("قيمة الخصم تتجاوز سعر الاشتراك."))
        sub.price = new_price
        return discount

    try:
        return tx(_apply), None
    except TxError as exc:
        return None, str(exc)
