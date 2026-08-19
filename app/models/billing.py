"""الاشتراك والدفع — حقيبة معزولة (درس OpenEduCat Fees)"""

from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db

from .mixins import PKMixin
from .user import User


class SubscriptionPlan(PKMixin, db.Model):
    __tablename__ = "subscription_plans"

    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), nullable=False)
    class_id: Mapped[int | None] = mapped_column(ForeignKey("classes.id"))  # NULL = خطة عامة للمدرسة
    name: Mapped[str] = mapped_column(Text, nullable=False)  # فصل أول / فصل ثاني / سنوي
    plan: Mapped[str] = mapped_column(String(15), nullable=False)  # first_term/second_term/annual
    price: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="ILS", nullable=False)
    duration_days: Mapped[int | None] = mapped_column(Integer)
    benefits: Mapped[dict | None] = mapped_column(JSONB)  # مزايا المواد الاختيارية
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Subscription(PKMixin, db.Model):
    __tablename__ = "subscriptions"
    __table_args__ = (UniqueConstraint("user_id", "plan_id", "class_id", "status", name="uq_subscription_active"),)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("subscription_plans.id"), nullable=False)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id"), nullable=False)
    price: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="ILS", nullable=False)
    start_at = db.Column(db.DateTime(timezone=True))
    end_at = db.Column(db.DateTime(timezone=True))
    status: Mapped[str] = mapped_column(
        String(10), default="pending", nullable=False
    )  # pending/active/expired/cancelled/pending_review
    source: Mapped[str] = mapped_column(String(10), default="manual", nullable=False)  # manual/gateway
    auto_activated_at = db.Column(db.DateTime(timezone=True))

    payments: Mapped[list[ManualPayment]] = relationship(back_populates="subscription", cascade="all, delete-orphan")
    user: Mapped[User] = relationship("User")
    plan: Mapped[SubscriptionPlan] = relationship("SubscriptionPlan")


class ManualPayment(PKMixin, db.Model):
    __tablename__ = "manual_payments"

    subscription_id: Mapped[int] = mapped_column(ForeignKey("subscriptions.id"), nullable=False)
    reference: Mapped[str] = mapped_column(Text, nullable=False)  # رقم مرجع التحويل
    amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), default="pending", nullable=False)  # pending/approved/rejected
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at = db.Column(db.DateTime(timezone=True))
    gateway: Mapped[str | None] = mapped_column(String(20))  # stripe/paytabs/cashu/manual

    subscription: Mapped[Subscription] = relationship(back_populates="payments")
    receipts: Mapped[list[PaymentReceipt]] = relationship(back_populates="payment", cascade="all, delete-orphan")


class PaymentReceipt(PKMixin, db.Model):
    __tablename__ = "payment_receipts"

    manual_payment_id: Mapped[int] = mapped_column(ForeignKey("manual_payments.id"), nullable=False)
    stored_name: Mapped[str] = mapped_column(Text, nullable=False)
    original_name: Mapped[str | None] = mapped_column(Text)
    mime: Mapped[str | None] = mapped_column(String(120))
    size_bytes: Mapped[int | None] = mapped_column(Numeric(20))

    payment: Mapped[ManualPayment] = relationship(back_populates="receipts")


class ProcessedEvent(PKMixin, db.Model):
    """أحداث Webhook المعالجة — لمنع المعالجة المكررة (Idempotency)."""

    __tablename__ = "processed_events"

    event_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False, index=True)
    gateway: Mapped[str] = mapped_column(String(20), nullable=False)
    payload: Mapped[dict | None] = mapped_column(JSONB)
    processed_at = db.Column(db.DateTime(timezone=True), default=db.func.now())


class ReminderLog(PKMixin, db.Model):
    """سجل التذكيرات المرسلة — لمنع الإرسال المكرر"""

    __tablename__ = "reminder_logs"

    subscription_id: Mapped[int] = mapped_column(ForeignKey("subscriptions.id"), nullable=False, index=True)
    reminder_type: Mapped[str] = mapped_column(String(10), nullable=False)  # 7d/3d/1d
    sent_at = db.Column(db.DateTime(timezone=True), default=db.func.now())

    subscription: Mapped[Subscription] = relationship()

    __table_args__ = (db.UniqueConstraint("subscription_id", "reminder_type", name="uq_reminder_log_unique"),)
