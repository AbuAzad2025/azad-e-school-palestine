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
(xhtml2pdf is installed in this environment).
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

    def test_whatsapp_webhook_receives_messages(self, app):
        client = app.test_client()
        resp = client.post("/api/payments/webhook/whatsapp")
        assert resp.status_code == 200
        assert resp.get_json() == {"status": "received"}

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
        fake.verify_payment.return_value = True
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
        from flask_login import login_user
        from app.models.user import User
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

    def test_render_pdf_produces_real_pdf_bytes(self, app):
        from app.services.invoice import render_invoice_pdf
        from flask_login import login_user
        from app.models.user import User
        from app.extensions import db

        sub_id = self._full_chain(app)
        with app.test_request_context():
            user = db.session.get(User, 1)  # subscription owner user_id=1
            if user:
                login_user(user)
            pdf = render_invoice_pdf(sub_id)
        assert pdf is not None
        assert bytes(pdf)[:5] == b"%PDF-"
