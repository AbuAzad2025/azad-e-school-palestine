"""التواصل الداخلي: إشعارات + سجل تدقيق — خدمة موحّدة بلا تكرار."""

from typing import Any

from flask import request
from flask_login import current_user

from app.extensions import db
from app.models.communication import Notification
from app.models.system import AuditLog

from .base import tx


def notify(user_id: int, type: str, title: str, body: str | None = None, link: str | None = None) -> None:
    """إشعار داخل المنصة (نتيجة، واجب جديد، اشتراك...)."""

    def _notify():
        db.session.add(Notification(user_id=user_id, type=type, title=title, body=body, link=link))

    tx(_notify)


def unread_count(user_id: int) -> int:
    return Notification.query.filter_by(user_id=user_id, is_read=False).count()


def mark_all_read(user_id: int) -> None:
    def _mark():
        Notification.query.filter_by(user_id=user_id, is_read=False).update({"is_read": True})

    tx(_mark)


def audit(
    action: str,
    entity: str | None = None,
    entity_id: int | None = None,
    detail: dict | None = None,
    amount: float | None = None,
    currency: str | None = None,
    gateway: str | None = None,
    subscription_id: int | None = None,
    session_id: int | None = None,
) -> None:
    """
    سجل تدقيق — أي إجراء مهم يوثَّق (لا يُغيّر منطق العمل).
    يدعم تفاصيل مالية: المبلغ، العملة، بوابة الدفع، معرف الاشتراك/الجلسة.
    """
    uid = current_user.id if current_user.is_authenticated else None
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "") if request else None

    # دمج التفاصيل المالية في detail
    financial_detail: dict[str, Any] = {}
    if amount is not None:
        financial_detail["amount"] = amount
    if currency:
        financial_detail["currency"] = currency
    if gateway:
        financial_detail["gateway"] = gateway
    if subscription_id is not None:
        financial_detail["subscription_id"] = subscription_id
    if session_id is not None:
        financial_detail["session_id"] = session_id

    merged_detail = {**(detail or {}), **financial_detail}

    def _audit():
        db.session.add(
            AuditLog(
                user_id=uid,
                action=action,
                entity=entity,
                entity_id=entity_id,
                detail=merged_detail,
                ip=ip,
            )
        )

    tx(_audit)
