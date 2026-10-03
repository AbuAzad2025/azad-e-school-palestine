"""نظام المدفوعات المتكامل — Stripe + بوابات محلية + WhatsApp + يدوي

الأمان: تحقق توقيع Webhook، Idempotency، تحقق ملكية، تحقق مبلغ.
"""

import os
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING, Any

from app.core.logging import get_logger
from app.core.webhooks import header_value, verify_hmac_webhook
from app.extensions import db
from app.models.billing import ProcessedEvent

if TYPE_CHECKING:
    from app.models.billing import Subscription

logger = get_logger(__name__)


# ---- Fraud Detection Configuration ----
FRAUD_THRESHOLD_MULTIPLIER = 3
FRAUD_LOOKBACK_DAYS = 90


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


@dataclass(frozen=True)
class WebhookVerification:
    """نتيجة التحقق من webhook — تفصل بين «موقّع» و«سبق معالجته».

    الفصل جوهري: الدالة القديمة كانت تُرجع ``True`` في الحالتين، فلم فرّق
    ``process_webhook`` بينهما وأعاد تطبيق التفعيل والدفتر والإيميل على
    الحدث المكرر — أي تفعيل مزدوج من إعادة إرسال واحدة.
    """

    verified: bool
    event_id: str | None = None
    already_processed: bool = False
    reason: str = ""

    def __bool__(self) -> bool:
        return self.verified


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
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime = field(default_factory=lambda: datetime.now(UTC) + timedelta(minutes=30))


