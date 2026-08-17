"""فواتير — إنشاء فواتير PDF للاشتراكات."""

from flask import render_template

from app.services.billing import subscription_payment_summary


def generate_invoice_number(subscription) -> str:
    """رقم الفاتورة: INV-{school_id}-{year}-{id}."""
    from datetime import datetime

    year = datetime.now().year
    return f"INV-{subscription.class_id}-{year}-{subscription.id:05d}"


def generate_invoice_html(subscription_id: int) -> str | None:
    """إنشاء فاتورة HTML."""
    from app.extensions import db
    from app.models.billing import Subscription

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


def render_invoice_pdf(subscription_id: int) -> bytes | None:
    """إنشاء فاتورة PDF."""
    html = generate_invoice_html(subscription_id)
    if not html:
        return None

    try:
        from xhtml2pdf import pisa

        pdf_bytes = pisa.CreatePDF(html).dest
        return pdf_bytes
    except ImportError:
        return None
