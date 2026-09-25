"""Batch 5 — بوابة المدفوعات app/services/payments.py (فجوات مؤكدة 38%).

التغطية:
- PaymentIntent / enums
- StripeGateway: بلا مفتاح (create/verify/refund)، توقيع webhook صحيح/خاطئ،
  Idempotency (event مكرر)، إنشاء intent ناجح، refund.
- PayTabsGateway: بلا secret (verify)، توقيع HMAC صحيح/خاطئ، idempotency،
  استعلام API ناجح/فاشل، refund False.
- CashUGateway: بلا secret، توقيع صحيح/خاطئ، idempotency، API نجاح، refund.
- WhatsApp/Manual: admin_approved فقط.
- PaymentService: create_payment غير مهيأة ترفع، process_webhook بلا بوابة،
  process_webhook موقّع يفعّل اشتراكاً حقيقياً، fraud flag عبر process_webhook
  (مبلغ مشبوه → pending_review + إشعارات)، extract helpers، _is_suspicious_amount
  مباشرة، _create_ledger_entry.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from app.services.payments import (
    CashUGateway,
    ManualPaymentGateway,
    PaymentGateway,
    PaymentIntent,
    PaymentService,
    PaymentStatus,
    PayTabsGateway,
    StripeGateway,
    WhatsAppPaymentGateway,
    get_payment_service,
)

# ═══════════════════════════════════════════════════════════════════════════
# PaymentIntent
# ═════════════════════════════_H Marker ═════════════════════════════════════


def test_payment_intent_defaults():
    intent = PaymentIntent(
        id="x_1",
        gateway=PaymentGateway.STRIPE,
        amount=Decimal("10"),
        currency="ils",
        status=PaymentStatus.PENDING,
        user_id=1,
    )
    assert intent.metadata is None
    assert intent.gateway_response is None
    assert intent.created_at.tzinfo is not None
    assert intent.expires_at > intent.created_at


# ═══════════════════════════════════════════════════════════════════════════
# StripeGateway
# ═══════════════════════════════════ ` ═════════════════════


class _FakeStripeEvent(dict):
    """يشبه StripeObject: وصول dict ووصول صفّي معاً."""

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name) from None


def _stripe_mock():
    """stripe module وهمي مع Webhook.construct_event وPaymentIntent/Refund."""
    stripe = MagicMock()
    event = _FakeStripeEvent({"id": f"evt_{uuid.uuid4().hex[:10]}", "type": "payment_intent.succeeded"})
    stripe.Webhook.construct_event.return_value = event
    pi = MagicMock()
    pi.id = f"pi_{uuid.uuid4().hex[:14]}"
    pi.client_secret = "cs_test"
    stripe.PaymentIntent.create.return_value = pi
    return stripe, event


def _stripe_gw(config):
    """StripeGateway مع ضبط webhook_secret يدوياً (قد لا يكون stripe مثبتاً)."""
    gw = StripeGateway(config)
    if not hasattr(gw, "webhook_secret") or gw.webhook_secret is None:
        gw.webhook_secret = config.get("webhook_secret")
    return gw


class TestStripeGateway:
    def test_no_stripe_package(self):
        """إذا كان stripe مثبتاً فعلاً، نفرض ImportError عبر sys.modules."""
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "stripe":
                raise ImportError("forced")
            return real_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", fake_import):
            gw = StripeGateway({})
        assert gw.stripe is None
        with pytest.raises(RuntimeError, match="not configured"):
            gw.create_payment_intent(Decimal("10"), "ILS", 1)
        assert (
            gw.verify_payment(
                PaymentIntent("i", PaymentGateway.STRIPE, Decimal("1"), "ILS", PaymentStatus.PENDING, 1), {}
            )
            is False
        )
        assert (
            gw.refund(PaymentIntent("stripe_x", PaymentGateway.STRIPE, Decimal("1"), "ILS", PaymentStatus.PENDING, 1))
            is False
        )

    def test_verify_no_webhook_secret(self, app):
        gw = StripeGateway({"secret_key": "sk_test"})
        gw.webhook_secret = None
        intent = PaymentIntent("i", PaymentGateway.STRIPE, Decimal("1"), "ILS", PaymentStatus.PENDING, 1)
        assert gw.verify_payment(intent, {"payload": b"{}", "headers": {}}) is False

    def test_verify_bad_signature(self, app):
        stripe, event = _stripe_mock()
        stripe.Webhook.construct_event.side_effect = Exception("bad signature")
        gw = _stripe_gw({"secret_key": "sk", "webhook_secret": "whsec"})
        gw.stripe = stripe
        intent = PaymentIntent("i", PaymentGateway.STRIPE, Decimal("1"), "ILS", PaymentStatus.PENDING, 1)
        with app.app_context():
            assert gw.verify_payment(intent, {"payload": b"x", "headers": {"Stripe-Signature": "bad"}}) is False

    def test_verify_success_and_idempotency(self, app):
        from app.extensions import db
        from app.models.billing import ProcessedEvent

        stripe, event = _stripe_mock()
        gw = _stripe_gw({"secret_key": "sk", "webhook_secret": "whsec"})
        gw.stripe = stripe
        intent = PaymentIntent("i", PaymentGateway.STRIPE, Decimal("1"), "ILS", PaymentStatus.PENDING, 1)
        data = {"payload": b"raw", "headers": {"Stripe-Signature": "sig"}}
        with app.app_context():
            assert gw.verify_payment(intent, data) is True
            assert db.session.query(ProcessedEvent).filter_by(event_id=event["id"]).count() == 1
            # مرة ثانية — idempotent: يعيد True دون إضافة صف
            assert gw.verify_payment(intent, data) is True
            assert db.session.query(ProcessedEvent).filter_by(event_id=event["id"]).count() == 1

    def test_verify_other_event_type(self, app):
        stripe, event = _stripe_mock()
        event["type"] = "charge.refunded"
        gw = _stripe_gw({"secret_key": "sk", "webhook_secret": "whsec"})
        gw.stripe = stripe
        intent = PaymentIntent("i", PaymentGateway.STRIPE, Decimal("1"), "ILS", PaymentStatus.PENDING, 1)
        with app.app_context():
            assert gw.verify_payment(intent, {"payload": b"r", "headers": {}}) is False

    def test_verify_no_event_id(self, app):
        from app.models.billing import ProcessedEvent

        stripe, event = _stripe_mock()
        event.pop("id")
        gw = _stripe_gw({"secret_key": "sk", "webhook_secret": "whsec"})
        gw.stripe = stripe
        intent = PaymentIntent("i", PaymentGateway.STRIPE, Decimal("1"), "ILS", PaymentStatus.PENDING, 1)
        with app.app_context():
            assert gw.verify_payment(intent, {"payload": b"r", "headers": {}}) is True
            # بلا event_id لا يُخزّن شيء للمعالجة المكررة
            assert ProcessedEvent.query.count() == 0

    def test_create_intent_success(self, app):
        stripe, _ = _stripe_mock()
        gw = StripeGateway({"secret_key": "sk"})
        gw.stripe = stripe
        intent = gw.create_payment_intent(Decimal("12.34"), "ILS", 7, metadata={"subscription_id": "9"})
        assert intent.id.startswith("stripe_")
        assert intent.gateway_response == {"client_secret": "cs_test"}
        assert stripe.PaymentIntent.create.call_args.kwargs["amount"] == 1234
        assert stripe.PaymentIntent.create.call_args.kwargs["metadata"]["subscription_id"] == "9"

    def test_refund_success_and_failure(self, app):
        stripe, _ = _stripe_mock()
        gw = StripeGateway({"secret_key": "sk"})
        gw.stripe = stripe
        intent = PaymentIntent(
            "stripe_pi_x",
            PaymentGateway.STRIPE,
            Decimal("20"),
            "ILS",
            PaymentStatus.PENDING,
            1,
            gateway_response={"client_secret": "cs"},
        )
        assert gw.refund(intent) is True
        assert stripe.Refund.create.call_args.kwargs["payment_intent"] == "pi_x"
        assert stripe.Refund.create.call_args.kwargs["amount"] == 2000
        # مبلغ جزئي
        assert gw.refund(intent, Decimal("5")) is True
        assert stripe.Refund.create.call_args.kwargs["amount"] == 500
        # فشل
        stripe.Refund.create.side_effect = Exception("fail")
        assert gw.refund(intent) is False
        # بلا gateway_response
        bare = PaymentIntent("stripe_pi_x", PaymentGateway.STRIPE, Decimal("20"), "ILS", PaymentStatus.PENDING, 1)
        assert gw.refund(bare) is False


# ═════════ slop marker ═════════════════════════════════════════════════════
# PayTabsGateway
# ═══════════════════════════════════════════════════════════════════════════


class TestPayTabsGateway:
    def _gw(self, secret="s3cret"):
        return PayTabsGateway({"profile_id": "pt", "server_key": "sk", "webhook_secret": secret})

    def test_verify_no_secret(self):
        gw = self._gw(None)
        intent = PaymentIntent("paytabs_T1", PaymentGateway.PAYTABS, Decimal("1"), "ILS", PaymentStatus.PENDING, 1)
        assert gw.verify_payment(intent, {"payload": {}, "headers": {}}) is False

    def _signed(self, gw, payload):
        body = json.dumps(payload, sort_keys=True).encode()
        sig = hmac.new(gw.webhook_secret.encode(), body, hashlib.sha256).hexdigest()
        return {"payload": payload, "headers": {"X-Paytabs-Signature": sig}}

    def test_verify_success_first_time(self, app):
        from app.extensions import db
        from app.models.billing import ProcessedEvent

        gw = self._gw()
        tran_ref = f"T{uuid.uuid4().hex[:8]}"
        payload = {"tran_ref": tran_ref, "cart_amount": 100}
        intent = PaymentIntent(
            f"paytabs_{tran_ref}", PaymentGateway.PAYTABS, Decimal("100"), "ILS", PaymentStatus.PENDING, 1
        )
        with app.app_context(), patch("requests.get") as get:
            get.return_value = MagicMock(status_code=200, json=lambda: {"payment_result": {"response_code": "100"}})
            assert gw.verify_payment(intent, self._signed(gw, payload)) is True
            assert db.session.query(ProcessedEvent).filter_by(event_id=f"paytabs_{tran_ref}").count() == 1

    def test_verify_success_idempotent_repeat(self, app):
        from app.models.billing import ProcessedEvent

        gw = self._gw()
        tran_ref = f"T{uuid.uuid4().hex[:8]}"
        payload = {"tran_ref": tran_ref}
        intent = PaymentIntent(
            f"paytabs_{tran_ref}", PaymentGateway.PAYTABS, Decimal("100"), "ILS", PaymentStatus.PENDING, 1
        )
        with app.app_context():
            db_rows = ProcessedEvent.query.filter_by(event_id=f"paytabs_{tran_ref}").first()
            assert db_rows is None
            # معالجة مسبقة: أدرج الحدث يدوياً ثم تحقق — يجب أن يعيد True فوراً
            from app.extensions import db

            db.session.add(ProcessedEvent(event_id=f"paytabs_{tran_ref}", gateway="paytabs", payload={}))
            db.session.commit()
            # لا API call
            with patch("requests.get") as get:
                assert gw.verify_payment(intent, self._signed(gw, payload)) is True
                get.assert_not_called()

    def test_verify_bad_signature(self):
        gw = self._gw()
        payload = {"tran_ref": "TX"}
        data = {"payload": payload, "headers": {"X-Paytabs-Signature": "wrong"}}
        intent = PaymentIntent("paytabs_TX", PaymentGateway.PAYTABS, Decimal("1"), "ILS", PaymentStatus.PENDING, 1)
        assert gw.verify_payment(intent, data) is False

    def test_verify_api_error(self, app):
        gw = self._gw()
        tran_ref = f"T{uuid.uuid4().hex[:8]}"
        payload = {"tran_ref": tran_ref}
        intent = PaymentIntent(
            f"paytabs_{tran_ref}", PaymentGateway.PAYTABS, Decimal("1"), "ILS", PaymentStatus.PENDING, 1
        )
        with app.app_context(), patch("requests.get") as get:
            get.return_value = MagicMock(status_code=500)
            assert gw.verify_payment(intent, self._signed(gw, payload)) is False

    def test_verify_api_exception(self, app):
        gw = self._gw()
        tran_ref = f"T{uuid.uuid4().hex[:8]}"
        payload = {"tran_ref": tran_ref}
        intent = PaymentIntent(
            f"paytabs_{tran_ref}", PaymentGateway.PAYTABS, Decimal("1"), "ILs".upper(), PaymentStatus.PENDING, 1
        )
        with app.app_context(), patch("requests.get", side_effect=RuntimeError("boom")):
            assert gw.verify_payment(intent, self._signed(gw, payload)) is False

    def test_verify_non_100_response_code(self, app):
        gw = self._gw()
        tran_ref = f"T{uuid.uuid4().hex[:8]}"
        payload = {"tran_ref": tran_ref}
        intent = PaymentIntent(
            f"paytabs_{tran_ref}", PaymentGateway.PAYTABS, Decimal("1"), "ILS", PaymentStatus.PENDING, 1
        )
        with app.app_context(), patch("requests.get") as get:
            get.return_value = MagicMock(status_code=200, json=lambda: {"payment_result": {"response_code": "7"}})
            assert gw.verify_payment(intent, self._signed(gw, payload)) is False

    def test_create_intent_success(self):
        gw = self._gw()
        with patch("requests.post") as post:
            post.return_value = MagicMock(status_code=200, json=lambda: {"tran_ref": "TR123"})
            intent = gw.create_payment_intent(Decimal("99.5"), "ILS", 3, metadata={"description": "اشتراك"})
            assert intent.id == "paytabs_TR123"
            payload = post.call_args.kwargs["json"]
            assert payload["cart_amount"] == 99.5
            assert payload["cart_description"] == "اشتراك"

    def test_create_intent_http_error_raises(self):
        gw = self._gw()
        with patch("requests.post") as post:
            post.return_value = MagicMock(status_code=500, text="oops")
            with pytest.raises(RuntimeError, match="PayTabs error"):
                gw.create_payment_intent(Decimal("10"), "ILS", 3)

    def test_refund_unsupported(self):
        gw = self._gw()
        intent = PaymentIntent("paytabs_X", PaymentGateway.PAYTABS, Decimal("1"), "ILS", PaymentStatus.PENDING, 1)
        assert gw.refund(intent) is False


# ═══════════════════════════════════════════════════════════════════════════
# CashUGateway
# ═══════════════════════════════════════════════════════════════════════════


class TestCashUGateway:
    def _gw(self, secret="cs3cret"):
        return CashUGateway({"merchant_id": "m", "encryption_key": "ek", "webhook_secret": secret})

    def test_no_secret(self):
        gw = self._gw(None)
        intent = PaymentIntent("cashu_X", PaymentGateway.CASHU, Decimal("1"), "ILS", PaymentStatus.PENDING, 1)
        assert gw.verify_payment(intent, {"payload": {}, "headers": {}}) is False

    def _signed(self, gw, payload):
        body = json.dumps(payload, sort_keys=True).encode()
        sig = hmac.new(gw.webhook_secret.encode(), body, hashlib.sha256).hexdigest()
        return {"payload": payload, "headers": {"X-Cashu-Signature": header_sig(sig)}}

    def test_verify_success(self, app):
        from app.extensions import db
        from app.models.billing import ProcessedEvent

        gw = self._gw()
        txn = f"X{uuid.uuid4().hex[:8]}"
        payload = {"transaction_id": txn}
        intent = PaymentIntent(f"cashu_{txn}", PaymentGateway.CASHU, Decimal("1"), "ILS", PaymentStatus.PENDING, 1)
        with app.app_context(), patch("requests.get") as get:
            get.return_value = MagicMock(status_code=200, json=lambda: {"status": "completed"})
            assert gw.verify_payment(intent, self._signed(gw, payload)) is True
            assert db.session.query(ProcessedEvent).filter_by(event_id=f"cashu_{txn}").count() == 1

    def test_verify_idempotent(self, app):
        from app.extensions import db
        from app.models.billing import ProcessedEvent

        gw = self._gw()
        txn = f"X{uuid.uuid4().hex[:8]}"
        payload = {"transaction_id": txn}
        intent = PaymentIntent(f"cashu_{txn}", PaymentGateway.CASHU, Decimal("1"), "ILS", PaymentStatus.PENDING, 1)
        with app.app_context():
            db.session.add(ProcessedEvent(event_id=f"cashu_{txn}", gateway="cashu", payload={}))
            db.session.commit()
            with patch("requests.get") as get:
                assert gw.verify_payment(intent, self._signed(gw, payload)) is True
                get.assert_not_called()

    def test_bad_signature(self):
        gw = self._gw()
        intent = PaymentIntent("cashu_X", PaymentGateway.CASHU, Decimal("1"), "ILS", PaymentStatus.PENDING, 1)
        data = {"payload": {"a": 1}, "headers": {"X-Cashu-Signature": "nope"}}
        assert gw.verify_payment(intent, data) is False

    def test_api_not_completed(self, app):
        gw = self._gw()
        txn = f"X{uuid.uuid4().hex[:8]}"
        intent = PaymentIntent(f"cashu_{txn}", PaymentGateway.CASHU, Decimal("1"), "ILS", PaymentStatus.PENDING, 1)
        with app.app_context(), patch("requests.get") as get:
            get.return_value = MagicMock(status_code=200, json=lambda: {"status": "pending"})
            assert gw.verify_payment(intent, self._signed(gw, {"transaction_id": txn})) is False

    def test_api_error_status(self, app):
        gw = self._gw()
        txn = f"X{uuid.uuid4().hex[:8]}"
        intent = PaymentIntent(f"cashu_{txn}", PaymentGateway.CASHU, Decimal("1"), "ILS", PaymentStatus.PENDING, 1)
        with app.app_context(), patch("requests.get") as get:
            get.return_value = MagicMock(status_code=503)
            assert gw.verify_payment(intent, self._signed(gw, {"transaction_id": txn})) is False

    def test_create_intent(self):
        gw = self._gw()
        intent = gw.create_payment_intent(Decimal("55"), "ILS", 2)
        assert intent.id.startswith("cashu_")
        assert intent.status == PaymentStatus.PENDING

    def test_refund_unsupported(self):
        assert self._gw().refund(None) is False


def header_sig(sig):  # توقيع Header كما هو
    return sig


# ═══════════════════════════════════════════ _H2 ═══════════════════════════
# WhatsApp + Manual
# ═════ wa marker ═════════════════════════════════════════


class TestManualStyleGateways:
    def test_whatsapp_intent_and_message(self):
        gw = WhatsAppPaymentGateway({"whatsapp_number": "+970599"})
        intent = gw.create_payment_intent(Decimal("150"), "ILS", 5, metadata={"description": "درس", "currency": "ILS"})
        assert intent.id.startswith("whatsapp_")
        assert "طلب دفع جديد" in intent.metadata["whatsapp_message"]
        assert intent.metadata["payment_reference"].startswith("WA_")
        assert gw._build_payment_message(Decimal("10"))  # default description

    def test_whatsapp_verify_admin_approved_only(self):
        gw = WhatsAppPaymentGateway({})
        intent = PaymentIntent("wa", PaymentGateway.WHATSAPP, Decimal("1"), "ILS", PaymentStatus.PENDING, 1)
        assert gw.verify_payment(intent, {"admin_approved": True}) is True
        assert gw.verify_payment(intent, {}) is False

    def test_manual_intent_and_verify(self):
        gw = ManualPaymentGateway({"enabled": True})
        intent = gw.create_payment_intent(Decimal("70"), "ILS", 4)
        assert intent.gateway == PaymentGateway.MANUAL
        assert gw.verify_payment(intent, {"admin_approved": True}) is True
        assert gw.verify_payment(intent, {"admin_approved": False}) is False
        assert gw.refund(intent) is False


# ═══════════════════════════════════════════════════════════════════════════
# PaymentService
# ═══════════════════════════════════════════════════════════════════════════


class TestPaymentService:
    def _svc_with_manual(self):
        svc = PaymentService()
        svc.gateways = {PaymentGateway.MANUAL: ManualPaymentGateway({"enabled": True})}
        return svc

    def test_create_payment_unconfigured_gateway_raises(self):
        svc = self._svc_with_manual()
        with pytest.raises(ValueError, match="not configured"):
            svc.create_payment(PaymentGateway.STRIPE, Decimal("10"), "ILS", 1)

    def test_create_payment_via_manual(self):
        svc = self._svc_with_manual()
        intent = svc.create_payment(PaymentGateway.MANUAL, Decimal("10"), "ILS", 1, metadata={"k": "v"})
        assert intent.gateway == PaymentGateway.MANUAL

    def test_process_webhook_unconfigured_gateway(self):
        svc = self._svc_with_manual()
        result = svc.process_webhook(PaymentGateway.STRIPE, {}, {})
        assert result == {"success": False, "error": "Gateway not configured"}

    def test_process_webhook_verification_failed(self, app):
        svc = self._svc_with_manual()
        result = svc.process_webhook(PaymentGateway.MANUAL, {}, {})
        assert result == {"success": False, "error": "Verification failed"}

    def _cashu_svc(self, app):
        """بوابة CashU حقيقية الموقّعة مع API mock — تمرّ من verify_payment فعلياً."""
        svc = PaymentService()
        svc.gateways = {PaymentGateway.CASHU: CashUGateway({"webhook_secret": "cs3cret"})}
        return svc

    def _signed_cashu(self, payload):
        """headers فقط — process_webhook يبني الغلاف داخلياً."""
        body = json.dumps(payload, sort_keys=True).encode()
        sig = hmac.new(b"cs3cret", body, hashlib.sha256).hexdigest()
        return {"X-Cashu-Signature": sig}

    def test_process_webhook_success_activates_subscription(self, app):
        """Webhook موقّع فعلياً (CashU + API success mock) → تفعيل اشتراك حقيقي."""
        from app.extensions import db
        from app.models.billing import Subscription
        from tests.conftest import (
            make_class,
            make_grade,
            make_school,
            make_subject,
            make_subscription,
            make_subscription_plan,
            make_user,
        )

        sid = make_school(app)
        with app.app_context():
            gid = make_grade(app, sid)
            cid = make_class(app, sid, gid, make_subject(app))
            plan = make_subscription_plan(app, sid, cid, price=100.0)
            uid = make_user(app, role="student", school_id=sid)
            sub_id = make_subscription(app, uid, plan, cid, price=100.0, status="pending")

            svc = self._cashu_svc(app)
            txn = f"X{uuid.uuid4().hex[:8]}"
            payload = {"transaction_id": txn, "metadata": {"subscription_id": str(sub_id)}, "amount": 100}
            with patch("requests.get") as get:
                get.return_value = MagicMock(status_code=200, json=lambda: {"status": "completed"})
                result = svc.process_webhook(PaymentGateway.CASHU, payload, self._signed_cashu(payload))
            assert result == {"success": True}
            sub = db.session.get(Subscription, sub_id)
            assert sub.status == "active"
            assert sub.start_at is not None

    def test_process_webhook_no_subscription_id_in_payload(self, app):
        svc = self._cashu_svc(app)
        payload = {"transaction_id": f"X{uuid.uuid4().hex[:8]}"}
        with app.app_context(), patch("requests.get") as get:
            get.return_value = MagicMock(status_code=200, json=lambda: {"status": "completed"})
            result = svc.process_webhook(PaymentGateway.CASHU, payload, self._signed_cashu(payload))
        assert result == {"success": True}  # verified لكن لا subscription_id → تجاهل

    def test_process_webhook_subscription_missing(self, app):
        svc = self._cashu_svc(app)
        txn = f"X{uuid.uuid4().hex[:8]}"
        payload = {"transaction_id": txn, "metadata": {"subscription_id": "424242"}}
        with app.app_context(), patch("requests.get") as get:
            get.return_value = MagicMock(status_code=200, json=lambda: {"status": "completed"})
            result = svc.process_webhook(PaymentGateway.CASHU, payload, self._signed_cashu(payload))
        assert result == {"success": True}

    def test_process_webhook_no_amount(self, app):
        """subscription موجود لكن payload بلا مبلغ → تحذير وعدم تفعيل."""
        from app.extensions import db
        from app.models.billing import Subscription
        from tests.conftest import (
            make_class,
            make_grade,
            make_school,
            make_subject,
            make_subscription,
            make_subscription_plan,
            make_user,
        )

        sid = make_school(app)
        with app.app_context():
            gid = make_grade(app, sid)
            cid = make_class(app, sid, gid, make_subject(app))
            plan = make_subscription_plan(app, sid, cid, price=100.0)
            uid = make_user(app, role="student", school_id=sid)
            sub_id = make_subscription(app, uid, plan, cid, price=100.0, status="pending")

            svc = self._cashu_svc(app)
            txn = f"X{uuid.uuid4().hex[:8]}"
            payload = {"transaction_id": txn, "metadata": {"subscription_id": str(sub_id)}}  # بلا amount
            with patch("requests.get") as get:
                get.return_value = MagicMock(status_code=200, json=lambda: {"status": "completed"})
                result = svc.process_webhook(PaymentGateway.CASHU, payload, self._signed_cashu(payload))
            assert result == {"success": True}
            assert db.session.get(Subscription, sub_id).status == "pending"  # لم يُفعّل

    def test_process_webhook_fraud_path(self, app):
        """مبلغ مشبوه → subscription.status=pending_review + إشعارات المشرفين."""
        from app.extensions import db
        from app.models.billing import Subscription
        from tests.conftest import (
            make_class,
            make_grade,
            make_school,
            make_subject,
            make_subscription,
            make_subscription_plan,
            make_user,
        )

        sid = make_school(app)
        with app.app_context():
            gid = make_grade(app, sid)
            cid = make_class(app, sid, gid, make_subject(app))
            plan = make_subscription_plan(app, sid, cid, price=100.0)
            uid = make_user(app, role="student", school_id=sid)
            sub_id = make_subscription(app, uid, plan, cid, price=100.0, status="pending")

            svc = self._cashu_svc(app)
            txn = f"X{uuid.uuid4().hex[:8]}"
            payload = {"transaction_id": txn, "metadata": {"subscription_id": str(sub_id)}, "amount": 10000}
            with patch("requests.get") as get:
                get.return_value = MagicMock(status_code=200, json=lambda: {"status": "completed"})
                with patch.object(PaymentService, "_is_suspicious_amount", return_value=True):
                    result = svc.process_webhook(PaymentGateway.CASHU, payload, self._signed_cashu(payload))
            assert result == {"success": True}
            assert db.session.get(Subscription, sub_id).status == "pending_review"

    def test_extract_subscription_id_all_gateways(self, app):
        svc = PaymentService()
        assert (
            svc._extract_subscription_id(
                {"data": {"object": {"metadata": {"subscription_id": "5"}}}}, PaymentGateway.STRIPE
            )
            == 5
        )
        assert svc._extract_subscription_id({"metadata": {"subscription_id": "6"}}, PaymentGateway.PAYTABS) == 6
        assert svc._extract_subscription_id({"metadata": {"subscription_id": "7"}}, PaymentGateway.CASHU) == 7
        assert svc._extract_subscription_id({"metadata": {"subscription_id": "8"}}, PaymentGateway.WHATSAPP) is None
        assert svc._extract_subscription_id({}, PaymentGateway.MANUAL) is None
        assert svc._extract_subscription_id({"data": {"object": {"metadata": {}}}}, PaymentGateway.STRIPE) is None

    def test_extract_amount_all_gateways(self):
        svc = PaymentService()
        assert svc._extract_amount({"data": {"object": {"amount_received": 1050}}}, PaymentGateway.STRIPE) == Decimal(
            "10.5"
        )
        assert svc._extract_amount({"data": {"object": {"amount": 2000}}}, PaymentGateway.STRIPE) == Decimal("20")
        assert svc._extract_amount({"cart_amount": 99.5}, PaymentGateway.PAYTABS) == Decimal("99.5")
        assert svc._extract_amount({"amount": 40}, PaymentGateway.CASHU) == Decimal("40")
        assert svc._extract_amount({}, PaymentGateway.STRIPE) is None
        assert svc._extract_amount({"amount": None}, PaymentGateway.CASHU) is None
        assert svc._extract_amount({"amount": 5}, PaymentGateway.WHATSAPP) is None

    def test_is_suspicious_amount_direct(self, app):
        """متوسط مدفوعات المدرسة — مبلغ أعلى من 3x → True."""
        from tests.conftest import (
            make_class,
            make_grade,
            make_payment,
            make_school,
            make_subject,
            make_subscription,
            make_subscription_plan,
            make_user,
        )

        svc = PaymentService()
        sid = make_school(app)
        with app.app_context():
            gid = make_grade(app, sid)
            cid = make_class(app, sid, gid, make_subject(app))
            plan = make_subscription_plan(app, sid, cid, price=100.0)
            uid = make_user(app, role="student", school_id=sid)
            sub_id = make_subscription(app, uid, plan, cid, price=100.0, status="active")
            make_payment(app, sub_id, amount=10.0, status="approved")  # avg=10 → threshold=30
            assert svc._is_suspicious_amount(sid, Decimal("31")) is True
            assert svc._is_suspicious_amount(sid, Decimal("29")) is False
            # مدرسة بلا بيانات → False
            other = make_school(app)
            assert svc._is_suspicious_amount(other, Decimal("999")) is False

    def test_create_ledger_entry(self, app):
        from app.extensions import db
        from app.models.billing import ManualPayment, Subscription
        from tests.conftest import (
            make_class,
            make_grade,
            make_payment,
            make_school,
            make_subject,
            make_subscription,
            make_subscription_plan,
            make_user,
        )

        svc = PaymentService()
        sid = make_school(app)
        with app.app_context():
            gid = make_grade(app, sid)
            cid = make_class(app, sid, gid, make_subject(app))
            plan = make_subscription_plan(app, sid, cid, price=100.0)
            uid = make_user(app, role="student", school_id=sid)
            sub_id = make_subscription(app, uid, plan, cid, price=100.0, status="active")
            pay_id = make_payment(app, sub_id, amount=50.0, status="approved")
            svc._create_ledger_entry(
                db.session.get(Subscription, sub_id),
                Decimal("50"),
                PaymentGateway.WHATSAPP,
            )
            payment = db.session.get(ManualPayment, pay_id)
            assert payment.gateway == "whatsapp"
            assert payment.amount == 50.0

    def test_cleanup_expired_intents_returns_zero(self):
        assert PaymentService().cleanup_expired_intents() == 0

    def test_get_payment_service_singleton(self):
        s1 = get_payment_service()
        s2 = get_payment_service()
        assert s1 is s2


# ═══════════════════════════════════════════════════════════ wal ═══════════
# invoice missing lines (40, 47, 49-50)
# ═══════════════════════════════════════════════════════════════════════════


class TestInvoicePdfGaps:
    def test_pdf_success_real_bytes(self, app, tmp_path, monkeypatch):
        from app.services.invoice import generate_invoice_number, render_invoice_pdf
        from tests.conftest import (
            make_class,
            make_grade,
            make_school,
            make_subject,
            make_subscription,
            make_subscription_plan,
            make_user,
        )

        sid = make_school(app)
        with app.app_context():
            gid = make_grade(app, sid)
            cid = make_class(app, sid, gid, make_subject(app))
            plan = make_subscription_plan(app, sid, cid)
            uid = make_user(app, role="student", school_id=sid)
            sub = make_subscription(app, uid, plan, cid, price=80.0, status="active")
            from app.services.invoice import generate_invoice_html

            monkeypatch.setitem(app.config, "UPLOAD_FOLDER", str(tmp_path))
            with app.test_request_context("/"):
                html = generate_invoice_html(sub)
                assert html is not None
                number = generate_invoice_number(
                    __import__("app.extensions", fromlist=["db"]).db.session.get(
                        __import__("app.models.billing", fromlist=["Subscription"]).Subscription, sub
                    )
                )
                assert "INV-" in number
                pdf = render_invoice_pdf(sub)
                assert isinstance(pdf, bytes)
                assert bytes(pdf)[:5] == b"%PDF-"

    def test_pdf_html_none(self, app):
        from app.services.invoice import render_invoice_pdf

        with app.test_request_context("/"):
            assert render_invoice_pdf(999_999) is None