class PaymentGatewayBase:
    """فئة أساسية للبوابات"""

    def __init__(self, config: dict):
        self.config = config

    def create_payment_intent(
        self, amount: Decimal, currency: str, user_id: int, metadata: dict[str, Any] | None = None
    ) -> PaymentIntent:
        raise NotImplementedError

    def verify_payment(self, payment_intent: PaymentIntent, gateway_data: dict) -> bool:
        """واجهة توافقية (قائمة) — تستدعي ``verify_webhook`` وتُرجع ``verified``."""
        return bool(self.verify_webhook(gateway_data))

    def verify_webhook(self, gateway_data: dict) -> WebhookVerification:
        """التحقق الكامل (توقيع + idمعرّف الحدث + حالة المعالجة السابقة).

        ``gateway_data`` يحمل ``raw_body`` (بايتات الطلب الخام) و``headers``
        و``payload``. كل تنفيذ يعيد نتيجة صريحة بدل bool مبهمة.
        """
        raise NotImplementedError

    def refund(self, payment_intent: PaymentIntent, amount: Decimal | None = None) -> bool:
        raise NotImplementedError

    # ── مساعدات مشتركة للبوابات القائمة ──────────────────────────────
    @staticmethod
    def _event_already_processed(event_id: str | None) -> bool:
        if not event_id:
            return False
        return ProcessedEvent.query.filter_by(event_id=event_id).first() is not None

    @staticmethod
    def _remember_event(event_id: str, gateway: str, payload: dict) -> None:
        db.session.add(ProcessedEvent(event_id=event_id, gateway=gateway, payload=payload))


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

    def verify_webhook(self, gateway_data: dict) -> WebhookVerification:
        if not self.stripe or not self.webhook_secret:
            return WebhookVerification(verified=False, reason="stripe_not_configured")

        payload = gateway_data.get("payload", "")
        headers = gateway_data.get("headers", {})
        sig_header = header_value(headers, "Stripe-Signature")

        try:
            event = self.stripe.Webhook.construct_event(
                payload=payload, sig_header=sig_header, secret=self.webhook_secret
            )
        except Exception:
            logger.warning("stripe_webhook_signature_invalid", action="reject")
            return WebhookVerification(verified=False, reason="signature_invalid")

        if event.get("type") != "payment_intent.succeeded":
            return WebhookVerification(verified=False, reason="event_type_ignored")

        event_id = event.get("id")
        if self._event_already_processed(event_id):
            return WebhookVerification(
                verified=True, event_id=event_id, already_processed=True, reason="duplicate_event"
            )

        if event_id:
            self._remember_event(event_id, "stripe", event)
        return WebhookVerification(verified=True, event_id=event_id, reason="signature_valid")

    def refund(self, payment_intent: PaymentIntent, amount: Decimal | None = None) -> bool:
        if not self.stripe or not payment_intent.gateway_response:
            return False
        try:
            pi_id = payment_intent.id.replace("stripe_", "")
            self.stripe.Refund.create(
                payment_intent=pi_id,
                amount=int((amount or payment_intent.amount) * 100),
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
        response = requests.post(f"{self.base_url}/payment/request", json=payload, headers=headers, timeout=(3, 27))

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

    def verify_webhook(self, gateway_data: dict) -> WebhookVerification:
        if not self.webhook_secret:
            return WebhookVerification(verified=False, reason="webhook_secret_missing")

        payload = gateway_data.get("payload") or {}
        headers = gateway_data.get("headers") or {}

        # PayTabs يوقّع على جسم الطلب الخام: X-Paytabs-Signature
        if not verify_hmac_webhook(
            secret=self.webhook_secret,
            headers=headers,
            header_name="X-Paytabs-Signature",
            raw_body=gateway_data.get("raw_body"),
            payload=payload,
            gateway="paytabs",
        ):
            return WebhookVerification(verified=False, reason="signature_invalid")

        tran_ref = str(payload.get("tran_ref") or "").strip()
        if not tran_ref:
            return WebhookVerification(verified=False, reason="missing_tran_ref")

        event_id = f"paytabs_{tran_ref}"
        if self._event_already_processed(event_id):
            return WebhookVerification(
                verified=True, event_id=event_id, already_processed=True, reason="duplicate_event"
            )

        # تحقق من حالة الدفع عبر API
        try:
            import requests

            response = requests.get(
                f"{self.base_url}/payment/query/{tran_ref}",
                headers={"Authorization": f"Bearer {self.server_key}"},
                timeout=(3, 27),
            )
            if response.status_code == 200:
                data = response.json()
                if data.get("payment_result", {}).get("response_code") == "100":
                    self._remember_event(event_id, "paytabs", payload)
                    return WebhookVerification(verified=True, event_id=event_id, reason="signature_valid")
        except Exception:
            logger.exception("PayTabs verification API call failed")
        return WebhookVerification(verified=False, event_id=event_id, reason="gateway_query_failed")

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

    def verify_webhook(self, gateway_data: dict) -> WebhookVerification:
        if not self.webhook_secret:
            return WebhookVerification(verified=False, reason="webhook_secret_missing")

        payload = gateway_data.get("payload") or {}
        headers = gateway_data.get("headers") or {}

        if not verify_hmac_webhook(
            secret=self.webhook_secret,
            headers=headers,
            header_name="X-Cashu-Signature",
            raw_body=gateway_data.get("raw_body"),
            payload=payload,
            gateway="cashu",
        ):
            return WebhookVerification(verified=False, reason="signature_invalid")

        txn_id = str(payload.get("transaction_id") or "").strip()
        if not txn_id:
            return WebhookVerification(verified=False, reason="missing_transaction_id")

        event_id = f"cashu_{txn_id}"
        if self._event_already_processed(event_id):
            return WebhookVerification(
                verified=True, event_id=event_id, already_processed=True, reason="duplicate_event"
            )

        # التحقق من الحالة عبر API
        try:
            import requests

            response = requests.get(
                f"{self.base_url}/transaction/{txn_id}",
                headers={"Authorization": f"Bearer {self.encryption_key}"},
                timeout=(3, 27),
            )
            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "completed":
                    self._remember_event(event_id, "cashu", payload)
                    return WebhookVerification(verified=True, event_id=event_id, reason="signature_valid")
        except Exception:
            logger.exception("CashU verification API call failed")
        return WebhookVerification(verified=False, event_id=event_id, reason="gateway_query_failed")

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

    def verify_webhook(self, gateway_data: dict) -> WebhookVerification:
        """التحقق **لا يتم** هنا تلقائياً.

        مصادَق فقط عندما يحمل ``gateway_data`` مفتاح ``admin_approved: True``
        الذي يضبطه مسار /billing/payments/<id>/approve أو /tutoring/sessions/<id>/pay.
        """
        approved = bool(gateway_data.get("admin_approved", False))
        return WebhookVerification(
            verified=approved,
            event_id=str(gateway_data.get("event_id") or "") or None,
            already_processed=bool(gateway_data.get("already_processed", False)),
            reason="admin_approved" if approved else "manual_review_required",
        )

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

    def verify_webhook(self, gateway_data: dict) -> WebhookVerification:
        """الدفع اليدوي (إيصال بنكي/كاش) — مصادَق باعتماد المشرف فقط."""
        approved = bool(gateway_data.get("admin_approved", False))
        return WebhookVerification(
            verified=approved,
            event_id=str(gateway_data.get("event_id") or "") or None,
            already_processed=bool(gateway_data.get("already_processed", False)),
            reason="admin_approved" if approved else "manual_review_required",
        )

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

    def _get_gateway_config(self, gateway_type: PaymentGateway) -> dict[str, Any] | None:
        configs: dict[PaymentGateway, dict[str, Any]] = {
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
            PaymentGateway.MANUAL: {"enabled": True},
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
        log = logger.bind(service="payments", user_id=user_id, gateway=gateway.value)
        log.info("create_payment_called", amount=str(amount), currency=currency)
        gateway_obj = self.gateways.get(gateway)
        if not gateway_obj:
            log.error("gateway_not_configured", gateway=gateway.value)
            raise ValueError(f"Gateway {gateway.value} not configured")
        return gateway_obj.create_payment_intent(amount, currency, user_id, metadata)

    def process_webhook(
        self,
        gateway: PaymentGateway,
        payload: dict,
        headers: dict,
        raw_body: bytes | None = None,
    ) -> dict:
        """معالجة webhook من البوابة مع Idempotency.

        ``raw_body`` هو جسم الطلب الخام كما وقّع عليه المرسِل — نمرّره دائماً
        لأن إعادة ترميز ``payload`` تعطي بايتات قد لا تطابق توقيع مشروع legit.
        """
        log = logger.bind(service="payments", gateway=gateway.value)
        log.info("process_webhook_called")
        gateway_obj = self.gateways.get(gateway)
        if not gateway_obj:
            return {"success": False, "error": "Gateway not configured"}

        result = gateway_obj.verify_webhook({"payload": payload, "headers": headers, "raw_body": raw_body})

        if not result.verified:
            log.warning("webhook_rejected", reason=result.reason)
            return {"success": False, "error": "Verification failed"}

        if result.already_processed:
            # حدث سبق أن عولج: لا نُعيد التفعيل ولا الدفتر ولا الإيميل.
            log.info("webhook_duplicate_ignored", event_id=result.event_id)
            return {"success": True, "duplicate": True, "event_id": result.event_id}

        self._handle_successful_payment(payload, gateway)
        # الاستجابة توافق العقد السابق {"success": True}؛ معرّف الحدث يُكشف
        # في فرع التكرار فقط حيث يفيد المُحيل (لا يعيد المحاولة).
        return {"success": True}

    def _handle_successful_payment(self, payload: dict, gateway: PaymentGateway):
        """معالجة دفع ناجح — يُستدعى بعد تحقق ناجح"""
        from app.extensions import db
        from app.models.billing import Subscription
        from app.services.billing import _activate
        from app.services.communication import audit
        from app.services.email import send_payment_approved_email

        # استخراج معلومات الدفع من payload حسب البوابة
        subscription_id = self._extract_subscription_id(payload, gateway)
        if not subscription_id:
            logger.warning(f"Could not extract subscription_id from {gateway.value} payload")
            return

        # P0-10: FOR UPDATE على الاشتراك لمنع التفعيل المزدوج
        subscription = db.session.execute(
            db.select(Subscription).where(Subscription.id == subscription_id).with_for_update()
        ).scalar_one_or_none()
        if not subscription:
            logger.warning(f"Subscription {subscription_id} not found")
            return

        amount = self._extract_amount(payload, gateway)
        if amount is None:
            logger.warning(f"Could not extract amount from {gateway.value} payload")
            return

        # fail-closed: لا تفعيل إلا بمبلغ العملة المتفق عليها. بدون هذا الفحص
        # يكفي webhook موقع لـ 1 شيكل لتفعيل خطة بـ 500 (الاشتراك مُقفل بـ
        # FOR UPDATE لكنه غير مُتحقَّق من قيمته).
        currency = self._extract_currency(payload, gateway)
        mismatch = self._payment_mismatch(subscription, amount, currency)
        if mismatch:
            self._flag_for_review(
                subscription,
                title="دفع غير مطابق يتطلب مراجعة",
                body=(
                    f"اشتراك #{subscription.id}: توقّعنا {subscription.price} "
                    f"{subscription.currency} ووصل {amount} {currency or '—'} ({mismatch})"
                ),
            )
            return

        # احتيال: تحقق مما إذا كان المبلغ > 3x المتوسط لـ 90 يوماً
        # الحصول على school_id عبر class_id أو plan
        school_id = None
        if subscription.class_id:
            from app.models.class_room import ClassRoom

            class_room = db.session.get(ClassRoom, subscription.class_id)
            if class_room:
                school_id = class_room.school_id
        if not school_id and subscription.plan_id:
            from app.models.billing import SubscriptionPlan

            plan = db.session.get(SubscriptionPlan, subscription.plan_id)
            if plan:
                school_id = plan.school_id

        if school_id and self._is_suspicious_amount(school_id, amount):
            self._flag_for_review(
                subscription,
                title="دفع مشبوه يتطلب مراجعة",
                body=f"اشتراك #{subscription.id} بمبلغ {amount} يتطلب مراجعة يدوية",
            )
            return

        # تفعيل الاشتراك
        _activate(subscription, auto_activate=True)

        # إنشاء إدخال في الدفتر المحاسبي (ledger credit)
        self._create_ledger_entry(subscription, amount, gateway)

        # إرسال إيميل إيصال
        try:
            send_payment_approved_email(subscription.payments[-1] if subscription.payments else None)
        except Exception:
            logger.exception("Failed to send payment approved email")

        # تسجيل تدقيق
        audit(
            "billing.gateway_auto_activate",
            "subscriptions",
            subscription.id,
            amount=float(amount),
            currency=subscription.currency,
            gateway=gateway.value,
            subscription_id=subscription.id,
        )

        logger.info(f"Subscription {subscription_id} auto-activated via {gateway.value} for amount {amount}")

    def _flag_for_review(self, subscription: "Subscription", title: str, body: str) -> None:
        """علم الاشتراك «يحتاج مراجعة» + إشعار المشرفين — بلا تفعيل.

        مسار المراجعة اليدوية (مبلغ غير مطابق أو مشبوه). الكتابة ذرّية عبر
        ``tx()``، والإشعار أثر جانبي بعد الالتزام.
        """
        from app.core.db import tx

        def _flag():
            subscription.status = "pending_review"

        tx(_flag)
        logger.warning("subscription_flagged_for_review", subscription_id=subscription.id, detail=body)

        from app.models.user import User, UserRole
        from app.services.communication import notify

        admins = User.query.filter(User.role.in_([UserRole.super_admin, UserRole.school_admin])).all()
        for admin in admins:
            notify(admin.id, "payment_review", title, body)

    @staticmethod
    def _payment_mismatch(
        subscription: "Subscription",
        amount: Decimal,
        currency: str | None,
    ) -> str | None:
        """سبب عدم مطابقة المبلغ (أو ``None`` إذا طابق).

        المقارنة على منزلتين عشريتين لأن ``Numeric(10,2)`` يُقرَّب عند
        التخزين؛ والعملة حساسة لحالة الأحرف (ILS ≠ ils في المقارنة النصية
        لكن البوابات ترسلها variously).
        """
        try:
            expected = Decimal(str(subscription.price)).quantize(Decimal("0.01"))
        except (ArithmeticError, TypeError, ValueError):
            return "unreadable_expected_price"

        paid = amount.quantize(Decimal("0.01"))
        if paid < expected:
            return "underpaid"
        if paid > expected:
            return "overpaid"

        expected_currency = (subscription.currency or "").strip().upper()
        received_currency = (currency or "").strip().upper()
        if received_currency and expected_currency and received_currency != expected_currency:
            return "currency_mismatch"
        return None

    def _extract_currency(self, payload: dict, gateway: PaymentGateway) -> str | None:
        """استخراج عملة الدفع من payload حسب البوابة."""
        if gateway == PaymentGateway.STRIPE:
            pi = payload.get("data", {}).get("object", {})
            currency = pi.get("currency")
            return str(currency) if currency else None
        if gateway == PaymentGateway.PAYTABS:
            currency = payload.get("cart_currency") or payload.get("currency")
            return str(currency) if currency else None
        if gateway == PaymentGateway.CASHU:
            currency = payload.get("currency")
            return str(currency) if currency else None
        return None

    def _extract_subscription_id(self, payload: dict, gateway: PaymentGateway) -> int | None:
        """استخراج subscription_id من payload حسب البوابة"""
        if gateway == PaymentGateway.STRIPE:
            # Stripe: metadata.subscription_id
            pi = payload.get("data", {}).get("object", {})
            return int(pi.get("metadata", {}).get("subscription_id", 0)) or None
        elif gateway == PaymentGateway.PAYTABS:
            # PayTabs: cart_id أو metadata
            return int(payload.get("metadata", {}).get("subscription_id", 0)) or None
        elif gateway == PaymentGateway.CASHU:
            # CashU: metadata
            return int(payload.get("metadata", {}).get("subscription_id", 0)) or None
        elif gateway in (PaymentGateway.WHATSAPP, PaymentGateway.MANUAL):
            # WhatsApp/Manual: لا يتم تفعيل تلقائي
            return None
        return None

    def _extract_amount(self, payload: dict, gateway: PaymentGateway) -> Decimal | None:
        """استخراج المبلغ من payload حسب البوابة"""
        if gateway == PaymentGateway.STRIPE:
            pi = payload.get("data", {}).get("object", {})
            amount = pi.get("amount_received") or pi.get("amount")
            if amount:
                return Decimal(str(amount)) / 100
        elif gateway == PaymentGateway.PAYTABS:
            amount = payload.get("cart_amount") or payload.get("amount")
            if amount:
                return Decimal(str(amount))
        elif gateway == PaymentGateway.CASHU:
            amount = payload.get("amount")
            if amount:
                return Decimal(str(amount))
        return None

    def _is_suspicious_amount(self, school_id: int, amount: Decimal) -> bool:
        """كشف الاحتيال: المبلغ > 3x المتوسط لـ 90 يوماً"""
        from sqlalchemy import func

        from app.models.billing import ManualPayment, Subscription, SubscriptionPlan

        try:
            # حساب متوسط المدفوعات المعتمدة للمدرسة في آخر 90 يوماً
            cutoff = datetime.now() - timedelta(days=FRAUD_LOOKBACK_DAYS)
            avg_amount = (
                db.session.query(func.avg(ManualPayment.amount))
                .join(Subscription, ManualPayment.subscription_id == Subscription.id)
                .join(SubscriptionPlan, Subscription.plan_id == SubscriptionPlan.id)
                .filter(
                    SubscriptionPlan.school_id == school_id,
                    ManualPayment.status == "approved",
                    ManualPayment.created_at >= cutoff,
                )
                .scalar()
            )

            if avg_amount is None:
                return False  # لا توجد بيانات سابقة للمقارنة

            avg_decimal = Decimal(str(avg_amount))
            threshold = avg_decimal * FRAUD_THRESHOLD_MULTIPLIER
            return amount > threshold
        except Exception:
            logger.exception("Fraud detection check failed")
            return False

    def _create_ledger_entry(self, subscription: "Subscription", amount: Decimal, gateway: PaymentGateway):
        """إنشاء إدخال دفتر محاسبي (ledger credit) — via tx() for atomic safety."""
        from app.core.db import tx
        from app.models.billing import ManualPayment

        # البحث عن الدفع اليدوي المقابل أو إنشاء سجل جديد
        payment = (
            ManualPayment.query.filter_by(
                subscription_id=subscription.id,
                status="approved",
            )
            .order_by(ManualPayment.created_at.desc())
            .first()
        )

        if payment:

            def _update_ledger():
                payment.gateway = gateway.value
                payment.amount = float(amount)

            tx(_update_ledger)

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
