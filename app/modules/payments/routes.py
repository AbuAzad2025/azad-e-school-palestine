"""مسارات Webhook للمدفوعات"""

from app.core.db import db
from app.core.webhooks import safe_json_loads
from app.extensions import csrf
from app.models.billing import Subscription
from app.services.payments import PaymentGateway, get_payment_service
from flask import Blueprint, abort, jsonify, render_template, request
from flask_login import current_user, login_required

bp = Blueprint("payments_webhook", __name__, url_prefix="/api/payments")

# كل مسارات هذا المخطّط بوابات مزوّدين: نداءات خادمية بلا جلسة ولا رمز CSRF،
# فكان محرّك الحماية يرفضها كلها بـ400. التحقّق يتم داخل كل بوابة (توقيع
# المزوّد على الجسم الخام) وهو ما يثبت مصدر الطلب.
csrf.exempt(bp)


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
    # نقرأ الجسم مرة واحدة: نفس البايتات تُستخدم للتحقق من التوقيع ولتفكيك
    # JSON — إعادة الترميز تُنتج بايتات قد لا تطابق ما وقّع عليه المرسِل.
    raw_body = request.get_data()
    payload = safe_json_loads(raw_body)
    payment_service = get_payment_service()
    result = payment_service.process_webhook(PaymentGateway.PAYTABS, payload, dict(request.headers), raw_body)
    return jsonify(result), 200 if result.get("success") else 400


@bp.post("/webhook/cashu")
def cashu_webhook():
    """CashU webhook endpoint"""
    raw_body = request.get_data()
    payload = safe_json_loads(raw_body)
    payment_service = get_payment_service()
    result = payment_service.process_webhook(PaymentGateway.CASHU, payload, dict(request.headers), raw_body)
    return jsonify(result), 200 if result.get("success") else 400


# DEPRECATED: the stub that returned {"status": "received"} is gone. The
# production engine lives in app/modules/whatsapp and verifies a Meta HMAC
# signature over the raw body before touching anything. This alias is kept so
# an already-configured Meta subscription URL keeps working, but it no longer
# accepts unsigned traffic.
@bp.post("/webhook/whatsapp")
def whatsapp_webhook_alias():
    """تفويض كامل إلى محرّك واتساب — لا مسار ثانٍ بلا تحقّق."""
    from app.core.webhooks import safe_json_loads
    from app.modules.whatsapp.routes import _handle_events
    from app.services.whatsapp import (
        MAX_BODY_BYTES,
        META_SIGNATURE_HEADER,
        verification_challenge_response,
        verified_webhook_scope,
        verify_inbound_signature,
    )
    from flask import current_app, jsonify, request

    mode = request.args.get("hub.mode")
    challenge = request.args.get("hub.challenge")
    if mode or challenge:
        response = verification_challenge_response(
            mode=mode,
            verify_token=request.args.get("hub.verify_token"),
            challenge=challenge,
        )
        if response is None:
            abort(403)
        return response, 200

    raw_body = request.get_data()
    if len(raw_body) > MAX_BODY_BYTES:
        abort(413)
    if not verify_inbound_signature(
        raw_body=raw_body,
        headers=dict(request.headers),
        secret=current_app.config.get("WHATSAPP_APP_SECRET") or None,
        header_name=META_SIGNATURE_HEADER,
    ):
        abort(401)
    with verified_webhook_scope():
        handled = _handle_events(safe_json_loads(raw_body))
    return jsonify({"status": "processed", "handled": handled}), 200


# مسارات واجهة المستخدم للمدفوعات
payments_ui_bp = Blueprint("payments_ui", __name__, url_prefix="/payments")


@payments_ui_bp.get("/")
@login_required
def payment_methods_page():
    """صفحة طرق الدفع المتاحة"""
    methods = [
        {"id": "stripe", "name": "Stripe (بطاقة)", "enabled": True, "currencies": ["USD", "EUR", "ILS"]},
        {"id": "paytabs", "name": "PayTabs", "enabled": True, "currencies": ["USD", "SAR", "AED", "ILS"]},
        {"id": "cashu", "name": "CashU", "enabled": True, "currencies": ["ILS", "USD"]},
        {"id": "whatsapp", "name": "WhatsApp (يدوي)", "enabled": True, "currencies": ["ILS", "USD", "JOD"]},
        {"id": "manual", "name": "تحويل بنكي / كاش", "enabled": True, "currencies": ["ILS", "USD", "JOD"]},
    ]
    return render_template("payments_ui/index.html", methods=methods)


@payments_ui_bp.get("/methods")
@login_required
def payment_methods():
    """عرض طرق الدفع المتاحة (API)"""
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
        sub = db.get_or_404(Subscription, subscription_id)
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
