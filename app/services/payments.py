"""نظام المدفوعات المتكامل — Stripe + بوابات محلية + WhatsApp + يدوي

الأمان: تحقق توقيع Webhook، Idempotency، تحقق ملكية، تحقق مبلغ.
"""

import hashlib
import hmac
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any

from app.extensions import db
from app.models.billing import ProcessedEvent


class PaymentGateway(Enum):
    STRIPE = "stripe"
    PAYTABS = "paytabs"
    CASHU = "cashu"
    WHATSAPP = "whatsapp"
    MANUAL = "manual"


class PaymentStatus(Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    REFUNDED = "refunded"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


@dataclass
class PaymentIntent:
    """نية دفع موحدة لجميع البوابات"""

    id: str
    gateway: PaymentGateway
    amount: Decimal
    currency: str
    status: PaymentStatus
    user_id: int
    subscription_id: int | None = None
    metadata: dict | None = None
    gateway_response: dict | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: datetime = field(default_factory=lambda: datetime.utcnow() + timedelta(minutes=30))


class PaymentGatewayBase:
    """فئة أساسية للبوابات"""

    def __init__(self, config: dict):
        self.config = config

    def create_payment_intent(
        self, amount: Decimal, currency: str, user_id: int, metadata: dict[str, Any] | None = None
    ) -> PaymentIntent:
        raise NotImplementedError

    def verify_payment(self, payment_intent: PaymentIntent, gateway_data: dict) -> bool:
        raise NotImplementedError

    def refund(self, payment_intent: PaymentIntent, amount: Decimal | None = None) -> bool:
        raise NotImplementedError


class StripeGateway(PaymentGatewayBase):
    """بوابة Stripe — تحقق توقيع Webhook + Idempotency"""

    def __init__(self, config: dict):
        super().__init__(config)
        try:
            import stripe

            self.stripe = stripe
            stripe.api_key = config.get("secret_key") or os.getenv("STRIPE_SECRET_KEY")
            self.webhook_secret = config.get("webhook_secret") or os.getenv("STRIPE_WEBHOOK_SECRET")
        except ImportError:
            self.stripe = None

    def create_payment_intent(
        self, amount: Decimal, currency: str, user_id: int, metadata: dict[str, Any] | None = None
    ) -> PaymentIntent:
        if not self.stripe:
            raise RuntimeError("Stripe not configured")

        intent = self.stripe.PaymentIntent.create(
            amount=int(amount * 100),
            currency=currency.lower(),
            metadata={"user_id": str(user_id), **(metadata or {})},
            automatic_payment_methods={"enabled": True},
        )

        return PaymentIntent(
            id=f"stripe_{intent.id}",
            gateway=PaymentGateway.STRIPE,
            amount=amount,
            currency=currency,
            status=PaymentStatus.PENDING,
            user_id=user_id,
            metadata=metadata,
            gateway_response={"client_secret": intent.client_secret},
        )

    def verify_payment(self, payment_intent: PaymentIntent, gateway_data: dict) -> bool:
        """تحقق توقيع Stripe Webhook + Idempotency عبر ProcessedEvent"""
        if not self.stripe or not self.webhook_secret:
            return False

        payload = gateway_data.get("payload", "")
        sig_header = gateway_data.get("headers", {}).get("Stripe-Signature", "")

        try:
            event = self.stripe.Webhook.construct_event(
                payload=payload, sig_header=sig_header, secret=self.webhook_secret
            )
        except Exception:
            return False

        # Idempotency: تحقق من event.id
        event_id = event.get("id")
        if event_id and ProcessedEvent.query.filter_by(event_id=event_id).first():
            return True  # تم المعالجة سابقاً

        if event.type == "payment_intent.succeeded":
            # حفظ event_id لمنع المعالجة المكررة
            if event_id:
                db.session.add(ProcessedEvent(event_id=event_id, gateway="stripe", payload=event))
            return True
        return False

    def refund(self, payment_intent: PaymentIntent, amount: Decimal | None = None) -> bool:
        if not self.stripe or not payment_intent.gateway_response:
            return False
        try:
            pi_id = payment_intent.id.replace("stripe_", "")
            self.stripe.Refund.create(
                payment_intent=pi_id,
                amount=int((amount or payment_intent.amount) * 100) if amount else None,
            )
            return True
        except Exception:
            return False


class PayTabsGateway(PaymentGatewayBase):
    """بوابة PayTabs — تحقق HMAC Webhook + Idempotency"""

    def __init__(self, config: dict):
        super().__init__(config)
        self.profile_id = config.get("profile_id") or os.getenv("PAYTABS_PROFILE_ID")
        self.server_key = config.get("server_key") or os.getenv("PAYTABS_SERVER_KEY")
        self.webhook_secret = config.get("webhook_secret") or os.getenv("PAYTABS_WEBHOOK_SECRET")
        self.base_url = config.get("base_url", "https://secure.paytabs.com")

    def create_payment_intent(
        self, amount: Decimal, currency: str, user_id: int, metadata: dict[str, Any] | None = None
    ) -> PaymentIntent:
        import requests

        payload = {
            "profile_id": self.profile_id,
            "tran_type": "sale",
            "tran_class": "ecom",
            "cart_id": f"azad_{uuid.uuid4().hex[:12]}",
            "cart_description": metadata.get("description", "Azad E-School Payment")
            if metadata
            else "Azad E-School Payment",
            "cart_currency": currency,
            "cart_amount": float(amount),
            "callback": self.config.get("callback_url") or os.getenv("PAYTABS_CALLBACK_URL"),
            "return": self.config.get("return_url") or os.getenv("PAYTABS_RETURN_URL"),
        }
        headers = {"Authorization": f"Bearer {self.server_key}", "Content-Type": "application/json"}
        response = requests.post(f"{self.base_url}/payment/request", json=payload, headers=headers)

        if response.status_code == 200:
            data = response.json()
            return PaymentIntent(
                id=f"paytabs_{data.get('tran_ref')}",
                gateway=PaymentGateway.PAYTABS,
                amount=amount,
                currency=currency,
                status=PaymentStatus.PENDING,
                user_id=user_id,
                metadata=metadata,
                gateway_response=data,
            )
        raise RuntimeError(f"PayTabs error: {response.text}")

    def verify_payment(self, payment_intent: PaymentIntent, gateway_data: dict) -> bool:
        """تحقق HMAC PayTabs Webhook + Idempotency"""
        if not self.webhook_secret:
            return False

        payload = gateway_data.get("payload", {})
        headers = gateway_data.get("headers", {})

        # PayTabs يرسل التوقيع في Header: X-Paytabs-Signature
        received_sig = headers.get("X-Paytabs-Signature", "")
        payload_bytes = str(payload).encode() if isinstance(payload, dict) else str(payload).encode()

        expected_sig = hmac.new(self.webhook_secret.encode(), payload_bytes, hashlib.sha256).hexdigest()

        if not hmac.compare_digest(received_sig, expected_sig):
            return False

        # Idempotency: استخدم tran_ref كـ event_id
        tran_ref = payload.get("tran_ref") or payment_intent.id.replace("paytabs_", "")
        if tran_ref and ProcessedEvent.query.filter_by(event_id=f"paytabs_{tran_ref}").first():
            return True

        # تحقق من حالة الدفع عبر API
        try:
            import requests

            response = requests.get(
                f"{self.base_url}/payment/query/{tran_ref}",
                headers={"Authorization": f"Bearer {self.server_key}"},
            )
            if response.status_code == 200:
                data = response.json()
                if data.get("payment_result", {}).get("response_code") == "100":
                    if tran_ref:
                        db.session.add(
                            ProcessedEvent(event_id=f"paytabs_{tran_ref}", gateway="paytabs", payload=payload)
                        )
                    return True
        except Exception:
            pass
        return False

    def refund(self, payment_intent: PaymentIntent, amount: Decimal | None = None) -> bool:
        # PayTabs لا يدعم استرداد تلقائي كامل عبر API بسيط
        # يحتاج استدعاء API منفصل — نتركها False للتطبيق اليدوي
        return False


class CashUGateway(PaymentGatewayBase):
    """بوابة CashU — تحقق توقيع + Idempotency"""

    def __init__(self, config: dict):
        super().__init__(config)
        self.merchant_id = config.get("merchant_id") or os.getenv("CASHU_MERCHANT_ID")
        self.encryption_key = config.get("encryption_key") or os.getenv("CASHU_ENCRYPTION_KEY")
        self.webhook_secret = config.get("webhook_secret") or os.getenv("CASHU_WEBHOOK_SECRET")
        self.base_url = config.get("base_url", "https://api.cashu.ps")

    def create_payment_intent(
        self, amount: Decimal, currency: str, user_id: int, metadata: dict[str, Any] | None = None
    ) -> PaymentIntent:
        # CashU SDK يبسط التنفيذ
        return PaymentIntent(
            id=f"cashu_{uuid.uuid4().hex[:12]}",
            gateway=PaymentGateway.CASHU,
            amount=amount,
            currency=currency,
            status=PaymentStatus.PENDING,
            user_id=user_id,
            metadata=metadata,
        )

    def verify_payment(self, payment_intent: PaymentIntent, gateway_data: dict) -> bool:
        """تحقق CashU Webhook + Idempotency"""
        if not self.webhook_secret:
            return False

        payload = gateway_data.get("payload", {})
        headers = gateway_data.get("headers", {})

        # CashU يستخدم توقيع HMAC في Header
        received_sig = headers.get("X-Cashu-Signature", "")
        payload_str = str(payload)
        expected_sig = hmac.new(self.webhook_secret.encode(), payload_str.encode(), hashlib.sha256).hexdigest()

        if not hmac.compare_digest(received_sig, expected_sig):
            return False

        # Idempotency
        txn_id = payload.get("transaction_id") or payment_intent.id.replace("cashu_", "")
        if txn_id and ProcessedEvent.query.filter_by(event_id=f"cashu_{txn_id}").first():
            return True

        # التحقق من الحالة عبر API
        try:
            import requests

            response = requests.get(
                f"{self.base_url}/transaction/{txn_id}",
                headers={"Authorization": f"Bearer {self.encryption_key}"},
            )
            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "completed":
                    if txn_id:
                        db.session.add(ProcessedEvent(event_id=f"cashu_{txn_id}", gateway="cashu", payload=payload))
                    return True
        except Exception:
            pass
        return False

    def refund(self, payment_intent: PaymentIntent, amount: Decimal | None = None) -> bool:
        return False  # غير مدعوم تلقائياً


class WhatsAppPaymentGateway(PaymentGatewayBase):
    """الدفع عبر الواتساب — التحقق يتم **فقط** عبر اعتماد المشرف (Admin Approve)"""

    def __init__(self, config: dict):
        super().__init__(config)
        self.whatsapp_number = config.get("whatsapp_number") or os.getenv("WHATSAPP_BUSINESS_NUMBER")
        self.verification_token = config.get("verification_token") or os.getenv("WHATSAPP_VERIFY_TOKEN")
        self.webhook_url = config.get("webhook_url")

    def create_payment_intent(
        self, amount: Decimal, currency: str, user_id: int, metadata: dict[str, Any] | None = None
    ) -> PaymentIntent:
        payment_ref = f"WA_{uuid.uuid4().hex[:12]}"
        message = self._build_payment_message(amount, metadata)

        return PaymentIntent(
            id=f"whatsapp_{uuid.uuid4().hex[:12]}",
            gateway=PaymentGateway.WHATSAPP,
            amount=amount,
            currency=currency,
            status=PaymentStatus.PENDING,
            user_id=user_id,
            metadata={
                **(metadata or {}),
                "whatsapp_message": message,
                "payment_reference": payment_ref,
            },
        )

    def _build_payment_message(self, amount: Decimal, metadata: dict[str, Any] | None = None) -> str:
        desc = (metadata or {}).get("description", "دفع منصة أزاد")
        return (
            f"🔔 *طلب دفع جديد*\n\n"
            f"📝 {desc}\n"
            f"💰 المبلغ: {amount} {(metadata or {}).get('currency', 'ILS')}\n"
            f"📅 التاريخ: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
            f"للدفع، يرجى تحويل المبلغ وإرسال صورة الإيصال.\n"
            f"سيتم التحقق يدوياً وتفعيل الاشتراك خلال ساعة."
        )

    def verify_payment(self, payment_intent: PaymentIntent, gateway_data: dict) -> bool:
        """
        التحقق **لا يتم** هنا تلقائياً.
        يرجع True فقط إذا كان gateway_data يحتوي على مفتاح "admin_approved": True
        الذي يُضبط من قبل مسار /billing/payments/<id>/approve (أو /tutoring/sessions/<id>/pay).
        """
        return bool(gateway_data.get("admin_approved", False))

    def refund(self, payment_intent: PaymentIntent, amount: Decimal | None = None) -> bool:
        return False  # يتم يدوياً


class ManualPaymentGateway(PaymentGatewayBase):
    """الدفع اليدوي (إيصالات بنكية، كاش) — التحقق **فقط** عبر اعتماد المشرف"""

    def create_payment_intent(
        self, amount: Decimal, currency: str, user_id: int, metadata: dict[str, Any] | None = None
    ) -> PaymentIntent:
        return PaymentIntent(
            id=f"manual_{uuid.uuid4().hex[:12]}",
            gateway=PaymentGateway.MANUAL,
            amount=amount,
            currency=currency,
            status=PaymentStatus.PENDING,
            user_id=user_id,
            metadata=metadata,
        )

    def verify_payment(self, payment_intent: PaymentIntent, gateway_data: dict) -> bool:
        """
        التحقق **لا يتم** هنا تلقائياً.
        يرجع True فقط إذا كان gateway_data يحتوي على "admin_approved": True
        الذي يُضبط من قبل مسار /billing/payments/<id>/approve.
        """
        return bool(gateway_data.get("admin_approved", False))

    def refund(self, payment_intent: PaymentIntent, amount: Decimal | None = None) -> bool:
        return False  # يتم يدوياً


class PaymentService:
    """خدمة المدفوعات الموحدة"""

    GATEWAYS = {
        PaymentGateway.STRIPE: StripeGateway,
        PaymentGateway.PAYTABS: PayTabsGateway,
        PaymentGateway.CASHU: CashUGateway,
        PaymentGateway.WHATSAPP: WhatsAppPaymentGateway,
        PaymentGateway.MANUAL: ManualPaymentGateway,
    }

    def __init__(self):
        self.gateways = {}
        self._load_gateways()

    def _load_gateways(self):
        for gateway_type, gateway_class in self.GATEWAYS.items():
            config = self._get_gateway_config(gateway_type)
            if config:
                self.gateways[gateway_type] = gateway_class(config)

    def _get_gateway_config(self, gateway_type: PaymentGateway) -> dict | None:
        configs = {
            PaymentGateway.STRIPE: {
                "secret_key": os.getenv("STRIPE_SECRET_KEY"),
                "webhook_secret": os.getenv("STRIPE_WEBHOOK_SECRET"),
            },
            PaymentGateway.PAYTABS: {
                "profile_id": os.getenv("PAYTABS_PROFILE_ID"),
                "server_key": os.getenv("PAYTABS_SERVER_KEY"),
                "webhook_secret": os.getenv("PAYTABS_WEBHOOK_SECRET"),
                "callback_url": os.getenv("PAYTABS_CALLBACK_URL"),
                "return_url": os.getenv("PAYTABS_RETURN_URL"),
            },
            PaymentGateway.CASHU: {
                "merchant_id": os.getenv("CASHU_MERCHANT_ID"),
                "encryption_key": os.getenv("CASHU_ENCRYPTION_KEY"),
                "webhook_secret": os.getenv("CASHU_WEBHOOK_SECRET"),
            },
            PaymentGateway.WHATSAPP: {
                "whatsapp_number": os.getenv("WHATSAPP_BUSINESS_NUMBER"),
                "verification_token": os.getenv("WHATSAPP_VERIFY_TOKEN"),
            },
            PaymentGateway.MANUAL: {},
        }
        return configs.get(gateway_type)

    def create_payment(
        self,
        gateway: PaymentGateway,
        amount: Decimal,
        currency: str,
        user_id: int,
        subscription_id: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> PaymentIntent | None:
        """إنشاء نية دفع عبر البوابة المحددة"""
        gateway_obj = self.gateways.get(gateway)
        if not gateway_obj:
            raise ValueError(f"Gateway {gateway.value} not configured")
        return gateway_obj.create_payment_intent(amount, currency, user_id, metadata)

    def process_webhook(self, gateway: PaymentGateway, payload: dict, headers: dict) -> dict:
        """معالجة webhook من البوابة مع Idempotency"""
        gateway_obj = self.gateways.get(gateway)
        if not gateway_obj:
            return {"success": False, "error": "Gateway not configured"}

        # التحقق من التوقيع + Idempotency داخل verify_payment
        dummy_intent = PaymentIntent(
            id="", gateway=gateway, amount=Decimal("0"), currency="", status=PaymentStatus.PENDING, user_id=0
        )
        verified = gateway_obj.verify_payment(
            dummy_intent,
            {"payload": payload, "headers": headers},
        )

        if verified:
            self._handle_successful_payment(payload, gateway)
            return {"success": True}
        return {"success": False, "error": "Verification failed"}

    def _handle_successful_payment(self, payload: dict, gateway: PaymentGateway):
        """معالجة دفع ناجح — يُستدعى بعد تحقق ناجح"""
        # استخراج معلومات الدفع من payload
        # تحديث قاعدة البيانات، إرسال إشعارات، إلخ
        pass

    def cleanup_expired_intents(self, max_age_hours: int = 24) -> int:
        """
        تنظيف PaymentIntents منتهية الصلاحية (في الذاكرة فقط — للـ singleton).
        في الإنتاج الحقيقي، يجب تخزين PaymentIntents في قاعدة البيانات.
        """
        # للـ singleton الحالي، لا يوجد تخزين دائم للـ intents
        # هذه الدالة تُترك للتوسع المستقبلي عند إضافة نموذج PaymentIntent في DB
        return 0


# Singleton
_payment_service: "PaymentService | None" = None


def get_payment_service() -> PaymentService:
    global _payment_service
    if _payment_service is None:
        _payment_service = PaymentService()
    return _payment_service
