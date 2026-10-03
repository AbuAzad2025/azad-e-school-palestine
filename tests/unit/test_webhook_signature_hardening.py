"""تحصين توقيعات Webhook — اختبارات ما بعد الفحص.

تغطّي ثلاثة مستويات:
    1. app/core/webhooks.py — أساسيات fail-closed وثابتة الزمن.
    2. app/services/payments.py — التحقق لكل بوابة ومنع التفعيل المزدوج.
    3. ربط المبلغ بسعر الخطة قبل التفعيل.

كل اختبار سالب يقابل اختباراً موجباً: نفس المسار بتوقيع خاطئ يُرفض،
وكل اختبار موجب يُقابله ما يثبت أن تحريف الحمولة يُرفض.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from app.core.webhooks import (
    MAX_WEBHOOK_BYTES,
    canonical_payload_bytes,
    header_value,
    safe_json_loads,
    signature_matches,
    signing_body,
    verify_hmac_webhook,
)
from app.services.payments import PaymentGateway, PaymentService

SECRET = "whsec_test_secret"


def _sign(body: bytes, secret: str = SECRET) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


# ═══════════════════════════ أساسيات webhooks.py ═══════════════════════════
class TestSignaturePrimitives:
    """دوال التحقق الأساسية — الفحص الفردي."""

    def test_signature_matches_positive_and_negative(self):
        body = b'{"a":1}'
        assert signature_matches(SECRET, body, _sign(body)) is True
        assert signature_matches(SECRET, body, _sign(body, "other")) is False

    def test_missing_secret_fails_closed(self):
        """بلا سر = رفض صريح، لا تجاوز صامت."""
        assert signature_matches(None, b"x", _sign(b"x")) is False
        assert signature_matches("", b"x", _sign(b"x")) is False

    def test_empty_signature_fails_closed(self):
        assert signature_matches(SECRET, b"x", "") is False

    def test_algorithm_prefix_is_accepted(self):
        """بعض المرسلين يضعون sha256= قبل الهكس."""
        body = b'{"b":2}'
        assert signature_matches(SECRET, body, f"sha256={_sign(body)}") is True
        assert signature_matches(SECRET, body, f"SHA256={_sign(body)}") is True

    def test_header_lookup_is_case_insensitive(self):
        headers = {"x-paytabs-signature": "abc"}
        assert header_value(headers, "X-Paytabs-Signature") == "abc"
        assert header_value(headers, "X-PAYTABS-SIGNATURE") == "abc"
        assert header_value(headers, "Missing") == ""
        assert header_value(None, "Any") == ""
        assert header_value({}, "Any") == ""

    def test_canonical_payload_bytes_is_deterministic(self):
        """ترتيب المفاتيح لا يغيّر البايتات ⇒Same body ⇒ same signature."""
        a = canonical_payload_bytes({"b": 1, "a": 2})
        b = canonical_payload_bytes({"a": 2, "b": 1})
        assert a == b
        assert canonical_payload_bytes(b"raw") == b"raw"
        assert canonical_payload_bytes("text") == b"text"

    def test_signing_body_prefers_raw_bytes(self):
        """الجسم الخام يتقدّم على JSON المُعاد ترميزه."""
        raw = b'{"x": 1,  "y": 2}'
        assert signing_body(raw, {"x": 1, "y": 2}) == raw
        assert signing_body(None, {"x": 1}) == canonical_payload_bytes({"x": 1})
        assert signing_body(b"", {"x": 1}) == canonical_payload_bytes({"x": 1})

    def test_safe_json_loads_is_total(self):
        assert safe_json_loads(b'{"a":1}') == {"a": 1}
        assert safe_json_loads(b"not json") == {}
        assert safe_json_loads(b"[1,2]") == {}
        assert safe_json_loads(None) == {}

    def test_oversized_body_is_rejected(self):
        """حمولة أكبر من السقف تُرفض قبل أي حساب توقيع."""
        big = b"x" * (MAX_WEBHOOK_BYTES + 1)
        assert (
            verify_hmac_webhook(
                secret=SECRET,
                headers={"X-Paytabs-Signature": _sign(big)},
                header_name="X-Paytabs-Signature",
                raw_body=big,
                payload={},
                gateway="paytabs",
            )
            is False
        )

    def test_verify_hmac_webhook_end_to_end(self):
        body = b'{"tran_ref":"T1"}'
        good = verify_hmac_webhook(
            secret=SECRET,
            headers={"X-Paytabs-Signature": _sign(body)},
            header_name="X-Paytabs-Signature",
            raw_body=body,
            payload={"tran_ref": "T1"},
            gateway="paytabs",
        )
        assert good is True
        # نفس الترويسة على جسم مُعدَّل = رفض (تلاعب بالحمولة)
        tampered = verify_hmac_webhook(
            secret=SECRET,
            headers={"X-Paytabs-Signature": _sign(body)},
            header_name="X-Paytabs-Signature",
            raw_body=b'{"tran_ref":"T2"}',
            payload={"tran_ref": "T2"},
            gateway="paytabs",
        )
        assert tampered is False
        # ترويسة غائبة = رفض
        assert (
            verify_hmac_webhook(
                secret=SECRET,
                headers={},
                header_name="X-Paytabs-Signature",
                raw_body=body,
                payload={},
                gateway="paytabs",
            )
            is False
        )

    def test_canonical_fallback_accepts_legacy_callers(self):
        """مستدعون بلا جسم خام (مهام/اختبارات) يوقّعون على JSON حتمي."""
        payload = {"tran_ref": "T9"}
        assert (
            verify_hmac_webhook(
                secret=SECRET,
                headers={"X-Cashu-Signature": _sign(canonical_payload_bytes(payload))},
                header_name="X-Cashu-Signature",
                raw_body=None,
                payload=payload,
                gateway="cashu",
            )
            is True
        )


# ═══════════════════════════ البوابات ═══════════════════════════
class TestGatewayVerification:
    """PayTabs/CashU: توقيع خام + معرّف حدث إلزامي."""

    def _paytabs(self, secret=SECRET):
        from app.services.payments import PayTabsGateway

        return PayTabsGateway({"profile_id": "p", "server_key": "s", "webhook_secret": secret})

    def _cashu(self, secret=SECRET):
        from app.services.payments import CashUGateway

        return CashUGateway({"merchant_id": "m", "encryption_key": "k", "webhook_secret": secret})

    def test_paytabs_rejects_missing_secret(self):
        result = self._paytabs(secret=None).verify_webhook({"payload": {"tran_ref": "T1"}, "headers": {}})
        assert result.verified is False
        assert result.reason == "webhook_secret_missing"

    def test_paytabs_rejects_bad_signature(self, app):
        gw = self._paytabs()
        result = gw.verify_webhook({"payload": {"tran_ref": "T1"}, "headers": {"X-Paytabs-Signature": "deadbeef"}})
        assert result.verified is False
        assert result.reason == "signature_invalid"

    def test_paytabs_verifies_raw_body_and_remembers_event(self, app):
        from app.extensions import db
        from app.models.billing import ProcessedEvent

        gw = self._paytabs()
        payload = {"tran_ref": "T100", "cart_amount": "50.00"}
        body = json.dumps(payload).encode()
        headers = {"X-Paytabs-Signature": _sign(body)}
        with app.app_context(), patch("requests.get") as get:
            get.return_value = MagicMock(status_code=200, json=lambda: {"payment_result": {"response_code": "100"}})
            first = gw.verify_webhook({"payload": payload, "headers": headers, "raw_body": body})
            assert first.verified is True
            assert first.already_processed is False
            db.session.flush()
            assert db.session.query(ProcessedEvent).filter_by(event_id="paytabs_T100").count() == 1
            # إعادة الإرسال: موقّع لكن سبق معالجته ⇒ لا يُخزَّن مرتين
            second = gw.verify_webhook({"payload": payload, "headers": headers, "raw_body": body})
            assert second.verified is True
            assert second.already_processed is True
            assert second.reason == "duplicate_event"
            db.session.commit()
            assert db.session.query(ProcessedEvent).filter_by(event_id="paytabs_T100").count() == 1

    def test_paytabs_without_tran_ref_fails_closed(self, app):
        """لا معرّف حدث ⇒ لا idمبس-so لا معالجة (fail-closed)."""
        gw = self._paytabs()
        payload = {"cart_amount": "50.00"}
        body = json.dumps(payload).encode()
        result = gw.verify_webhook(
            {"payload": payload, "headers": {"X-Paytabs-Signature": _sign(body)}, "raw_body": body}
        )
        assert result.verified is False
        assert result.reason == "missing_tran_ref"

    def test_paytabs_gateway_query_failure_rejected(self, app):
        gw = self._paytabs()
        payload = {"tran_ref": "T200"}
        body = json.dumps(payload).encode()
        with app.app_context(), patch("requests.get") as get:
            get.return_value = MagicMock(status_code=500, json=lambda: {})
            result = gw.verify_webhook(
                {"payload": payload, "headers": {"X-Paytabs-Signature": _sign(body)}, "raw_body": body}
            )
        assert result.verified is False
        assert result.reason == "gateway_query_failed"

    def test_paytabs_query_exception_rejected(self, app):
        gw = self._paytabs()
        payload = {"tran_ref": "T201"}
        body = json.dumps(payload).encode()
        with app.app_context(), patch("requests.get", side_effect=RuntimeError("network")):
            result = gw.verify_webhook(
                {"payload": payload, "headers": {"X-Paytabs-Signature": _sign(body)}, "raw_body": body}
            )
        assert result.verified is False

    def test_cashu_verifies_raw_body(self, app):
        from app.extensions import db
        from app.models.billing import ProcessedEvent

        gw = self._cashu()
        payload = {"transaction_id": "C1", "amount": 50, "status": "completed"}
        body = json.dumps(payload).encode()
        headers = {"X-Cashu-Signature": _sign(body)}
        with app.app_context(), patch("requests.get") as get:
            get.return_value = MagicMock(status_code=200, json=lambda: {"status": "completed"})
            first = gw.verify_webhook({"payload": payload, "headers": headers, "raw_body": body})
            assert first.verified is True and first.already_processed is False
            db.session.flush()
            assert db.session.query(ProcessedEvent).filter_by(event_id="cashu_C1").count() == 1
            second = gw.verify_webhook({"payload": payload, "headers": headers, "raw_body": body})
            assert second.already_processed is True
            db.session.commit()
            assert db.session.query(ProcessedEvent).filter_by(event_id="cashu_C1").count() == 1

    def test_cashu_without_transaction_id_fails_closed(self, app):
        gw = self._cashu()
        payload = {"amount": 50}
        body = json.dumps(payload).encode()
        result = gw.verify_webhook(
            {"payload": payload, "headers": {"X-Cashu-Signature": _sign(body)}, "raw_body": body}
        )
        assert result.verified is False
        assert result.reason == "missing_transaction_id"

    def test_cashu_query_failure_rejected(self, app):
        gw = self._cashu()
        payload = {"transaction_id": "C9"}
        body = json.dumps(payload).encode()
        with app.app_context(), patch("requests.get") as get:
            get.return_value = MagicMock(status_code=200, json=lambda: {"status": "pending"})
            result = gw.verify_webhook(
                {"payload": payload, "headers": {"X-Cashu-Signature": _sign(body)}, "raw_body": body}
            )
        assert result.verified is False
        assert result.reason == "gateway_query_failed"

    def test_verify_payment_wrapper_stays_boolean(self, app):
        """الواجهة القديمة تُرجع bool (توافق المستدعين الحاليين)."""
        from app.services.payments import PaymentGateway, PaymentIntent, PaymentStatus

        gw = self._paytabs()
        intent = PaymentIntent("paytabs_T1", PaymentGateway.PAYTABS, Decimal("1"), "ILS", PaymentStatus.PENDING, 1)
        assert gw.verify_payment(intent, {"payload": {"tran_ref": "T1"}, "headers": {}}) is False

    def test_cashu_query_exception_rejected(self, app):
        gw = self._cashu()
        payload = {"transaction_id": "C77"}
        body = json.dumps(payload).encode()
        with app.app_context(), patch("requests.get", side_effect=RuntimeError("network")):
            result = gw.verify_webhook(
                {"payload": payload, "headers": {"X-Cashu-Signature": _sign(body)}, "raw_body": body}
            )
        assert result.verified is False

    def test_manual_and_whatsapp_require_admin_approval(self, app):
        """الدفع اليدوي/واتساب لا يُصادَق تلقائياً — مصادَق المشرف فقط."""
        from app.services.payments import ManualPaymentGateway, WhatsAppPaymentGateway

        for gateway in (ManualPaymentGateway({}), WhatsAppPaymentGateway({})):
            rejected = gateway.verify_webhook({"payload": {}})
            assert rejected.verified is False
            assert rejected.reason == "manual_review_required"

            approved = gateway.verify_webhook({"admin_approved": True, "event_id": "E1", "already_processed": False})
            assert approved.verified is True
            assert approved.reason == "admin_approved"
            assert approved.event_id == "E1"
            assert approved.already_processed is False

            # المُعيد مُعلَّم مسبقاً — process_webhook يجب ألا يعيد التفعيل
            replay = gateway.verify_webhook({"admin_approved": True, "already_processed": True})
            assert replay.verified is True and replay.already_processed is True


class TestAmountMismatchBlocksActivation:
    """التكامل: webhook بمبلغ لا يطابق سعر الخطة ⇒ مراجعة يدوية بلا تفعيل."""

    def _subscription(self, app, price="500.00", currency="ILS"):
        from app.extensions import db
        from app.models.billing import Subscription, SubscriptionPlan
        from tests.conftest import make_class, make_grade, make_school, make_subject, make_user

        school_id = make_school(app)
        grade_id = make_grade(app, school_id)
        subject_id = make_subject(app)
        class_id = make_class(app, school_id, grade_id, subject_id)
        user_id = make_user(app, role="student", school_id=school_id)
        with app.app_context():
            plan = SubscriptionPlan(
                school_id=school_id,
                name="خطة",
                plan="first_term",
                price=Decimal(price),
                currency=currency,
            )
            db.session.add(plan)
            db.session.flush()
            sub = Subscription(
                user_id=user_id,
                plan_id=plan.id,
                class_id=class_id,
                price=Decimal(price),
                currency=currency,
                status="pending",
            )
            db.session.add(sub)
            db.session.commit()
            return sub.id

    def test_underpaid_webhook_is_flagged_not_activated(self, app):
        from app.extensions import db
        from app.models.billing import Subscription
        from app.services.payments import PaymentService
        from tests.conftest import make_user

        make_user(app, role="school_admin")  # يجب أن يصل إشعار المراجعة
        sub_id = self._subscription(app, price="500.00")
        payload = {
            "metadata": {"subscription_id": str(sub_id)},
            "cart_amount": "1.00",
            "cart_currency": "ILS",
        }
        with app.app_context():
            with patch("app.services.communication.notify") as notify:
                PaymentService()._handle_successful_payment(payload, PaymentGateway.PAYTABS)
            db.session.commit()
            sub = db.session.get(Subscription, sub_id)

        assert sub.status == "pending_review", "مبلغ غير مطابق نشّط الاشتراك"
        assert sub.start_at is None, "بدون تفعيل بلا تاريخ بداية"
        assert notify.called, "لم يُشعر المشرفون بالحالة"

    def test_currency_mismatch_is_flagged(self, app):
        from app.extensions import db
        from app.models.billing import Subscription
        from app.services.payments import PaymentService

        sub_id = self._subscription(app, price="500.00", currency="ILS")
        payload = {
            "metadata": {"subscription_id": str(sub_id)},
            "cart_amount": "500.00",
            "cart_currency": "USD",
        }
        with app.app_context():
            with patch("app.services.communication.notify"):
                PaymentService()._handle_successful_payment(payload, PaymentGateway.PAYTABS)
            db.session.commit()
            sub = db.session.get(Subscription, sub_id)
        assert sub.status == "pending_review"

    def test_fraud_check_still_runs_when_amount_matches_plan(self, app):
        """فحص الاحتيال مستقل: المبلغ يطابق الخطة لكن متوسط المدرسة أدنى.

        قبل الربط بالمبلغ مرّ الاختبار القديم بمبلغ 10000 لخطة بـ 100، فانحرف
        إلى فحص عدم المطابقة وترك مسار الاحتيال بلا تغطية. هنا نثبت استقلالهما.
        """
        from app.extensions import db
        from app.models.billing import Subscription
        from app.services.payments import PaymentService
        from tests.conftest import make_user

        make_user(app, role="school_admin")
        sub_id = self._subscription(app, price="500.00")
        payload = {
            "metadata": {"subscription_id": str(sub_id)},
            "cart_amount": "500.00",
            "cart_currency": "ILS",
        }
        with app.app_context():
            with patch("app.services.communication.notify") as notify:
                with patch.object(PaymentService, "_is_suspicious_amount", return_value=True):
                    PaymentService()._handle_successful_payment(payload, PaymentGateway.PAYTABS)
            db.session.commit()
            sub = db.session.get(Subscription, sub_id)

        assert sub.status == "pending_review"
        assert sub.start_at is None
        assert notify.called

    def test_matching_amount_activates(self, app):
        from app.extensions import db
        from app.models.billing import Subscription
        from app.services.payments import PaymentService

        sub_id = self._subscription(app, price="500.00")
        payload = {
            "metadata": {"subscription_id": str(sub_id)},
            "cart_amount": "500.00",
            "cart_currency": "ils",
        }
        with app.app_context():
            with (
                patch("app.services.communication.notify"),
                patch("app.services.email.send_payment_approved_email"),
                patch("app.services.communication.audit"),
                patch.object(PaymentService, "_is_suspicious_amount", return_value=False),
                patch.object(PaymentService, "_create_ledger_entry"),
            ):
                PaymentService()._handle_successful_payment(payload, PaymentGateway.PAYTABS)
            db.session.commit()
            sub = db.session.get(Subscription, sub_id)
        assert sub.status == "active"
        assert sub.start_at is not None


# ═══════════════════ service.process_webhook — منع التفعيل المزدوج ═══════════════════
class TestProcessWebhookIdempotency:
    """العيب الأخطر: إعادة إرسال واحدة كانت تُفعّل الاشتراك مرتين."""

    def _service_with_paytabs(self):
        from app.services.payments import PayTabsGateway

        svc = PaymentService()
        return svc, PayTabsGateway({"profile_id": "p", "server_key": "s", "webhook_secret": SECRET})

    def test_replay_does_not_reactivate(self, app):
        """الحدث نفسه مرتين ⇒ معالجة واحدة فقط (لا تفعيل مزدوج)."""
        from app.extensions import db
        from app.services.payments import PaymentGateway

        payload = {"tran_ref": "T300", "cart_amount": "1"}
        body = json.dumps(payload).encode()
        headers = {"X-Paytabs-Signature": _sign(body)}

        svc, gw = self._service_with_paytabs()
        calls: list[int] = []

        def _fake_handle(self, *args, **kwargs):  # noqa: ARG001
            calls.append(1)

        with app.app_context():
            with patch("requests.get") as get:
                get.return_value = MagicMock(status_code=200, json=lambda: {"payment_result": {"response_code": "100"}})
                with patch.object(PaymentService, "_handle_successful_payment", _fake_handle):
                    svc.gateways[PaymentGateway.PAYTABS] = gw
                    first = svc.process_webhook(PaymentGateway.PAYTABS, payload, headers, raw_body=body)
                    second = svc.process_webhook(PaymentGateway.PAYTABS, payload, headers, raw_body=body)
            db.session.commit()

        assert first["success"] is True and first.get("duplicate") is None
        assert second["success"] is True and second["duplicate"] is True
        assert calls == [1], f"الحدث المكرر أعاد المعالجة: {len(calls)} مرات"

    def test_failed_gateway_query_applies_no_side_effects(self, app):
        """بوابة لم تعتمد الدفع ⇒ لا معالجة إطلاقاً."""
        from app.extensions import db
        from app.services.payments import PaymentGateway

        payload = {"tran_ref": "T301"}
        body = json.dumps(payload).encode()
        headers = {"X-Paytabs-Signature": _sign(body)}

        svc, gw = self._service_with_paytabs()
        calls: list[int] = []
        with app.app_context():
            with patch("requests.get") as get:
                get.return_value = MagicMock(status_code=200, json=lambda: {"payment_result": {"response_code": "0"}})
                with patch.object(PaymentService, "_handle_successful_payment", side_effect=lambda *a: calls.append(1)):
                    svc.gateways[PaymentGateway.PAYTABS] = gw
                    result = svc.process_webhook(PaymentGateway.PAYTABS, payload, headers, raw_body=body)
            db.session.rollback()
        assert result == {"success": False, "error": "Verification failed"}
        assert calls == [], "معالجة حدث لم تعتمده البوابة"

    def test_duplicate_flag_short_circuits_side_effects(self, app):
        """عند وجود الحدث مسبقاً ⇒ success بلا استدعاء المعالجة."""
        from app.core.db import tx
        from app.extensions import db
        from app.models.billing import ProcessedEvent
        from app.services.payments import PaymentGateway

        svc, gw = self._service_with_paytabs()
        calls: list[int] = []

        def _fake_handle(self, *args, **kwargs):  # noqa: ARG001
            calls.append(1)

        payload = {"tran_ref": "T400"}
        body = json.dumps(payload).encode()
        headers = {"X-Paytabs-Signature": _sign(body)}

        with app.app_context():

            def _seed():
                db.session.add(ProcessedEvent(event_id="paytabs_T400", gateway="paytabs", payload=payload))

            tx(_seed)
            with patch.object(PaymentService, "_handle_successful_payment", _fake_handle):
                svc.gateways[PaymentGateway.PAYTABS] = gw
                result = svc.process_webhook(PaymentGateway.PAYTABS, payload, headers, raw_body=body)
            db.session.rollback()

        assert result["success"] is True
        assert result["duplicate"] is True
        assert result["event_id"] == "paytabs_T400"
        assert calls == [], "الحدث المكرر أعاد تطبيق آثار جانبية"

    def test_unconfigured_gateway_rejected(self, app):
        from app.services.payments import PaymentGateway, PaymentService

        svc = PaymentService()
        svc.gateways = {}
        with app.app_context():
            result = svc.process_webhook(PaymentGateway.STRIPE, {}, {})
        assert result == {"success": False, "error": "Gateway not configured"}

    def test_verification_failure_returns_error(self, app):
        from app.services.payments import PaymentGateway

        svc, gw = self._service_with_paytabs()
        with app.app_context():
            svc.gateways[PaymentGateway.PAYTABS] = gw
            result = svc.process_webhook(PaymentGateway.PAYTABS, {"tran_ref": "T1"}, {"X-Paytabs-Signature": "bad"})
        assert result == {"success": False, "error": "Verification failed"}


# ═══════════════════════ ربط المبلغ بسعر الخطة ═══════════════════════
class TestAmountBinding:
    """fail-closed: لا تفعيل إلا بمبلغ/عملة الخطة."""

    def _mismatch(self, sub_price="500.00", sub_currency="ILS", amount="500.00", currency="ILS"):
        from app.services.payments import PaymentService

        sub = MagicMock()
        sub.price = None if sub_price is None else Decimal(sub_price)
        sub.currency = sub_currency
        return PaymentService._payment_mismatch(sub, Decimal(amount), currency)

    def test_exact_match(self):
        assert self._mismatch() is None

    def test_underpaid_is_rejected(self):
        assert self._mismatch(amount="1.00") == "underpaid"

    def test_overpaid_is_rejected(self):
        assert self._mismatch(amount="900.00") == "overpaid"

    def test_currency_mismatch_is_rejected(self):
        assert self._mismatch(currency="USD") == "currency_mismatch"

    def test_case_insensitive_currency_ok(self):
        assert self._mismatch(currency="ils") is None

    def test_missing_received_currency_is_tolerated(self):
        """غياب العملة من البوابة لا يُفسد دفعاً صحيحاً."""
        assert self._mismatch(currency=None) is None

    def test_unreadable_expected_price_is_rejected(self):
        assert self._mismatch(sub_price=None) == "unreadable_expected_price"

    def test_extract_currency_per_gateway(self):
        from app.services.payments import PaymentGateway, PaymentService

        svc = PaymentService()
        stripe_payload = {"data": {"object": {"currency": "usd"}}}
        assert svc._extract_currency(stripe_payload, PaymentGateway.STRIPE) == "usd"
        assert svc._extract_currency({"cart_currency": "ILS"}, PaymentGateway.PAYTABS) == "ILS"
        assert svc._extract_currency({"currency": "JOD"}, PaymentGateway.CASHU) == "JOD"
        assert svc._extract_currency({}, PaymentGateway.MANUAL) is None


@pytest.mark.parametrize("gateway_name", ["paytabs", "cashu"])
def test_signature_required_for_both_local_gateways(gateway_name):
    """كلا البوابتين المحليتين تفشل مغلقاً بلا توقيع — لا استثناء."""
    from app.services.payments import CashUGateway, PayTabsGateway

    gateway = (PayTabsGateway if gateway_name == "paytabs" else CashUGateway)({"webhook_secret": None})
    assert gateway.verify_webhook({"payload": {"a": 1}, "headers": {}}).verified is False
