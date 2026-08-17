"""مسارات Webhook للمدفوعات"""

import os

from app.models.billing import Subscription
from app.services.payments import PaymentGateway, get_payment_service
from flask import Blueprint, abort, jsonify, request
from flask_login import current_user, login_required

bp = Blueprint("payments_webhook", __name__, url_prefix="/api/payments")


@bp.post("/webhook/stripe")
def stripe_webhook():
    """Stripe webhook endpoint"""
    payload = request.get_data(as_text=True)
    sig_header = request.headers.get("Stripe-Signature")

    payment_service = get_payment_service()
    result = payment_service.process_webhook(
        PaymentGateway.STRIPE, {"payload": payload}, {"Stripe-Signature": sig_header}
    )
    return jsonify(result), 200 if result.get("success") else 400


@bp.post("/webhook/paytabs")
def paytabs_webhook():
    """PayTabs webhook endpoint"""
    payload = request.get_json() or {}
    payment_service = get_payment_service()
    result = payment_service.process_webhook(PaymentGateway.PAYTABS, payload, dict(request.headers))
    return jsonify(result), 200 if result.get("success") else 400


@bp.post("/webhook/cashu")
def cashu_webhook():
    """CashU webhook endpoint"""
    payload = request.get_json() or {}
    payment_service = get_payment_service()
    result = payment_service.process_webhook(PaymentGateway.CASHU, payload, dict(request.headers))
    return jsonify(result), 200 if result.get("success") else 400


@bp.post("/webhook/whatsapp")
def whatsapp_webhook():
    """WhatsApp payment webhook - للتحقق اليدوي"""
    # التحقق من التوكن
    verify_token = request.args.get("hub.verify_token")
    if verify_token:
        challenge = request.args.get("hub.challenge")
        if verify_token == os.getenv("WHATSAPP_VERIFY_TOKEN"):
            return challenge, 200
        abort(403)

    # استلام رسالة واتساب (معالجة الرسائل الواردة: استفسارات الدفع، صور الإيصالات، إلخ)
    return jsonify({"status": "received"}), 200


# مسارات واجهة المستخدم للمدفوعات
payments_ui_bp = Blueprint("payments_ui", __name__, url_prefix="/payments")


@payments_ui_bp.get("/methods")
@login_required
def payment_methods():
    """عرض طرق الدفع المتاحة"""
    return jsonify(
        {
            "methods": [
                {"id": "stripe", "name": "Stripe (بطاقة)", "enabled": True, "currencies": ["USD", "EUR", "ILS"]},
                {"id": "paytabs", "name": "PayTabs", "enabled": True, "currencies": ["USD", "SAR", "AED", "ILS"]},
                {"id": "cashu", "name": "CashU", "enabled": True, "currencies": ["ILS", "USD"]},
                {"id": "whatsapp", "name": "WhatsApp (يدوي)", "enabled": True, "currencies": ["ILS", "USD", "JOD"]},
                {"id": "manual", "name": "تحويل بنكي / كاش", "enabled": True, "currencies": ["ILS", "USD", "JOD"]},
            ]
        }
    )


@payments_ui_bp.post("/create-intent")
@login_required
def create_payment_intent():
    """إنشاء نية دفع مع تحقق الملكية والمبلغ"""
    from decimal import Decimal

    from app.services.payments import PaymentGateway, get_payment_service
    from flask_babel import _

    data = request.get_json() or {}
    gateway_id = data.get("gateway")
    amount = Decimal(str(data.get("amount", 0)))
    currency = data.get("currency", "ILS")
    subscription_id = data.get("subscription_id")
    metadata = data.get("metadata", {})

    if not gateway_id or amount <= 0:
        return jsonify({"error": _("بيانات غير صالحة")}), 400

    try:
        gateway = PaymentGateway(gateway_id)
    except ValueError:
        return jsonify({"error": _("بوابة دفع غير مدعومة")}), 400

    # تحقق الملكية والمبلغ للاشتراك
    if subscription_id:
        sub = Subscription.query.get_or_404(subscription_id)
        if sub.user_id != current_user.id:
            return jsonify({"error": _("غير مصرح: الاشتراك لا يعود لك")}), 403
        # تحقق المبلغ يطابق سعر الاشتراك
        expected = Decimal(str(sub.price))
        if amount != expected:
            return jsonify({"error": _("المبلغ غير مطابق لسعر الاشتراك")}), 400
        if currency != sub.currency:
            return jsonify({"error": _("العملة غير مطابقة للاشتراك")}), 400

    payment_service = get_payment_service()
    intent = payment_service.create_payment(
        gateway=gateway,
        amount=amount,
        currency=currency,
        user_id=current_user.id,
        subscription_id=subscription_id,
        metadata=metadata,
    )

    if not intent:
        return jsonify({"error": _("فشل إنشاء طلب الدفع")}), 500

    return jsonify(
        {
            "payment_id": intent.id,
            "gateway": intent.gateway.value,
            "client_data": intent.gateway_response,
            "amount": str(intent.amount),
            "currency": intent.currency,
        }
    )


@payments_ui_bp.post("/verify")
@login_required
def verify_payment():
    """التحقق من الدفع (للبوابات اليدوية/واتساب) — للبوابات الآلية يتم عبر webhook"""
    from app.services.payments import PaymentGateway, get_payment_service
    from flask_babel import _

    data = request.get_json() or {}
    payment_id = data.get("payment_id")
    gateway_id = data.get("gateway")
    verification_data = data.get("verification_data", {})

    if not payment_id or not gateway_id:
        return jsonify({"error": _("بيانات غير مكتملة")}), 400

    try:
        gateway = PaymentGateway(gateway_id)
    except ValueError:
        return jsonify({"error": _("بوابة غير مدعومة")}), 400

    gateway_obj = get_payment_service().gateways.get(gateway)

    if not gateway_obj:
        return jsonify({"error": _("البوابة غير مفعلة")}), 400

    # إنشاء payment intent وهمي للتحقق
    from decimal import Decimal

    from app.services.payments import PaymentIntent, PaymentStatus

    dummy_intent = PaymentIntent(
        id=payment_id,
        gateway=gateway,
        amount=Decimal("0"),
        currency="ILS",
        status=PaymentStatus.PENDING,
        user_id=current_user.id,
    )

    # التحقق اليدوي يمرر admin_approved=True من المشرف
    verification_data["admin_approved"] = True
    verified = gateway_obj.verify_payment(dummy_intent, verification_data)

    if verified:
        return jsonify({"success": True, "message": _("تم التحقق بنجاح")})
    else:
        return jsonify({"success": False, "error": _("فشل التحقق")}), 400
