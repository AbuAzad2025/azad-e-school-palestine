"""Batch 5 — payments/finance coverage gaps (verified misses only).

Route layer: /api/payments/webhook/* (all 4 gateways incl. WhatsApp challenge),
/payments UI page+API, /payments/create-intent ownership+amount+currency guards,
/payments/verify manual approval contract.

Service layer: gateway intent creation + webhook signature verification
(Stripe mock SDK, PayTabs/CashU real HMAC + mocked verify API), webhook-driven
auto-activation (happy path + fraud flag), extractor methods per gateway,
cleanup_expired_intents.

Wallet: transfer failure branches, tutor commission math, admin credit
(idempotency + validation), transaction history.

Invoice: missing subscription branch, invoice number format, real PDF bytes
(reportlab platypus via app/core/pdf.py).
"""

from __future__ import annotations

import hashlib
import hmac as hmac_mod
import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from tests.conftest import (
    make_class,
    make_grade,
    make_payment,
    make_school,
    make_subject,
    make_subscription,
    make_subscription_plan,
    make_tutoring_session,
    make_user,
)

_PASSWORD = "TestPass123!"


def _persona(app, role, school_id=None):
    """Create a user + logged-in client → (user_id, client)."""
    email = f"b5-{uuid.uuid4().hex[:10]}@test.com"
    uid = make_user(app, role=role, school_id=school_id, email=email)
    client = app.test_client()
    client.post("/auth/login", data={"email": email, "password": _PASSWORD}, follow_redirects=False)
    return uid, client


def _wallet(app, school_id, user_id, currency="ILS"):
    from app.services.wallet_service import get_or_create_wallet

    with app.app_context():
        w, err = get_or_create_wallet(school_id, user_id, currency=currency)
        assert err is None
        return w.id


def _intent(
    payment_id: str,
    gateway: str = "stripe",
    amount: Decimal = Decimal("0"),
    gateway_response: dict | None = None,
):
    """Type-safe PaymentIntent stand-in (gateway methods only read id/amount/gateway_response)."""
    from app.services.payments import PaymentGateway, PaymentIntent, PaymentStatus

    return PaymentIntent(
        id=payment_id,
        gateway=PaymentGateway(gateway),
        amount=amount,
        currency="ILS",
        status=PaymentStatus.PENDING,
        user_id=0,
        gateway_response=gateway_response,
    )


def _xfer(app, school_id, src, dst, amount, key):
    """process_transfer with the required description pre-filled."""
    from app.services.wallet_service import process_transfer

    return process_transfer(school_id, src, dst, amount, idempotency_key=key, description="b5")


# ════════════════════════════════════════════════════════════════════
# Webhook routes — real service behind them (Stripe SDK absent → 400)
# ════════════════════════════════════════════════════════════════════


class TestWebhookRoutes:
    def test_stripe_webhook_unverifiable_returns_400(self, app):
        client = app.test_client()
        resp = client.post("/api/payments/webhook/stripe", data="{}", content_type="application/json")
        assert resp.status_code == 400
        assert resp.get_json()["success"] is False

    def test_paytabs_webhook_bad_signature_returns_400(self, app):
        client = app.test_client()
        resp = client.post("/api/payments/webhook/paytabs", json={"tran_ref": "x"})
        assert resp.status_code == 400

    def test_cashu_webhook_bad_signature_returns_400(self, app):
        client = app.test_client()
        resp = client.post("/api/payments/webhook/cashu", json={"transaction_id": "x"})
        assert resp.status_code == 400

    def test_whatsapp_webhook_rejects_unsigned_traffic(self, app):
        """The old stub answered {"status": "received"} to anyone.

        It now verifies a Meta HMAC signature over the raw body like every
        other webhook, so unsigned traffic is refused instead of acknowledged.
        """
        client = app.test_client()
        resp = client.post("/api/payments/webhook/whatsapp")
        assert resp.status_code == 401
        assert "traceback" not in resp.get_data(as_text=True).lower()

    def test_whatsapp_webhook_wrong_verify_token_403(self, app):
        client = app.test_client()
        resp = client.post("/api/payments/webhook/whatsapp?hub.verify_token=wrong&hub.challenge=c1")
        assert resp.status_code == 403

    def test_whatsapp_webhook_verify_token_challenge(self, app, monkeypatch):
        monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", "tok123")
        client = app.test_client()
        resp = client.post("/api/payments/webhook/whatsapp?hub.verify_token=tok123&hub.challenge=ch99")
        assert resp.status_code == 200
        assert resp.get_data(as_text=True) == "ch99"


# ════════════════════════════════════════════════════════════════════
# Payments UI routes
# ════════════════════════════════════════════════════════════════════


class TestPaymentsUIRoutes:
    def test_methods_page_requires_login(self, app):
        resp = app.test_client().get("/payments/", follow_redirects=False)
        assert resp.status_code == 302

    def test_methods_page_renders(self, app):
        _, client = _persona(app, "student")
        resp = client.get("/payments/")
        assert resp.status_code == 200

    def test_methods_api_lists_all_gateways(self, app):
        _, client = _persona(app, "student")
        resp = client.get("/payments/methods")
        assert resp.status_code == 200
        ids = {m["id"] for m in resp.get_json()["methods"]}
        assert {"stripe", "paytabs", "cashu", "whatsapp", "manual"} <= ids


