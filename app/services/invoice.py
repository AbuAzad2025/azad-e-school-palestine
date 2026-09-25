"""فواتير — إنشاء فواتير PDF للاشتراكات.

البناء عبر reportlab (platypus) عبر البنية المشتركة app/core/pdf.py —
خط عربي مدمج + تشكيل RTL، بلا وسيط HTML (xhtml2pdf لا يدمج خطوط TTF
عربية بشكل موثوق). قصة الفاتورة الواحدة (build_invoice_story) تُستخدم
من الخدمة المتزامنة (render_invoice_pdf) ومن مهمة الخلفية (app.tasks.reports)
حتى تتطابق الأربطة الثنائية دائماً.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)


def generate_invoice_number(subscription) -> str:
    """رقم الفاتورة: INV-{school_id}-{year}-{id}."""
    from datetime import datetime

    year = datetime.now().year
    return f"INV-{subscription.class_id}-{year}-{subscription.id:05d}"


def generate_invoice_html(subscription_id: int) -> str | None:
    """إنشاء فاتورة HTML (عرض الشاشة فقط — عبر billing.invoice_view)."""
    from flask import render_template

    from app.extensions import db
    from app.models.billing import Subscription
    from app.services.billing import subscription_payment_summary

    sub = db.session.get(Subscription, subscription_id)
    if not sub:
        return None

    summary = subscription_payment_summary(subscription_id)
    invoice_number = generate_invoice_number(sub)

    return render_template(
        "billing/invoice.html",
        subscription=sub,
        summary=summary,
        invoice_number=invoice_number,
    )


def build_invoice_story(story: list, subscription: Any, payments: list[Any] | None = None) -> None:
    """تعبئة قصة platypus بفاتورة الاشتراك — المصدر الوحيد لتخطيط الفاتورة.

    تُستخدم من render_invoice_pdf (متزامن) ومن app.tasks.reports (خلفي)
    عبر _write_invoice_pdf — بلا تكرار.

    Args:
        story: قصة platypus فارغة من blank_pdf_document().
        subscription: كائن Subscription محمَّل.
        payments: دفعات المهمة الخلفية (المصدر الوحيد للأرصدة هنا
            هو subscription_payment_summary — payments اختيارية للتوافق).
    """
    from reportlab.lib.units import mm

    from app.core.pdf import (
        register_arabic_font,
        shape_arabic,
        shape_arabic_deep,
        story_meta,
        story_subtitle,
        story_table,
        story_title,
    )
    from app.services.billing import subscription_payment_summary

    font = register_arabic_font()

    summary = subscription_payment_summary(subscription.id)
    total_paid = Decimal(str(summary.get("total_paid") or 0))
    balance = Decimal(str(summary.get("balance") or 0))
    currency = subscription.currency or "ILS"

    plan = getattr(subscription, "plan", None)
    plan_name = getattr(plan, "name", "—") or "—"
    student = getattr(subscription, "user", None)
    student_name = getattr(student, "name_ar", None) or getattr(student, "email", "") or str(subscription.user_id)

    status_labels = {
        "pending": "معلق",
        "active": "نشط",
        "expired": "منتهي",
        "cancelled": "ملغي",
    }
    status_label = status_labels.get(subscription.status, subscription.status or "—")

    story_title(story, shape_arabic_deep("منصة مدرسة أزاد الإلكترونية"), font)
    story_subtitle(story, shape_arabic("فاتورة اشتراك"), font)
    now_utc = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    story_meta(story, f"Invoice: {generate_invoice_number(subscription)} | {now_utc}")

    info_rows = [
        [shape_arabic_deep("الطالب"), shape_arabic_deep(str(student_name))],
        [shape_arabic_deep("الخطة"), shape_arabic_deep(str(plan_name))],
        [shape_arabic_deep("الحالة"), shape_arabic_deep(status_label)],
        [shape_arabic_deep("رقم الاشتراك"), f"#{subscription.id}"],
    ]
    story_table(story, info_rows, [40 * mm, 80 * mm], font)

    story_subtitle(story, shape_arabic_deep("تفاصيل المبالغ"), font)
    amount_rows = [
        [shape_arabic_deep("البيان"), shape_arabic_deep("المبلغ")],
        [shape_arabic_deep(f"اشتراك: {plan_name}"), f"{subscription.price} {currency}"],
        [shape_arabic_deep("المدفوع"), f"{total_paid} {currency}"],
        [shape_arabic_deep("المتبقي"), f"{balance} {currency}"],
    ]
    story_table(story, amount_rows, [80 * mm, 40 * mm], font)

    payment_rows = [
        [
            shape_arabic_deep(str(getattr(p, "reference", "") or "—")),
            f"{getattr(p, 'amount', '')} {currency}",
            shape_arabic_deep(str(getattr(p, "status", "") or "")),
        ]
        for p in (payments or [])
    ]
    if payment_rows:
        story_subtitle(story, shape_arabic_deep("سجل المدفوعات"), font)
        story_table(
            story,
            [[shape_arabic_deep("المرجع"), shape_arabic_deep("المبلغ"), shape_arabic_deep("الحالة")], *payment_rows],
            [50 * mm, 40 * mm, 30 * mm],
            font,
        )


def render_invoice_pdf(subscription_id: int) -> bytes | None:
    """إنشاء فاتورة PDF حقيقية عبر reportlab (لا HTML وسيط).

    Returns:
        bytes الخام عند النجاح؛ None إذا لم يوجد الاشتراك أو فشل البناء.
    """
    from app.extensions import db
    from app.models.billing import Subscription

    sub = db.session.get(Subscription, subscription_id)
    if not sub:
        return None

    try:
        from app.core.pdf import blank_pdf_document, build_pdf_bytes, write_pdf_file

        doc, story = blank_pdf_document()
        build_invoice_story(story, sub)
        data = build_pdf_bytes(doc, story)
    except Exception:
        logger.exception("invoice_pdf_generation_failed", subscription_id=subscription_id)
        return None

    write_pdf_file("invoices", f"invoice_{subscription_id}", data)
    return data