class TestCreateIntentRoute:
    def test_missing_gateway_400(self, app):
        _, client = _persona(app, "student")
        resp = client.post("/payments/create-intent", json={"amount": 10})
        assert resp.status_code == 400

    def test_non_positive_amount_400(self, app):
        _, client = _persona(app, "student")
        resp = client.post("/payments/create-intent", json={"gateway": "manual", "amount": 0})
        assert resp.status_code == 400

    def test_unknown_gateway_400(self, app):
        _, client = _persona(app, "student")
        resp = client.post("/payments/create-intent", json={"gateway": "nope", "amount": 10})
        assert resp.status_code == 400

    def test_subscription_of_other_user_403(self, app):
        sid = make_school(app)
        owner, _ = _persona(app, "student", sid)
        stranger, client = _persona(app, "student", sid)
        grade = make_grade(app, sid)
        subject = make_subject(app)
        cid = make_class(app, sid, grade, subject)
        plan = make_subscription_plan(app, sid, cid, price=75.0)
        sub = make_subscription(app, owner, plan, cid, price=75.0)
        resp = client.post(
            "/payments/create-intent",
            json={"gateway": "manual", "amount": 75, "subscription_id": sub, "currency": "ILS"},
        )
        assert resp.status_code == 403

    def test_amount_mismatch_400(self, app):
        sid = make_school(app)
        uid, client = _persona(app, "student", sid)
        grade = make_grade(app, sid)
        subject = make_subject(app)
        cid = make_class(app, sid, grade, subject)
        plan = make_subscription_plan(app, sid, cid, price=75.0)
        sub = make_subscription(app, uid, plan, cid, price=75.0)
        resp = client.post(
            "/payments/create-intent",
            json={"gateway": "manual", "amount": 99, "subscription_id": sub, "currency": "ILS"},
        )
        assert resp.status_code == 400

    def test_currency_mismatch_400(self, app):
        sid = make_school(app)
        uid, client = _persona(app, "student", sid)
        grade = make_grade(app, sid)
        subject = make_subject(app)
        cid = make_class(app, sid, grade, subject)
        plan = make_subscription_plan(app, sid, cid, price=75.0)
        sub = make_subscription(app, uid, plan, cid, price=75.0)
        resp = client.post(
            "/payments/create-intent",
            json={"gateway": "manual", "amount": 75, "subscription_id": sub, "currency": "USD"},
        )
        assert resp.status_code == 400

    def test_success_returns_payment_intent_payload(self, app):
        sid = make_school(app)
        uid, client = _persona(app, "student", sid)
        grade = make_grade(app, sid)
        subject = make_subject(app)
        cid = make_class(app, sid, grade, subject)
        plan = make_subscription_plan(app, sid, cid, price=75.0)
        sub = make_subscription(app, uid, plan, cid, price=75.0)
        resp = client.post(
            "/payments/create-intent",
            json={"gateway": "manual", "amount": 75, "subscription_id": sub, "currency": "ILS"},
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["payment_id"].startswith("manual_")
        assert body["gateway"] == "manual"
        assert Decimal(body["amount"]) == Decimal("75.00")


class TestVerifyRoute:
    def test_incomplete_data_400(self, app):
        _, client = _persona(app, "student")
        resp = client.post("/payments/verify", json={"payment_id": "p1"})
        assert resp.status_code == 400

    def test_unknown_gateway_400(self, app):
        _, client = _persona(app, "student")
        resp = client.post("/payments/verify", json={"payment_id": "p1", "gateway": "bogus"})
        assert resp.status_code == 400

    def test_manual_gateway_admin_approved_success(self, app):
        _, client = _persona(app, "student")
        resp = client.post("/payments/verify", json={"payment_id": "p1", "gateway": "manual"})
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True


# ════════════════════════════════════════════════════════════════════
# Gateway internals — Stripe (mock SDK), PayTabs/CashU (real HMAC)
# ════════════════════════════════════════════════════════════════════


class _Evt(dict):
    """Webhook event: dict (JSONB-serializable) carrying a .type attribute."""

    type = "payment_intent.succeeded"


class TestStripeGateway:
    def _gw(self):
        from app.services.payments import StripeGateway

        return StripeGateway({})

    def test_import_error_fallback_marks_unconfigured(self):
        gw = self._gw()
        assert gw.stripe is None

    def test_create_intent_without_sdk_raises(self):
        with pytest.raises(RuntimeError, match="not configured"):
            self._gw().create_payment_intent(Decimal("10"), "ILS", 1)

    def test_verify_without_sdk_or_secret_false(self):
        assert self._gw().verify_payment(_intent("x"), {"payload": "", "headers": {}}) is False

    def test_verify_success_records_processed_event(self, app):
        gw = self._gw()
        gw.webhook_secret = "whsec"
        event = _Evt(id="evt_b5_1", type="payment_intent.succeeded")
        gw.stripe = MagicMock()
        gw.stripe.Webhook.construct_event.return_value = event
        with app.app_context():
            intent = _intent("stripe_pi1")
            assert gw.verify_payment(intent, {"payload": "{}", "headers": {"Stripe-Signature": "sig"}}) is True
            from app.models.billing import ProcessedEvent

            assert ProcessedEvent.query.filter_by(event_id="evt_b5_1").first() is not None

    def test_verify_idempotent_replay_true(self, app):
        gw = self._gw()
        gw.webhook_secret = "whsec"
        event = _Evt(id="evt_b5_2", type="payment_intent.succeeded")
        gw.stripe = MagicMock()
        gw.stripe.Webhook.construct_event.return_value = event
        with app.app_context():
            from app.extensions import db
            from app.models.billing import ProcessedEvent

            db.session.add(ProcessedEvent(event_id="evt_b5_2", gateway="stripe", payload={}))
            db.session.commit()
            intent = _intent("stripe_pi2")
            assert gw.verify_payment(intent, {"payload": "{}", "headers": {}}) is True

    def test_verify_non_payment_event_false(self, app):
        gw = self._gw()
        gw.webhook_secret = "whsec"
        event = _Evt(id="evt_b5_3", type="invoice.paid")
        event.type = "invoice.paid"
        gw.stripe = MagicMock()
        gw.stripe.Webhook.construct_event.return_value = event
        with app.app_context():
            assert gw.verify_payment(_intent("x"), {"payload": "{}", "headers": {}}) is False

    def test_verify_signature_error_false(self):
        gw = self._gw()
        gw.webhook_secret = "whsec"
        gw.stripe = MagicMock()
        gw.stripe.Webhook.construct_event.side_effect = Exception("bad signature")
        assert gw.verify_payment(_intent("x"), {"payload": "{}", "headers": {}}) is False

    def test_refund_without_sdk_false(self):
        intent = _intent("stripe_x", gateway_response={"client_secret": "s"}, amount=Decimal("1"))
        assert self._gw().refund(intent) is False

    def test_refund_success(self):
        gw = self._gw()
        gw.stripe = MagicMock()
        intent = _intent("stripe_pi9", gateway_response={"client_secret": "s"}, amount=Decimal("5"))
        assert gw.refund(intent) is True
        gw.stripe.Refund.create.assert_called_once_with(payment_intent="pi9", amount=500)

    def test_refund_failure_false(self):
        gw = self._gw()
        gw.stripe = MagicMock()
        gw.stripe.Refund.create.side_effect = Exception("declined")
        intent = _intent("stripe_pi9", gateway_response={"c": 1}, amount=Decimal("5"))
        assert gw.refund(intent) is False


class TestPayTabsGateway:
    def _gw(self):
        from app.services.payments import PayTabsGateway

        return PayTabsGateway({"webhook_secret": "ptsecret", "server_key": "sk"})

    def _sig(self, payload: dict, secret: str = "ptsecret") -> str:
        return hmac_mod.new(secret.encode(), json.dumps(payload, sort_keys=True).encode(), hashlib.sha256).hexdigest()

    def test_verify_without_secret_false(self):
        from app.services.payments import PayTabsGateway

        gw = PayTabsGateway({})
        assert gw.verify_payment(_intent("paytabs_x", "paytabs"), {"payload": {}, "headers": {}}) is False

    def test_verify_bad_signature_false(self):
        gw = self._gw()
        data = {"payload": {"tran_ref": "T1"}, "headers": {"X-Paytabs-Signature": "deadbeef"}}
        assert gw.verify_payment(_intent("paytabs_T1", "paytabs"), data) is False

    def test_verify_good_signature_api_confirmed(self, app):
        gw = self._gw()
        payload = {"tran_ref": "PT-b5-1", "cart_amount": 100}
        data = {"payload": payload, "headers": {"X-Paytabs-Signature": self._sig(payload)}}
        api = MagicMock(status_code=200)
        api.json.return_value = {"payment_result": {"response_code": "100"}}
        with patch("requests.get", return_value=api):
            with app.app_context():
                from app.services.payments import PaymentGateway, PaymentIntent, PaymentStatus

                intent = PaymentIntent(
                    id="paytabs_PT-b5-1",
                    gateway=PaymentGateway.PAYTABS,
                    amount=Decimal("100"),
                    currency="ILS",
                    status=PaymentStatus.PENDING,
                    user_id=1,
                )
                assert gw.verify_payment(intent, data) is True
                from app.models.billing import ProcessedEvent

                assert ProcessedEvent.query.filter_by(event_id="paytabs_PT-b5-1").first() is not None

    def test_verify_api_reject_false(self, app):
        gw = self._gw()
        payload = {"tran_ref": "PT-b5-2"}
        data = {"payload": payload, "headers": {"X-Paytabs-Signature": self._sig(payload)}}
        api = MagicMock(status_code=200)
        api.json.return_value = {"payment_result": {"response_code": "999"}}
        with app.app_context():
            with patch("requests.get", return_value=api):
                assert gw.verify_payment(_intent("paytabs_PT-b5-2", "paytabs"), data) is False

    def test_verify_api_exception_false(self, app):
        gw = self._gw()
        payload = {"tran_ref": "PT-b5-3"}
        data = {"payload": payload, "headers": {"X-Paytabs-Signature": self._sig(payload)}}
        with patch("requests.get", side_effect=OSError("network down")):
            with app.app_context():
                assert gw.verify_payment(_intent("paytabs_PT-b5-3", "paytabs"), data) is False

    def test_create_intent_success(self):
        gw = self._gw()
        api = MagicMock(status_code=200)
        api.json.return_value = {"tran_ref": "PT99", "redirect_url": "https://paytabs/pay"}
        with patch("requests.post", return_value=api) as post:
            intent = gw.create_payment_intent(Decimal("120"), "ILS", 7, metadata={"description": "d"})
        assert intent.id == "paytabs_PT99"
        assert intent.gateway_response["redirect_url"].startswith("https://")
        assert post.call_args.kwargs["timeout"] == (3, 27)

    def test_create_intent_api_error_raises(self):
        gw = self._gw()
        api = MagicMock(status_code=500, text="boom")
        with patch("requests.post", return_value=api), pytest.raises(RuntimeError, match="PayTabs"):
            gw.create_payment_intent(Decimal("1"), "ILS", 1)

    def test_refund_not_supported(self):
        assert self._gw().refund(_intent("x")) is False


class TestCashUGateway:
    def _gw(self):
        from app.services.payments import CashUGateway

        return CashUGateway({"webhook_secret": "csecret", "encryption_key": "ek"})

    def _sig(self, payload: dict, secret: str = "csecret") -> str:
        return hmac_mod.new(secret.encode(), json.dumps(payload, sort_keys=True).encode(), hashlib.sha256).hexdigest()

    def test_create_intent_local_no_io(self):
        intent = self._gw().create_payment_intent(Decimal("30"), "ILS", 3)
        assert intent.id.startswith("cashu_")
        assert intent.status.value == "pending"

    def test_verify_without_secret_false(self):
        from app.services.payments import CashUGateway

        assert CashUGateway({}).verify_payment(_intent("cashu_x", "cashu"), {"payload": {}, "headers": {}}) is False

    def test_verify_bad_signature_false(self):
        gw = self._gw()
        data = {"payload": {"transaction_id": "TX1"}, "headers": {"X-Cashu-Signature": "nope"}}
        assert gw.verify_payment(_intent("cashu_TX1", "cashu"), data) is False

    def test_verify_completed_records_event(self, app):
        gw = self._gw()
        payload = {"transaction_id": "TX-b5-1"}
        data = {"payload": payload, "headers": {"X-Cashu-Signature": self._sig(payload)}}
        api = MagicMock(status_code=200)
        api.json.return_value = {"status": "completed"}
        with patch("requests.get", return_value=api):
            with app.app_context():
                from app.services.payments import PaymentGateway, PaymentIntent, PaymentStatus

                intent = PaymentIntent(
                    id="cashu_TX-b5-1",
                    gateway=PaymentGateway.CASHU,
                    amount=Decimal("30"),
                    currency="ILS",
                    status=PaymentStatus.PENDING,
                    user_id=1,
                )
                assert gw.verify_payment(intent, data) is True
                from app.models.billing import ProcessedEvent

                assert ProcessedEvent.query.filter_by(event_id="cashu_TX-b5-1").first() is not None

    def test_verify_api_not_completed_false(self, app):
        gw = self._gw()
        payload = {"transaction_id": "TX-b5-2"}
        data = {"payload": payload, "headers": {"X-Cashu-Signature": self._sig(payload)}}
        api = MagicMock(status_code=200)
        api.json.return_value = {"status": "failed"}
        with patch("requests.get", return_value=api):
            with app.app_context():
                assert gw.verify_payment(_intent("cashu_TX-b5-2", "cashu"), data) is False

    def test_refund_not_supported(self):
        assert self._gw().refund(_intent("x")) is False


# ════════════════════════════════════════════════════════════════════
# PaymentService — webhook orchestration, fraud flag, extractors
# ════════════════════════════════════════════════════════════════════


class TestPaymentService:
    def _svc(self):
        from app.services.payments import PaymentService

        return PaymentService()

    def test_all_gateways_instantiated(self):
        svc = self._svc()
        assert {"stripe", "paytabs", "cashu", "whatsapp", "manual"} <= {g.value for g in svc.gateways}

    def test_webhook_unconfigured_gateway(self):
        from app.services.payments import PaymentGateway

        svc = self._svc()
        del svc.gateways[PaymentGateway.STRIPE]
        result = svc.process_webhook(PaymentGateway.STRIPE, {}, {})
        assert result == {"success": False, "error": "Gateway not configured"}

    def test_webhook_verification_failed(self):
        from app.services.payments import PaymentGateway

        svc = self._svc()
        result = svc.process_webhook(PaymentGateway.PAYTABS, {"payload": {}}, {})
        assert result["success"] is False

    def test_webhook_verified_success_with_unknown_subscription(self):
        """Verified gateway but payload lacks a resolvable subscription → warning no-op."""
        from app.services.payments import PaymentGateway

        svc = self._svc()
        fake = MagicMock()
        # process_webhook يستهلك العقد الصريح (WebhookVerification) لا bool،
        # وإلا التبس «موقّع» بـ «سبق معالجته».
        from app.services.payments import WebhookVerification

        fake.verify_webhook.return_value = WebhookVerification(
            verified=True, event_id="manual_1", reason="admin_approved"
        )
        svc.gateways[PaymentGateway.MANUAL] = fake
        result = svc.process_webhook(PaymentGateway.MANUAL, {"payload": {"x": 1}}, {})
        assert result == {"success": True}

    def test_handle_successful_payment_full_activation(self, app):
        """Gateway webhook → auto-activate subscription + ledger + audit."""
        from app.extensions import db
        from app.models.billing import Subscription
        from app.services.payments import PaymentGateway

        sid = make_school(app)
        uid = make_user(app, role="student", school_id=sid)
        grade = make_grade(app, sid)
        subject = make_subject(app)
        cid = make_class(app, sid, grade, subject)
        plan = make_subscription_plan(app, sid, cid, price=75.0)
        sub_id = make_subscription(app, uid, plan, cid, price=75.0, status="pending")

        svc = self._svc()
        payload = {"metadata": {"subscription_id": sub_id}, "cart_amount": "75.00"}
        from app.models.user import User
        from flask_login import login_user

        with app.test_request_context():
            user = db.session.get(User, uid)
            login_user(user)
            with patch("app.services.email.send_payment_approved_email") as mail:
                svc._handle_successful_payment(payload, PaymentGateway.PAYTABS)
            mail.assert_called_once()

        with app.app_context():
            sub = db.session.get(Subscription, sub_id)
            assert sub is not None
            assert sub.status == "active"
            assert sub.auto_activated_at is not None
            assert sub.source == "gateway"

    def test_handle_successful_payment_flags_suspicious_amount(self, app):
        """Amount > 3x the school's 90-day average → pending_review + admin notify."""
        from app.extensions import db
        from app.models.billing import Subscription
        from app.services.payments import PaymentGateway

        sid = make_school(app)
        uid = make_user(app, role="student", school_id=sid)
        grade = make_grade(app, sid)
        subject = make_subject(app)
        cid = make_class(app, sid, grade, subject)
        plan = make_subscription_plan(app, sid, cid, price=10.0)
        # History: two approved payments of 10 → average 10, threshold 30
        hist_sub = make_subscription(app, uid, plan, cid, price=10.0)
        make_payment(app, hist_sub, amount=10.0, status="approved")
        sub_id = make_subscription(app, uid, plan, cid, price=10.0, status="pending")

        with app.app_context():
            from app.models.billing import ManualPayment

            older = db.session.get(ManualPayment, make_payment(app, hist_sub, amount=10.0, status="approved"))
            assert older is not None
            older.created_at = datetime.now(UTC) - timedelta(days=30)
            db.session.commit()

        svc = self._svc()
        payload = {"metadata": {"subscription_id": sub_id}, "cart_amount": "500.00"}
        with app.app_context():
            svc._handle_successful_payment(payload, PaymentGateway.PAYTABS)

        with app.app_context():
            flagged = db.session.get(Subscription, sub_id)
            assert flagged is not None
            assert flagged.status == "pending_review"

    def test_handle_successful_payment_subscription_not_found(self, app):
        from app.services.payments import PaymentGateway

        svc = self._svc()
        payload = {"metadata": {"subscription_id": 99999999}, "cart_amount": "10"}
        with app.app_context():
            svc._handle_successful_payment(payload, PaymentGateway.PAYTABS)  # warning no-op, no crash

    def test_extract_subscription_id_per_gateway(self):
        from app.services.payments import PaymentGateway

        svc = self._svc()
        stripe_payload = {"data": {"object": {"metadata": {"subscription_id": "5"}}}}
        assert svc._extract_subscription_id(stripe_payload, PaymentGateway.STRIPE) == 5
        assert svc._extract_subscription_id({"metadata": {"subscription_id": "6"}}, PaymentGateway.PAYTABS) == 6
        assert svc._extract_subscription_id({"metadata": {"subscription_id": "7"}}, PaymentGateway.CASHU) == 7
        assert svc._extract_subscription_id({}, PaymentGateway.WHATSAPP) is None
        assert svc._extract_subscription_id({}, PaymentGateway.MANUAL) is None

    def test_extract_amount_per_gateway(self):
        from app.services.payments import PaymentGateway

        svc = self._svc()
        stripe_payload = {"data": {"object": {"amount_received": 7500}}}
        assert svc._extract_amount(stripe_payload, PaymentGateway.STRIPE) == Decimal("75")
        assert svc._extract_amount({"cart_amount": "75.5"}, PaymentGateway.PAYTABS) == Decimal("75.5")
        assert svc._extract_amount({"amount": "30"}, PaymentGateway.CASHU) == Decimal("30")
        assert svc._extract_amount({}, PaymentGateway.WHATSAPP) is None

    def test_is_suspicious_no_history_false(self, app):
        sid = make_school(app)
        svc = self._svc()
        with app.app_context():
            assert svc._is_suspicious_amount(sid, Decimal("1000")) is False

    def test_is_suspicious_above_threshold_true(self, app):
        sid = make_school(app)
        uid = make_user(app, role="student", school_id=sid)
        grade = make_grade(app, sid)
        subject = make_subject(app)
        cid = make_class(app, sid, grade, subject)
        plan = make_subscription_plan(app, sid, cid, price=10.0)
        hist = make_subscription(app, uid, plan, cid, price=10.0)
        make_payment(app, hist, amount=10.0, status="approved")
        svc = self._svc()
        with app.app_context():
            assert svc._is_suspicious_amount(sid, Decimal("100")) is True

    def test_create_payment_unconfigured_gateway_raises(self):
        from app.services.payments import PaymentGateway

        svc = self._svc()
        del svc.gateways[PaymentGateway.STRIPE]
        with pytest.raises(ValueError, match="not configured"):
            svc.create_payment(PaymentGateway.STRIPE, Decimal("1"), "ILS", 1)

    def test_cleanup_expired_intents_returns_zero(self):
        assert self._svc().cleanup_expired_intents() == 0

    def test_manual_gateway_create_and_verify(self):
        from app.services.payments import ManualPaymentGateway

        gw = ManualPaymentGateway({"enabled": True})
        intent = gw.create_payment_intent(Decimal("5"), "ILS", 1)
        assert intent.id.startswith("manual_")
        assert gw.verify_payment(intent, {}) is False
        assert gw.verify_payment(intent, {"admin_approved": True}) is True
        assert gw.refund(intent) is False


# ════════════════════════════════════════════════════════════════════
# Wallet service — transfer failures, commission, admin credit, history
# ════════════════════════════════════════════════════════════════════


class TestWalletTransfers:
    def test_transfer_missing_source_wallet(self, app):

        sid = make_school(app)
        uid = make_user(app, role="student", school_id=sid)
        uid2 = make_user(app, role="student", school_id=sid)
        _wallet(app, sid, uid2)
        with app.app_context():
            tx_, err = _xfer(app, sid, uid, uid2, Decimal("5"), f"b5-{uuid.uuid4().hex[:8]}")
        assert tx_ is None and err is not None

    def test_transfer_missing_dest_wallet(self, app):

        sid = make_school(app)
        uid = make_user(app, role="student", school_id=sid)
        uid2 = make_user(app, role="student", school_id=sid)
        _wallet(app, sid, uid)
        with app.app_context():
            tx_, err = _xfer(app, sid, uid, uid2, Decimal("5"), f"b5-{uuid.uuid4().hex[:8]}")
        assert tx_ is None and err is not None

    def test_transfer_frozen_source_wallet(self, app):
        from app.extensions import db
        from app.models.wallet import Wallet

        sid = make_school(app)
        uid = make_user(app, role="student", school_id=sid)
        uid2 = make_user(app, role="student", school_id=sid)
        wid = _wallet(app, sid, uid)
        _wallet(app, sid, uid2)
        with app.app_context():
            wallet = db.session.get(Wallet, wid)
            assert wallet is not None
            wallet.status = "frozen"
            db.session.commit()
            tx_, err = _xfer(app, sid, uid, uid2, Decimal("5"), f"b5-{uuid.uuid4().hex[:8]}")
        assert tx_ is None and err is not None

    def test_transfer_currency_mismatch(self, app):

        sid = make_school(app)
        uid = make_user(app, role="student", school_id=sid)
        uid2 = make_user(app, role="student", school_id=sid)
        _wallet(app, sid, uid, currency="ILS")
        _wallet(app, sid, uid2, currency="USD")
        with app.app_context():
            tx_, err = _xfer(app, sid, uid, uid2, Decimal("5"), f"b5-{uuid.uuid4().hex[:8]}")
        assert tx_ is None and err is not None

    def test_transfer_insufficient_balance(self, app):

        sid = make_school(app)
        uid = make_user(app, role="student", school_id=sid)
        uid2 = make_user(app, role="student", school_id=sid)
        wid = _wallet(app, sid, uid)
        _wallet(app, sid, uid2)
        with app.app_context():
            from app.extensions import db
            from app.models.wallet import Wallet

            wallet = db.session.get(Wallet, wid)
            assert wallet is not None
            wallet.balance = Decimal("2.00")
            db.session.commit()
            tx_, err = _xfer(app, sid, uid, uid2, Decimal("5"), f"b5-{uuid.uuid4().hex[:8]}")
        assert tx_ is None and "الرصيد غير كافٍ" in (err or "")

    def test_transfer_success_moves_balance_and_ledgers(self, app):
        from app.extensions import db
        from app.models.wallet import Wallet

        sid = make_school(app)
        uid = make_user(app, role="student", school_id=sid)
        uid2 = make_user(app, role="student", school_id=sid)
        w1 = _wallet(app, sid, uid)
        w2 = _wallet(app, sid, uid2)
        with app.app_context():
            src = db.session.get(Wallet, w1)
            dst = db.session.get(Wallet, w2)
            assert src is not None and dst is not None
            src.balance = Decimal("50.00")
            db.session.commit()
            ledger, err = _xfer(app, sid, uid, uid2, Decimal("12.50"), f"b5-{uuid.uuid4().hex[:8]}")
            assert err is None
            assert ledger.status == "completed"
            assert ledger.source_wallet_id == w1 and ledger.destination_wallet_id == w2
            src_after = db.session.get(Wallet, w1)
            dst_after = db.session.get(Wallet, w2)
            assert src_after is not None and dst_after is not None
            assert src_after.balance == Decimal("37.50")
            assert dst_after.balance == Decimal("12.50")

    def test_transfer_idempotent_replay(self, app):
        from app.extensions import db
        from app.models.wallet import Wallet

        sid = make_school(app)
        uid = make_user(app, role="student", school_id=sid)
        uid2 = make_user(app, role="student", school_id=sid)
        w1 = _wallet(app, sid, uid)
        _wallet(app, sid, uid2)
        key = f"b5-{uuid.uuid4().hex[:8]}"
        with app.app_context():
            wallet = db.session.get(Wallet, w1)
            assert wallet is not None
            wallet.balance = Decimal("50.00")
            db.session.commit()
            first, err1 = _xfer(app, sid, uid, uid2, Decimal("5"), key)
            replay, err2 = _xfer(app, sid, uid, uid2, Decimal("5"), key)
            assert err1 is None and err2 is None
            assert first.id == replay.id
            final = db.session.get(Wallet, w1)
            assert final is not None
            assert final.balance == Decimal("45.00")  # debited exactly once


class TestTutorCommission:
    def test_commission_success_deducts_only_commission(self, app):
        from app.extensions import db
        from app.models.wallet import Wallet
        from app.services.wallet_service import process_tutor_commission

        sid = make_school(app)
        tutor = make_user(app, role="teacher", school_id=sid)
        platform = make_user(app, role="school_admin", school_id=sid)
        w1 = _wallet(app, sid, tutor)
        _wallet(app, sid, platform)
        with app.app_context():
            tw = db.session.get(Wallet, w1)
            assert tw is not None
            tw.balance = Decimal("100.00")
            db.session.commit()
            ledger, err = process_tutor_commission(
                sid, tutor, platform, Decimal("200.00"), Decimal("20"), f"b5-{uuid.uuid4().hex[:8]}", session_id=1
            )
            assert err is None
            assert ledger.amount == Decimal("40.00")  # 20% of 200
            assert ledger.transaction_type == "tutor_commission"
            tw_after = db.session.get(Wallet, w1)
            assert tw_after is not None
            assert tw_after.balance == Decimal("60.00")

    def test_commission_failure_propagates(self, app):
        from app.services.wallet_service import process_tutor_commission

        sid = make_school(app)
        tutor = make_user(app, role="teacher", school_id=sid)
        platform = make_user(app, role="school_admin", school_id=sid)
        _wallet(app, sid, platform)  # tutor has no wallet
        with app.app_context():
            _, err = process_tutor_commission(
                sid, tutor, platform, Decimal("100"), Decimal("20"), f"b5-{uuid.uuid4().hex[:8]}", session_id=2
            )
        assert err is not None


# ═════════════════════════ AZ-P3-16: settlement matching ═════════════════════════


class TestTutorCommissionSettlement:
    """AZ-P3-16 — محفظة المعلم وسجل العمولة لا يتباعدان أبداً (لا تخطٍّ صامت).

    معايير القبول (docs/ACTIONABLE_WORK_ITEMS.md §AZ-P3-16):
    1. معلم بلا صف محفظة تُفتح له عند أول تسوية وتُكتب الساقان كاملتين.
    2. التخطي الصامت لا يحدث؛ ما لا يُسوَّى يفشل صراحةً مع تنبيه إداري.
    3. رصيد المحفظة = مجموع قيود الدفتر المطابقة (قابلية مطابقة).
    4. إكمال الجلسة مرتين لا ينشئ قيداً ثانياً (التزام idempotent).
    """

    def _login_existing(self, app, uid):
        """جلسة عميل لحساب قائم — بعض حالات الفشل لا تمرّ بمسار الشخصيات."""
        from app.extensions import db
        from app.models.user import User

        with app.app_context():
            email = db.session.get(User, uid).email
        client = app.test_client()
        client.post("/auth/login", data={"email": email, "password": _PASSWORD})
        return client

    def _session_without_wallet(self, app, *, price=100.0):
        """يعلم + طالب في مدرسة واحدة بلا أي صف محفظة مُهيأ مسبقاً."""
        from app.models.wallet import Wallet

        sid = make_school(app)
        tutor = make_user(app, role="teacher", school_id=sid)
        student = make_user(app, role="student", school_id=sid)
        session_id = make_tutoring_session(app, tutor_id=tutor, student_id=student, price=price)
        with app.app_context():
            assert Wallet.query.filter_by(school_id=sid, user_id=tutor).first() is None
        return sid, tutor, student, session_id

    def _settle(self, app, session_id):
        """تسوية واحدة → ``(أُنشئ السجل؟، صافي المعلم)`` مقروءان داخل الجلسة."""
        from app.extensions import db
        from app.models.tutoring import TutoringSession
        from app.services.tutoring import create_commission_record

        with app.app_context():
            created = create_commission_record(db.session.get(TutoringSession, session_id))
            return created is not None, (created.tutor_net if created is not None else None)

    def test_missing_wallet_is_created_and_both_legs_written(self, app):
        from app.models.wallet import Wallet, WalletTransaction

        sid, tutor, _student, session_id = self._session_without_wallet(app, price=250.0)
        created, tutor_net = self._settle(app, session_id)
        assert created is True

        with app.app_context():
            wallet = Wallet.query.filter_by(school_id=sid, user_id=tutor).one()
            legs = WalletTransaction.query.filter_by(
                reference_type="tutoring_session", reference_id=session_id
            ).all()
            by_type = {leg.transaction_type: leg for leg in legs}
            assert set(by_type) == {"tutor_session_credit", "tutor_commission"}
            assert by_type["tutor_session_credit"].amount == Decimal("250.00")
            assert by_type["tutor_session_credit"].destination_wallet_id == wallet.id
            assert by_type["tutor_commission"].amount == Decimal("50.00")  # 20%
            assert by_type["tutor_commission"].source_wallet_id == wallet.id
            assert wallet.balance == Decimal("200.00")
            assert wallet.balance == tutor_net  # صافي سجل العمولة نفسه

    def test_balance_matches_ledger_sum_across_sessions(self, app):
        """مطابقة (reconciliation): الرصيد = مجموع قيود الدفتر المطابقة دائماً."""
        from app.models.wallet import Wallet, WalletTransaction

        sid, tutor, student, first = self._session_without_wallet(app, price=100.0)
        second = make_tutoring_session(app, tutor_id=tutor, student_id=student, price=300.0)
        self._settle(app, first)
        self._settle(app, second)

        with app.app_context():
            wallet = Wallet.query.filter_by(school_id=sid, user_id=tutor).one()
            legs = WalletTransaction.query.filter_by(school_id=sid).all()
            ledger_net = sum(
                leg.amount if leg.transaction_type == "tutor_session_credit" else -leg.amount for leg in legs
            )
            assert len(legs) == 4  # ساقان لكل جلسة
            assert ledger_net == Decimal("320.00")  # 80 + 240
            assert wallet.balance == ledger_net

    def test_recompletion_does_not_double_the_ledger(self, app):
        from app.models.tutoring import TutorCommission
        from app.models.wallet import Wallet, WalletTransaction

        sid, tutor, _student, session_id = self._session_without_wallet(app, price=200.0)
        assert self._settle(app, session_id)[0] is True
        assert self._settle(app, session_id)[0] is False  # سجل قائم → لا عمل ثانٍ

        with app.app_context():
            assert TutorCommission.query.filter_by(session_id=session_id).count() == 1
            legs = WalletTransaction.query.filter_by(reference_id=session_id, reference_type="tutoring_session").all()
            assert len(legs) == 2
            assert Wallet.query.filter_by(school_id=sid, user_id=tutor).one().balance == Decimal("160.00")

    def test_school_less_tutor_settlement_fails_explicitly(self, app):
        """الجلسة تُكتمل لكنها تبقى غير مسوّاة — بمبلغ صريح لا تخطٍّ صامت."""
        from app.core.db import TxError
        from app.extensions import db
        from app.models.communication import Notification
        from app.models.tutoring import TutorCommission, TutoringSession
        from app.models.user import User, UserRole
        from app.models.wallet import Wallet, WalletTransaction

        sid = make_school(app)
        tutor = make_user(app, role="teacher")  # بلا عضوية مدرسة نشطة
        student = make_user(app, role="student", school_id=sid)
        make_user(app, role="super_admin")
        session_id = make_tutoring_session(app, tutor_id=tutor, student_id=student, price=100.0)

        with app.app_context():
            from app.models.tutoring import TutoringSession as TS
            from app.services.tutoring import create_commission_record

            with pytest.raises(TxError) as exc:
                create_commission_record(db.session.get(TS, session_id))
            assert "لا مدرسة نشطة" in str(exc.value)
            assert TutorCommission.query.filter_by(session_id=session_id).count() == 0
            assert WalletTransaction.query.filter_by(reference_id=session_id).count() == 0
            assert Wallet.query.filter_by(user_id=tutor).count() == 0
            assert db.session.get(TS, session_id).status == "completed"  # مكتملة، غير مسوّاة

        client = self._login_existing(app, tutor)
        resp = client.get(f"/tutoring/sessions/{session_id}/status/completed", follow_redirects=True)
        assert resp.status_code == 200
        assert "لا مدرسة نشطة" in resp.get_data(as_text=True)

        with app.app_context():
            admins = User.query.filter_by(role=UserRole.super_admin).all()
            assert admins
            alerts = Notification.query.filter_by(type="tutoring_settlement").all()
            assert alerts, "فشل التسوية يجب أن يُسجَّل تنبيهاً إدارياً"
            assert {alert.user_id for alert in alerts} <= {admin.id for admin in admins}
            assert all(str(session_id) in (alert.body or "") for alert in alerts)
            assert TutorCommission.query.filter_by(session_id=session_id).count() == 0

        from app.models.system import AuditLog

        with app.app_context():
            failure = AuditLog.query.filter_by(action="tutoring.settlement_failed").one()
            assert failure.detail["reason"] and failure.detail["status"] == "completed"
            assert db.session.get(TutoringSession, session_id).status == "completed"


class TestAdminCredit:
    def test_credit_non_positive_amount_rejected(self, app):
        from app.services.wallet_service import admin_credit

        sid = make_school(app)
        uid = make_user(app, role="student", school_id=sid)
        with app.app_context():
            _, err = admin_credit(sid, uid, Decimal("0"), f"b5-{uuid.uuid4().hex[:8]}", "desc")
        assert err is not None

    def test_credit_success_increases_balance(self, app):
        from app.services.wallet_service import admin_credit, get_balance

        sid = make_school(app)
        uid = make_user(app, role="student", school_id=sid)
        _wallet(app, sid, uid)
        key = f"b5-{uuid.uuid4().hex[:8]}"
        with app.app_context():
            ledger, err = admin_credit(sid, uid, Decimal("75.555"), key, "إيداع إداري", operator_id=None)
            assert err is None
            assert ledger.amount == Decimal("75.56")  # ROUND_HALF_UP
            assert ledger.source_wallet_id is None  # external inflow
            assert ledger.transaction_type == "admin_adjustment"
            assert get_balance(sid, uid) == Decimal("75.56")

    def test_credit_idempotent_hit(self, app):
        from app.services.wallet_service import admin_credit, get_balance

        sid = make_school(app)
        uid = make_user(app, role="student", school_id=sid)
        _wallet(app, sid, uid)
        key = f"b5-{uuid.uuid4().hex[:8]}"
        with app.app_context():
            first, err1 = admin_credit(sid, uid, Decimal("10"), key, "d1")
            replay, err2 = admin_credit(sid, uid, Decimal("10"), key, "d2")
            assert err1 is None and err2 is None
            assert first.id == replay.id
            assert get_balance(sid, uid) == Decimal("10.00")

    def test_credit_missing_wallet_fails(self, app):
        from app.services.wallet_service import admin_credit

        sid = make_school(app)
        uid = make_user(app, role="student", school_id=sid)
        with app.app_context():
            _, err = admin_credit(sid, uid, Decimal("10"), f"b5-{uuid.uuid4().hex[:8]}", "d")
        assert err is not None


class TestTransactionHistory:
    def test_history_without_wallet_empty(self, app):
        from app.services.wallet_service import get_transaction_history

        sid = make_school(app)
        uid = make_user(app, role="student", school_id=sid)
        with app.app_context():
            assert get_transaction_history(sid, uid) == []

    def test_history_returns_both_sides_of_ledger(self, app):
        from app.services.wallet_service import get_transaction_history

        sid = make_school(app)
        uid = make_user(app, role="student", school_id=sid)
        uid2 = make_user(app, role="student", school_id=sid)
        w1 = _wallet(app, sid, uid)
        _wallet(app, sid, uid2)
        with app.app_context():
            from app.extensions import db
            from app.models.wallet import Wallet

            src = db.session.get(Wallet, w1)
            assert src is not None
            src.balance = Decimal("50.00")
            db.session.commit()
            _xfer(app, sid, uid, uid2, Decimal("5"), f"b5-{uuid.uuid4().hex[:8]}")
            _xfer(app, sid, uid2, uid, Decimal("2"), f"b5-{uuid.uuid4().hex[:8]}")
            history = get_transaction_history(sid, uid)
            assert len(history) == 2  # one debit + one credit side
            assert all(t.status == "completed" for t in history)


# ════════════════════════════════════════════════════════════════════
# Invoice service
# ════════════════════════════════════════════════════════════════════


class TestInvoiceService:
    def _full_chain(self, app):
        sid = make_school(app)
        uid = make_user(app, role="student", school_id=sid)
        grade = make_grade(app, sid)
        subject = make_subject(app)
        cid = make_class(app, sid, grade, subject)
        plan = make_subscription_plan(app, sid, cid, price=75.0)
        sub = make_subscription(app, uid, plan, cid, price=75.0, status="active")
        make_payment(app, sub, amount=75.0, status="approved")
        return sub

    def test_invoice_number_format(self, app):
        from app.services.invoice import generate_invoice_number

        sub_id = self._full_chain(app)
        with app.app_context():
            from app.extensions import db
            from app.models.billing import Subscription

            number = generate_invoice_number(db.session.get(Subscription, sub_id))
        year = datetime.now().year
        assert number.startswith("INV-") and f"-{year}-" in number

    def test_generate_html_missing_subscription_none(self, app):
        from app.services.invoice import generate_invoice_html

        with app.app_context():
            assert generate_invoice_html(99999999) is None

    def test_render_pdf_missing_subscription_none(self, app):
        from app.services.invoice import render_invoice_pdf

        with app.app_context():
            assert render_invoice_pdf(99999999) is None

    def test_render_pdf_produces_real_pdf_bytes(self, app, tmp_path, monkeypatch):
        from app.extensions import db
        from app.models.user import User
        from app.services.invoice import render_invoice_pdf
        from flask_login import login_user

        sub_id = self._full_chain(app)
        monkeypatch.setitem(app.config, "UPLOAD_FOLDER", str(tmp_path))
        with app.test_request_context():
            user = db.session.get(User, 1)  # subscription owner user_id=1
            if user:
                login_user(user)
            pdf = render_invoice_pdf(sub_id)
        assert pdf is not None
        assert bytes(pdf)[:5] == b"%PDF-"

# ════════════════════════════════════════════════════════════════════
# AZ-P1-06 — تقرير عمولات المنصة للأدمن
# ════════════════════════════════════════════════════════════════════
# القيود تُكتب فعلاً في الدفتر عند إتمام كل جلسة، وكانت بلا أي واجهة تقرأها.
# الاختبارات تبذر قيوداً (عبر جلسات حقيقية — session_id NOT NULL ومرجع أجنبي)
# وتتحقق من: الاستقلال عن إيراد اشتراكات الطلاب، والتجميع الشهري ولكل مدرسة،
# وإسناد العمولة إلى مدرسة المعلّم (لا مجاميع مدارس أخرى)، وظهور الصفر صراحة.


def _commission(app, school_id=None, amount=100.0, rate=20.0, status="pending"):
    """قيد عمولة حقيقي: معلّم (برابط مدرسي اختياري) + جلسة + صف الدفتر."""
    from app.extensions import db
    from app.models.tutoring import TutorCommission
    from tests.conftest import make_tutoring_session

    tutor_id = make_user(app, role="teacher", school_id=school_id)
    student_id = make_user(app, role="student")
    session_id = make_tutoring_session(app, tutor_id, student_id, price=amount)
    commission_amount = round(amount * rate / 100, 2)
    with app.app_context():
        row = TutorCommission(
            session_id=session_id,
            tutor_id=tutor_id,
            session_amount=amount,
            commission_rate=rate,
            commission_amount=commission_amount,
            tutor_net=round(amount - commission_amount, 2),
            status=status,
        )
        db.session.add(row)
        db.session.commit()
        return row.id, tutor_id


class TestPlatformCommissionReport:
    def test_commission_is_independent_of_student_subscriptions(self, app):
        """صف العمولة يقيس الدفتر، لا اشتراكات الطلاب — الرقمان من مصدرين."""
        from app.services.revenue import get_commission_summary, get_revenue_summary

        sid = make_school(app)
        student = make_user(app, role="student", school_id=sid)
        grade = make_grade(app, sid)
        subject = make_subject(app)
        cid = make_class(app, sid, grade, subject)
        plan = make_subscription_plan(app, sid, cid, price=500.0)
        sub = make_subscription(app, student, plan, cid, price=500.0, status="active")
        make_payment(app, sub, amount=500.0, status="approved")
        _commission(app, school_id=sid, amount=100.0)

        with app.app_context():
            commission = get_commission_summary()
            subscriptions = get_revenue_summary()
            assert subscriptions["total_revenue"] == 500.0
            assert commission["total_commission"] == 20.0
            assert commission["transaction_count"] == 1

    def test_summary_splits_pending_and_counts_sessions(self, app):
        from app.services.revenue import get_commission_summary

        sid = make_school(app)
        _commission(app, school_id=sid, amount=100.0, status="pending")
        _commission(app, school_id=sid, amount=200.0, status="withdrawn")

        with app.app_context():
            data = get_commission_summary(school_id=sid)
            assert data["total_commission"] == 60.0  # 20 + 40
            assert data["session_total"] == 300.0
            assert data["transaction_count"] == 2
            assert data["pending_commission"] == 20.0
            assert data["pending_count"] == 1
            assert data["commission_rate"] == 20.0

    def test_school_scope_never_returns_another_school(self, app):
        """أدمن مدرسة A يرى مجموع A فقط — لا تسريب مجموع B في النطاق المدرسي."""
        from app.services.revenue import get_commission_summary

        school_a = make_school(app)
        school_b = make_school(app)
        _commission(app, school_id=school_a, amount=100.0)
        _commission(app, school_id=school_b, amount=300.0)
        _commission(app, school_id=school_b, amount=100.0)

        with app.app_context():
            scoped_a = get_commission_summary(school_id=school_a)
            scoped_b = get_commission_summary(school_id=school_b)
            platform = get_commission_summary()
            assert scoped_a["total_commission"] == 20.0
            assert scoped_a["transaction_count"] == 1
            assert scoped_b["total_commission"] == 80.0
            assert platform["total_commission"] == 100.0
            assert platform["school_id"] is None

    def test_by_school_attributes_each_commission_once(self, app):
        from app.services.revenue import get_commission_by_school

        school_a = make_school(app, name_ar="مدرسة أ")
        school_b = make_school(app, name_ar="مدرسة ب")
        _commission(app, school_id=school_a, amount=100.0)
        _commission(app, school_id=school_a, amount=100.0)
        _commission(app, school_id=school_b, amount=500.0)

        with app.app_context():
            rows = get_commission_by_school()
            by_id = {r["school_id"]: r for r in rows}
            assert by_id[school_a]["total"] == 40.0
            assert by_id[school_a]["count"] == 2
            assert by_id[school_b]["total"] == 100.0
            assert by_id[school_b]["count"] == 1

            scoped = get_commission_by_school(school_id=school_a)
            assert [r["school_id"] for r in scoped] == [school_a]

    def test_unattributed_commission_stays_in_the_total(self, app):
        """معلّم بلا رابط مدرسي: يظهر في الإجمالي ولا يختفي، ولا يظهر في التوزيع."""
        from app.services.revenue import get_commission_by_school, get_commission_summary

        school_a = make_school(app)
        _commission(app, school_id=school_a, amount=100.0)
        _commission(app, school_id=None, amount=100.0)

        with app.app_context():
            assert get_commission_summary()["total_commission"] == 40.0
            rows = get_commission_by_school()
            assert sum(r["count"] for r in rows) == 1
            assert sum(r["total"] for r in rows) == 20.0

    def test_monthly_trend_is_grouped_by_month(self, app):
        from app.services.revenue import get_commission_monthly_trend

        school_a = make_school(app)
        _commission(app, school_id=school_a, amount=100.0)

        with app.app_context():
            trend = get_commission_monthly_trend(12)
            assert len(trend) == 1
            assert trend[0]["month"] == datetime.now(UTC).strftime("%Y-%m")
            assert trend[0]["total"] == 20.0
            assert trend[0]["count"] == 1
            assert get_commission_monthly_trend(12, school_id=make_school(app)) == []

    def test_empty_ledger_reports_explicit_zeroes(self, app):
        """لا بيانات → أصفار صريحة لا `None` ولا فراغ يوهم بأن التقرير معطل."""
        from app.services.revenue import (
            get_commission_by_school,
            get_commission_monthly_trend,
            get_commission_summary,
        )

        empty_school = make_school(app)
        with app.app_context():
            summary = get_commission_summary(school_id=empty_school)
            assert summary["total_commission"] == 0.0
            assert summary["session_total"] == 0.0
            assert summary["transaction_count"] == 0
            assert summary["pending_commission"] == 0.0
            assert summary["pending_count"] == 0
            assert get_commission_by_school(school_id=empty_school) == []
            assert get_commission_monthly_trend(12, school_id=empty_school) == []

    def test_revenue_dashboard_data_carries_the_commission_block(self, app):
        from app.services.revenue import get_revenue_dashboard_data

        sid = make_school(app)
        _commission(app, school_id=sid, amount=100.0)
        with app.app_context():
            data = get_revenue_dashboard_data(days=30)
            assert {"summary", "by_school", "monthly_trend"} <= set(data["commission"])
            assert data["commission"]["summary"]["total_commission"] == 20.0

    def test_revenue_page_renders_the_commission_report(self, app):
        """صفحة الإيرادات تعرض صف العمولة ومدارسه — لا تقرير في الخدمة فقط."""
        sid = make_school(app, name_ar="مدرسة العمولة")
        _commission(app, school_id=sid, amount=100.0)
        _uid, client = _persona(app, "super_admin")

        resp = client.get("/admin/revenue")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert "commission-note" in html
        assert "مدرسة العمولة" in html

    def test_revenue_page_states_the_zero_explicitly(self, app):
        _uid, client = _persona(app, "super_admin")
        resp = client.get("/admin/revenue")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        # الصف الصفري بدل قسم مخفي: القارئ يرى أن الرقم صفر لا أنه ناقص.
        assert "لا عمولات مسجّلة في هذه الفترة" in html

    def test_school_admin_cannot_open_the_platform_report(self, app):
        sid = make_school(app)
        _uid, client = _persona(app, "school_admin", school_id=sid)
        resp = client.get("/admin/revenue", follow_redirects=False)
        assert resp.status_code in (302, 403)

# ════════════════════════════════════════════════════════════════════
# AZ-P1-07 — مستكشف دفتر المحفظة + عكس حركة
# ════════════════════════════════════════════════════════════════════
# الدفتر غير قابل للتغيير: العكس يُنشئ قيداً مقابلاً ولا يعدّل الأصل ولا
# يحذفه، ووجود القيد المقابل هو علامة «معكوسة». الاختبارات تتحقق من الأثر
# المالي الفعلي (الأرصدة)، ومن رفض العكس المكرّر، ومن بقاء التينانت، ومن
# كتابة سجل التدقيق مع المنفّذ في نفس المعاملة.


def _funded_transfer(app, amount=Decimal("100.00"), src_balance=Decimal("100.00")):
    """مدرسة + محفظتان ممولتان + تحويل مكتمل → (school_id, src, dst, tx_id)."""
    from app.extensions import db
    from app.models.wallet import Wallet

    sid = make_school(app)
    src = make_user(app, role="student", school_id=sid)
    dst = make_user(app, role="student", school_id=sid)
    src_wallet_id = _wallet(app, sid, src)
    _wallet(app, sid, dst)
    with app.app_context():
        wallet = db.session.get(Wallet, src_wallet_id)
        assert wallet is not None
        wallet.balance = src_balance
        db.session.commit()

    # الخدمة تحتاج سياق تطبيق، والكائن يصبح منتهي الصلاحية بعد الالتزام —
    # لذلك يُلتقط المعرّف داخل السياق لا بعده.
    with app.app_context():
        tx, err = _xfer(app, sid, src, dst, amount, f"b5-{uuid.uuid4().hex[:8]}")
        assert err is None and tx is not None
        tx_id = tx.id
    return sid, src, dst, tx_id


def _balances(app, school_id, user_id):
    from app.services.wallet_service import get_balance

    with app.app_context():
        return get_balance(school_id, user_id)


class TestLedgerReversal:
    def test_reversal_appends_offsetting_entry_and_restores_balances(self, app):
        from app.extensions import db
        from app.models.wallet import WalletTransaction
        from app.services.wallet_service import reverse_transaction

        sid, src, dst, tx_id = _funded_transfer(app)
        before_src = _balances(app, sid, src)
        before_dst = _balances(app, sid, dst)

        with app.app_context():
            reversal, err = reverse_transaction(
                school_id=sid, transaction_id=tx_id, operator_id=None, reason="خطأ إدخال"
            )
            assert err is None
            assert reversal is not None
            assert reversal.transaction_type == "reversal"
            assert reversal.reference_type == "wallet_reversal"
            assert reversal.reference_id == tx_id

            original = db.session.get(WalletTransaction, tx_id)
            # الأصل كما هو بالحرف: لا تعديل ولا حذف (دفتر غير قابل للتغيير).
            assert original is not None
            assert original.status == "completed"
            assert original.amount == Decimal("100.00")
            assert original.source_wallet_id == reversal.destination_wallet_id
            assert original.destination_wallet_id == reversal.source_wallet_id

        assert _balances(app, sid, src) == before_src + Decimal("100.00")
        assert _balances(app, sid, dst) == before_dst - Decimal("100.00")

    def test_reversal_carries_its_reason_and_operator(self, app):
        from app.services.wallet_service import reverse_transaction

        sid, _src, _dst, tx_id = _funded_transfer(app)
        operator = make_user(app, role="super_admin")
        with app.app_context():
            reversal, err = reverse_transaction(
                school_id=sid, transaction_id=tx_id, operator_id=operator, reason="تكرار إدخال"
            )
            assert err is None
            assert reversal.description == "تكرار إدخال"
            assert reversal.metadata_json["reversed_by"] == operator

    def test_second_reversal_is_rejected_with_one_offsetting_entry(self, app):
        from app.extensions import db
        from app.models.wallet import WalletTransaction
        from app.services.wallet_service import reverse_transaction

        sid, src, dst, tx_id = _funded_transfer(app)
        with app.app_context():
            _first, err = reverse_transaction(school_id=sid, transaction_id=tx_id)
            assert err is None
            after_first = (_balances(app, sid, src), _balances(app, sid, dst))

            second, err2 = reverse_transaction(school_id=sid, transaction_id=tx_id)
            assert second is None
            assert err2 is not None
            assert "معكوسة" in err2

            assert (
                WalletTransaction.query.filter_by(reference_type="wallet_reversal", reference_id=tx_id).count() == 1
            )
            assert db.session.get(WalletTransaction, tx_id).status == "completed"

        assert (_balances(app, sid, src), _balances(app, sid, dst)) == after_first

    def test_reversal_cannot_reach_another_school(self, app):
        """حدّ التينانت: عكس باسم مدرسة أخرى لا يجد الحركة ولا يحرّك رصيداً."""
        from app.services.wallet_service import reverse_transaction

        sid, src, dst, tx_id = _funded_transfer(app)
        other_school = make_school(app)
        before = (_balances(app, sid, src), _balances(app, sid, dst))

        with app.app_context():
            reversal, err = reverse_transaction(school_id=other_school, transaction_id=tx_id)
            assert reversal is None
            assert err is not None

        assert (_balances(app, sid, src), _balances(app, sid, dst)) == before

    def test_reversal_of_admin_deposit_takes_money_out_of_the_system(self, app):
        from app.services.wallet_service import admin_credit, get_balance, reverse_transaction

        sid = make_school(app)
        student = make_user(app, role="student", school_id=sid)
        _wallet(app, sid, student)
        with app.app_context():
            tx, err = admin_credit(
                school_id=sid,
                target_user_id=student,
                amount=Decimal("75.00"),
                idempotency_key=f"b5-{uuid.uuid4().hex[:8]}",
                description="إيداع إداري",
            )
            assert err is None
            assert tx.source_wallet_id is None
            assert get_balance(sid, student) == Decimal("75.00")

            reversal, err2 = reverse_transaction(school_id=sid, transaction_id=tx.id)
            assert err2 is None
            # المال دخل من خارج النظام فيدخل من خارج النظام: بلا محفظة مقابلة.
            assert reversal.source_wallet_id == tx.destination_wallet_id
            assert reversal.destination_wallet_id is None
            assert get_balance(sid, student) == Decimal("0.00")

    def test_reversal_requires_the_money_to_still_be_there(self, app):
        """رصيد مصروف لا يُعكس برقم سالب — يُرفض برسالة والرصيد ثابت."""
        from app.services.wallet_service import reverse_transaction

        sid, src, dst, tx_id = _funded_transfer(app)
        third = make_user(app, role="student", school_id=sid)
        _wallet(app, sid, third)
        with app.app_context():
            spent, err = _xfer(app, sid, dst, third, Decimal("100.00"), f"b5-{uuid.uuid4().hex[:8]}")
        assert err is None and spent is not None
        before = (_balances(app, sid, dst), _balances(app, sid, third))

        with app.app_context():
            reversal, err2 = reverse_transaction(school_id=sid, transaction_id=tx_id)
            assert reversal is None
            assert err2 is not None
            assert "رصيد" in err2

        assert (_balances(app, sid, dst), _balances(app, sid, third)) == before

    def test_a_reversal_cannot_be_reversed(self, app):
        from app.services.wallet_service import reverse_transaction

        sid, _src, _dst, tx_id = _funded_transfer(app)
        with app.app_context():
            reversal, err = reverse_transaction(school_id=sid, transaction_id=tx_id)
            assert err is None
            nested, err2 = reverse_transaction(school_id=sid, transaction_id=reversal.id)
            assert nested is None
            assert err2 is not None
            assert "قيد عكس" in err2


class TestWalletLedgerAdminRoutes:
    def test_super_admin_reversal_creates_entry_and_audit(self, app):
        from app.extensions import db
        from app.models.system import AuditLog
        from app.models.wallet import WalletTransaction

        sid, _src, _dst, tx_id = _funded_transfer(app)
        admin_id, client = _persona(app, "super_admin")

        resp = client.post(f"/admin/wallet/{tx_id}/reverse", data={"reason": "عكس بطلب المالك"})
        assert resp.status_code == 302

        with app.app_context():
            reversal = WalletTransaction.query.filter_by(
                reference_type="wallet_reversal", reference_id=tx_id
            ).one()
            assert reversal.transaction_type == "reversal"
            # الأصل ما زال قائماً بحالته.
            assert db.session.get(WalletTransaction, tx_id).status == "completed"

            log = AuditLog.query.filter_by(action="wallet_reversal").one()
            assert log.user_id == admin_id
            assert log.detail["transaction_id"] == tx_id
            assert log.detail["reversal_id"] == reversal.id
            assert log.detail["school_id"] == sid

    def test_second_route_reversal_is_refused_without_a_second_entry(self, app):
        from app.models.wallet import WalletTransaction

        _sid, _src, _dst, tx_id = _funded_transfer(app)
        _admin_id, client = _persona(app, "super_admin")

        assert client.post(f"/admin/wallet/{tx_id}/reverse", data={}).status_code == 302
        second = client.post(f"/admin/wallet/{tx_id}/reverse", data={}, follow_redirects=True)
        assert second.status_code == 200

        with app.app_context():
            assert (
                WalletTransaction.query.filter_by(reference_type="wallet_reversal", reference_id=tx_id).count() == 1
            )

    def test_unknown_transaction_is_404(self, app):
        _admin_id, client = _persona(app, "super_admin")
        assert client.post("/admin/wallet/99999999/reverse", data={}).status_code == 404

    def test_school_admin_neither_sees_nor_reverses(self, app):
        from app.models.wallet import WalletTransaction

        sid, _src, _dst, tx_id = _funded_transfer(app)
        _uid, client = _persona(app, "school_admin", school_id=sid)

        assert client.get("/admin/wallet", follow_redirects=False).status_code in (302, 403)
        assert client.post(f"/admin/wallet/{tx_id}/reverse", data={}, follow_redirects=False).status_code in (302, 403)

        with app.app_context():
            assert (
                WalletTransaction.query.filter_by(reference_type="wallet_reversal", reference_id=tx_id).count() == 0
            )

    def test_ledger_explorer_lists_rows_and_filters_by_school(self, app):
        sid, _src, _dst, tx_id = _funded_transfer(app)
        other_sid, _s2, _d2, other_tx_id = _funded_transfer(app)
        _uid, client = _persona(app, "super_admin")

        page = client.get("/admin/wallet")
        assert page.status_code == 200
        html = page.get_data(as_text=True)
        assert "ledger-immutability-note" in html
        assert f'data-row-id="{tx_id}"' in html
        assert f'data-row-id="{other_tx_id}"' in html

        filtered = client.get(f"/admin/wallet?school_id={sid}")
        filtered_html = filtered.get_data(as_text=True)
        assert f'data-row-id="{tx_id}"' in filtered_html
        assert f'data-row-id="{other_tx_id}"' not in filtered_html
        assert other_sid != sid

    def test_ledger_explorer_shows_the_reversal_state(self, app):
        _sid, _src, _dst, tx_id = _funded_transfer(app)
        _admin_id, client = _persona(app, "super_admin")
        client.post(f"/admin/wallet/{tx_id}/reverse", data={})

        page = client.get("/admin/wallet")
        assert page.status_code == 200
        html = page.get_data(as_text=True)
        assert "معكوسة" in html
