"""Third batch branch coverage tests — targets payments.py (all gateways,
fraud detection, webhook verification), ai.py (RateLimiter, BudgetTracker,
mock grading, session management), core/permissions.py, and deeper
tutoring/message branches not in batch 1/2.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from tests.conftest import (
    make_class,
    make_class_member,
    make_grade,
    make_lesson,
    make_school,
    make_subject,
    make_user,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uid() -> str:
    return f"_{int(time.time()*1000000)}"


def _make_student(app, school_id=None):
    return make_user(app, role="student", school_id=school_id)


def _make_teacher(app, school_id):
    return make_user(app, role="teacher", school_id=school_id)


def _make_super_admin(app):
    return make_user(app, role="super_admin")


# ===========================================================================
# PAYMENTS — all gateway implementations, fraud detection, webhook verification
# ===========================================================================

class TestPaymentsGateways:
    """payments.py — all gateway implementations and PaymentService branches."""

    def test_payment_service_singleton(self, app):
        from app.services.payments import get_payment_service
        with app.app_context():
            svc1 = get_payment_service()
            svc2 = get_payment_service()
            assert svc1 is svc2

    def test_payment_intent_dataclass(self, app):
        from app.services.payments import PaymentIntent, PaymentGateway, PaymentStatus
        with app.app_context():
            pi = PaymentIntent(
                id="test_123",
                gateway=PaymentGateway.STRIPE,
                amount=Decimal("100.00"),
                currency="ILS",
                status=PaymentStatus.PENDING,
                user_id=1,
            )
            assert pi.id == "test_123"
            assert pi.amount == Decimal("100.00")
            assert pi.status == PaymentStatus.PENDING

    def test_payment_intent_default_expiry(self, app):
        from app.services.payments import PaymentIntent, PaymentGateway, PaymentStatus
        with app.app_context():
            pi = PaymentIntent(
                id="test", gateway=PaymentGateway.STRIPE,
                amount=Decimal("50"), currency="ILS",
                status=PaymentStatus.PENDING, user_id=1,
            )
            assert pi.expires_at > datetime.utcnow()

    def test_stripe_gateway_init_no_stripe(self, app):
        from app.services.payments import StripeGateway
        with app.app_context():
            gw = StripeGateway({})
            assert gw.stripe is None

    def test_stripe_gateway_create_no_stripe(self, app):
        from app.services.payments import StripeGateway, PaymentStatus
        with app.app_context():
            gw = StripeGateway({})
            with pytest.raises(RuntimeError, match="Stripe not configured"):
                gw.create_payment_intent(Decimal("100"), "ILS", 1)

    def test_stripe_refund_no_stripe(self, app):
        from app.services.payments import StripeGateway, PaymentIntent, PaymentGateway, PaymentStatus
        with app.app_context():
            gw = StripeGateway({})
            pi = PaymentIntent(id="stripe_test", gateway=PaymentGateway.STRIPE,
                               amount=Decimal("100"), currency="ILS",
                               status=PaymentStatus.PENDING, user_id=1)
            assert gw.refund(pi) is False

    def test_stripe_refund_no_response(self, app):
        from app.services.payments import StripeGateway, PaymentIntent, PaymentGateway, PaymentStatus
        with app.app_context():
            gw = StripeGateway({})
            pi = PaymentIntent(id="stripe_test", gateway=PaymentGateway.STRIPE,
                               amount=Decimal("100"), currency="ILS",
                               status=PaymentStatus.PENDING, user_id=1,
                               gateway_response=None)
            assert gw.refund(pi) is False

    def test_paytabs_verify_no_secret(self, app):
        from app.services.payments import PayTabsGateway, PaymentIntent, PaymentGateway, PaymentStatus
        with app.app_context():
            gw = PayTabsGateway({})
            pi = PaymentIntent(id="pt_test", gateway=PaymentGateway.PAYTABS,
                               amount=Decimal("100"), currency="ILS",
                               status=PaymentStatus.PENDING, user_id=1)
            assert gw.verify_payment(pi, {"payload": {}, "headers": {}}) is False

    def test_paytabs_refund_returns_false(self, app):
        from app.services.payments import PayTabsGateway, PaymentIntent, PaymentGateway, PaymentStatus
        with app.app_context():
            gw = PayTabsGateway({})
            pi = PaymentIntent(id="pt_test", gateway=PaymentGateway.PAYTABS,
                               amount=Decimal("100"), currency="ILS",
                               status=PaymentStatus.PENDING, user_id=1)
            assert gw.refund(pi) is False

    def test_cashu_verify_no_secret(self, app):
        from app.services.payments import CashUGateway, PaymentIntent, PaymentGateway, PaymentStatus
        with app.app_context():
            gw = CashUGateway({})
            pi = PaymentIntent(id="cashu_test", gateway=PaymentGateway.CASHU,
                               amount=Decimal("100"), currency="ILS",
                               status=PaymentStatus.PENDING, user_id=1)
            assert gw.verify_payment(pi, {"payload": {}, "headers": {}}) is False

    def test_cashu_refund_returns_false(self, app):
        from app.services.payments import CashUGateway, PaymentIntent, PaymentGateway, PaymentStatus
        with app.app_context():
            gw = CashUGateway({})
            pi = PaymentIntent(id="cashu_test", gateway=PaymentGateway.CASHU,
                               amount=Decimal("100"), currency="ILS",
                               status=PaymentStatus.PENDING, user_id=1)
            assert gw.refund(pi) is False

    def test_cashu_create_intent(self, app):
        from app.services.payments import CashUGateway, PaymentStatus
        with app.app_context():
            gw = CashUGateway({})
            pi = gw.create_payment_intent(Decimal("50"), "ILS", 42, {"key": "val"})
            assert pi.gateway.value == "cashu"
            assert pi.status == PaymentStatus.PENDING
            assert pi.user_id == 42

    def test_whatsapp_verify_admin_approved(self, app):
        from app.services.payments import WhatsAppPaymentGateway, PaymentIntent, PaymentGateway, PaymentStatus
        with app.app_context():
            gw = WhatsAppPaymentGateway({})
            pi = PaymentIntent(id="wa_test", gateway=PaymentGateway.WHATSAPP,
                               amount=Decimal("100"), currency="ILS",
                               status=PaymentStatus.PENDING, user_id=1)
            assert gw.verify_payment(pi, {"admin_approved": True}) is True
            assert gw.verify_payment(pi, {}) is False

    def test_whatsapp_build_message(self, app):
        from app.services.payments import WhatsAppPaymentGateway
        with app.app_context():
            gw = WhatsAppPaymentGateway({})
            msg = gw._build_payment_message(Decimal("100"), {"description": "Test", "currency": "ILS"})
            assert "100" in msg
            assert "Test" in msg

    def test_whatsapp_build_message_no_metadata(self, app):
        from app.services.payments import WhatsAppPaymentGateway
        with app.app_context():
            gw = WhatsAppPaymentGateway({})
            msg = gw._build_payment_message(Decimal("50"), None)
            assert "50" in msg

    def test_whatsapp_refund_returns_false(self, app):
        from app.services.payments import WhatsAppPaymentGateway, PaymentIntent, PaymentGateway, PaymentStatus
        with app.app_context():
            gw = WhatsAppPaymentGateway({})
            pi = PaymentIntent(id="wa_test", gateway=PaymentGateway.WHATSAPP,
                               amount=Decimal("100"), currency="ILS",
                               status=PaymentStatus.PENDING, user_id=1)
            assert gw.refund(pi) is False

    def test_manual_verify_admin_approved(self, app):
        from app.services.payments import ManualPaymentGateway, PaymentIntent, PaymentGateway, PaymentStatus
        with app.app_context():
            gw = ManualPaymentGateway({})
            pi = PaymentIntent(id="m_test", gateway=PaymentGateway.MANUAL,
                               amount=Decimal("100"), currency="ILS",
                               status=PaymentStatus.PENDING, user_id=1)
            assert gw.verify_payment(pi, {"admin_approved": True}) is True
            assert gw.verify_payment(pi, {}) is False

    def test_manual_refund_returns_false(self, app):
        from app.services.payments import ManualPaymentGateway, PaymentIntent, PaymentGateway, PaymentStatus
        with app.app_context():
            gw = ManualPaymentGateway({})
            pi = PaymentIntent(id="m_test", gateway=PaymentGateway.MANUAL,
                               amount=Decimal("100"), currency="ILS",
                               status=PaymentStatus.PENDING, user_id=1)
            assert gw.refund(pi) is False

    def test_get_gateway_config_all(self, app):
        from app.services.payments import PaymentService, PaymentGateway
        with app.app_context():
            svc = PaymentService()
            for gw_type in PaymentGateway:
                config = svc._get_gateway_config(gw_type)
                # Manual always has config
                if gw_type == PaymentGateway.MANUAL:
                    assert config is not None

    def test_extract_subscription_id_stripe(self, app):
        from app.services.payments import PaymentService, PaymentGateway
        with app.app_context():
            svc = PaymentService()
            payload = {"data": {"object": {"metadata": {"subscription_id": "42"}}}}
            assert svc._extract_subscription_id(payload, PaymentGateway.STRIPE) == 42

    def test_extract_subscription_id_paytabs(self, app):
        from app.services.payments import PaymentService, PaymentGateway
        with app.app_context():
            svc = PaymentService()
            payload = {"metadata": {"subscription_id": "55"}}
            assert svc._extract_subscription_id(payload, PaymentGateway.PAYTABS) == 55

    def test_extract_subscription_id_cashu(self, app):
        from app.services.payments import PaymentService, PaymentGateway
        with app.app_context():
            svc = PaymentService()
            payload = {"metadata": {"subscription_id": "77"}}
            assert svc._extract_subscription_id(payload, PaymentGateway.CASHU) == 77

    def test_extract_subscription_id_whatsapp_returns_none(self, app):
        from app.services.payments import PaymentService, PaymentGateway
        with app.app_context():
            svc = PaymentService()
            assert svc._extract_subscription_id({}, PaymentGateway.WHATSAPP) is None

    def test_extract_subscription_id_manual_returns_none(self, app):
        from app.services.payments import PaymentService, PaymentGateway
        with app.app_context():
            svc = PaymentService()
            assert svc._extract_subscription_id({}, PaymentGateway.MANUAL) is None

    def test_extract_subscription_id_unknown_returns_none(self, app):
        from app.services.payments import PaymentService, PaymentGateway
        with app.app_context():
            svc = PaymentService()
            assert svc._extract_subscription_id({}, "unknown") is None

    def test_extract_amount_stripe(self, app):
        from app.services.payments import PaymentService, PaymentGateway
        with app.app_context():
            svc = PaymentService()
            payload = {"data": {"object": {"amount_received": 10000}}}
            assert svc._extract_amount(payload, PaymentGateway.STRIPE) == Decimal("100.00")

    def test_extract_amount_stripe_no_amount(self, app):
        from app.services.payments import PaymentService, PaymentGateway
        with app.app_context():
            svc = PaymentService()
            assert svc._extract_amount({}, PaymentGateway.STRIPE) is None

    def test_extract_amount_paytabs(self, app):
        from app.services.payments import PaymentService, PaymentGateway
        with app.app_context():
            svc = PaymentService()
            payload = {"cart_amount": 50.0}
            assert svc._extract_amount(payload, PaymentGateway.PAYTABS) == Decimal("50.0")

    def test_extract_amount_cashu(self, app):
        from app.services.payments import PaymentService, PaymentGateway
        with app.app_context():
            svc = PaymentService()
            payload = {"amount": 75.0}
            assert svc._extract_amount(payload, PaymentGateway.CASHU) == Decimal("75.0")

    def test_extract_amount_unknown(self, app):
        from app.services.payments import PaymentService, PaymentGateway
        with app.app_context():
            svc = PaymentService()
            assert svc._extract_amount({}, "unknown") is None

    def test_fraud_detection_no_data(self, app):
        from app.services.payments import PaymentService
        with app.app_context():
            svc = PaymentService()
            sid = make_school(app)
            assert svc._is_suspicious_amount(sid, Decimal("1000")) is False

    def test_cleanup_expired_intents(self, app):
        from app.services.payments import PaymentService
        with app.app_context():
            svc = PaymentService()
            assert svc.cleanup_expired_intents() == 0

    def test_stripe_verify_no_webhook_secret(self, app):
        from app.services.payments import StripeGateway, PaymentIntent, PaymentGateway, PaymentStatus
        with app.app_context():
            gw = StripeGateway({})
            pi = PaymentIntent(id="stripe_test", gateway=PaymentGateway.STRIPE,
                               amount=Decimal("100"), currency="ILS",
                               status=PaymentStatus.PENDING, user_id=1)
            assert gw.verify_payment(pi, {"payload": "", "headers": {}}) is False


# ===========================================================================
# AI SERVICE — RateLimiter, BudgetTracker, mock grading, sessions
# ===========================================================================

class TestAiServiceBranches:
    """ai.py — RateLimiter, BudgetTracker, AiService internals."""

    def test_rate_limiter_allows(self, app):
        from app.services.ai import RateLimiter
        with app.app_context():
            rl = RateLimiter(max_rpm=60, max_tpm=100000)
            ok, msg = rl.can_proceed(1000)
            assert ok is True

    def test_rate_limiter_rpm_exceeded(self, app):
        from app.services.ai import RateLimiter
        with app.app_context():
            rl = RateLimiter(max_rpm=2, max_tpm=100000)
            rl.record_request(100)
            rl.record_request(100)
            ok, msg = rl.can_proceed(1000)
            assert ok is False
            assert "Rate limit" in msg

    def test_rate_limiter_tpm_exceeded(self, app):
        from app.services.ai import RateLimiter
        with app.app_context():
            rl = RateLimiter(max_rpm=100, max_tpm=200)
            rl.record_request(150)
            ok, msg = rl.can_proceed(100)
            assert ok is False
            assert "Token limit" in msg

    def test_rate_limiter_cleans_old(self, app):
        from app.services.ai import RateLimiter
        import time
        with app.app_context():
            rl = RateLimiter(max_rpm=1, max_tpm=100000)
            rl.record_request(100)
            # Simulate old request by manipulating deque
            rl.request_times[0] = time.time() - 120
            rl.token_usage[0] = (time.time() - 120, 100)
            ok, msg = rl.can_proceed(1000)
            assert ok is True

    def test_budget_tracker_allows(self, app):
        from app.services.ai import BudgetTracker
        with app.app_context():
            bt = BudgetTracker(monthly_budget_usd=100.0)
            ok, msg = bt.can_spend(10.0)
            assert ok is True

    def test_budget_tracker_exceeded(self, app):
        from app.services.ai import BudgetTracker
        with app.app_context():
            bt = BudgetTracker(monthly_budget_usd=10.0)
            ok, msg = bt.can_spend(15.0)
            assert ok is False
            assert "budget" in msg.lower()

    def test_budget_tracker_records(self, app):
        from app.services.ai import BudgetTracker
        with app.app_context():
            bt = BudgetTracker(monthly_budget_usd=100.0)
            bt.record_spending(50.0)
            usage = bt.get_usage()
            assert usage["spent_usd"] == 50.0
            assert usage["remaining_usd"] == 50.0

    def test_budget_tracker_monthly_reset(self, app):
        from app.services.ai import BudgetTracker
        with app.app_context():
            bt = BudgetTracker(monthly_budget_usd=100.0)
            bt.record_spending(80.0)
            bt._last_reset = datetime(2020, 1, 1)
            bt._ensure_current_month()
            assert bt._monthly_spent == 0.0

    def test_budget_tracker_usage_percent_zero_budget(self, app):
        from app.services.ai import BudgetTracker
        with app.app_context():
            bt = BudgetTracker(monthly_budget_usd=0)
            usage = bt.get_usage()
            assert usage["usage_percent"] == 0

    def test_ai_config_from_env(self, app):
        from app.services.ai import AiConfig
        with app.app_context():
            config = AiConfig()
            assert config.model  # has a default

    def test_estimate_cost(self, app):
        from app.services.ai import AiService
        with app.app_context():
            svc = AiService()
            cost = svc._estimate_cost(1000, 1000)
            assert cost > 0

    def test_estimate_cost_unknown_model(self, app):
        from app.services.ai import AiService
        with app.app_context():
            svc = AiService()
            svc.config.model = "unknown-model"
            cost = svc._estimate_cost(1000, 1000)
            assert cost > 0

    def test_check_limits_no_limiter(self, app):
        from app.services.ai import AiService, RateLimiter, BudgetTracker
        with app.app_context():
            AiService._rate_limiter = None
            AiService._budget_tracker = None
            svc = AiService()
            ok, msg = svc._check_limits()
            assert ok is True

    def test_check_limits_rate_limited(self, app):
        from app.services.ai import AiService, RateLimiter, BudgetTracker
        with app.app_context():
            AiService._rate_limiter = RateLimiter(max_rpm=1, max_tpm=100000)
            AiService._rate_limiter.record_request(100)
            AiService._rate_limiter.record_request(100)
            svc = AiService()
            ok, msg = svc._check_limits()
            assert ok is False
            AiService._rate_limiter = None

    def test_mock_grade_mcq(self, app):
        from app.services.ai import AiService
        with app.app_context():
            svc = AiService()
            result = svc._mock_grade("mcq", {"index": 0})
            assert "score" in result

    def test_mock_grade_true_false(self, app):
        from app.services.ai import AiService
        with app.app_context():
            svc = AiService()
            result = svc._mock_grade("true_false", {"value": True})
            assert "correct" in result

    def test_mock_grade_essay(self, app):
        from app.services.ai import AiService
        with app.app_context():
            svc = AiService()
            result = svc._mock_grade("essay", None)
            assert "score" in result
            assert "strengths" in result

    def test_mock_grade_unknown(self, app):
        from app.services.ai import AiService
        with app.app_context():
            svc = AiService()
            result = svc._mock_grade("matching", None)
            assert "score" in result

    def test_mock_generate_questions(self, app):
        from app.services.ai import AiService
        with app.app_context():
            svc = AiService()
            qs = svc._mock_generate_questions("Math", 3, ["mcq", "true_false", "essay"])
            assert len(qs) == 3
            assert qs[0]["type"] == "mcq"
            assert qs[1]["type"] == "true_false"
            assert qs[2]["type"] == "essay"

    def test_verify_permission_super_admin(self, app):
        from app.services.ai import AiService
        from app.models.user import User, UserRole
        with app.app_context():
            svc = AiService()
            uid = _make_super_admin(app)
            user = db.session.get(User, uid)
            assert svc._verify_permission(user) is True
            assert svc._verify_permission(user, UserRole.student) is True

    def test_verify_permission_correct_role(self, app):
        from app.services.ai import AiService
        from app.models.user import User, UserRole
        with app.app_context():
            svc = AiService()
            uid = _make_student(app)
            user = db.session.get(User, uid)
            assert svc._verify_permission(user, UserRole.student) is True

    def test_verify_permission_wrong_role(self, app):
        from app.services.ai import AiService
        from app.models.user import User, UserRole
        with app.app_context():
            svc = AiService()
            uid = _make_student(app)
            user = db.session.get(User, uid)
            assert svc._verify_permission(user, UserRole.teacher) is False

    def test_verify_permission_set_of_roles(self, app):
        from app.services.ai import AiService
        from app.models.user import User, UserRole
        with app.app_context():
            svc = AiService()
            uid = _make_student(app)
            user = db.session.get(User, uid)
            assert svc._verify_permission(user, {UserRole.student, UserRole.teacher}) is True

    def test_get_client_no_openai(self, app):
        from app.services.ai import AiService, OPENAI_AVAILABLE
        with app.app_context():
            if OPENAI_AVAILABLE:
                pytest.skip("openai is installed")
            svc = AiService()
            with pytest.raises(RuntimeError, match="not installed"):
                svc._get_client()

    def test_model_pricing_coverage(self, app):
        from app.services.ai import MODEL_PRICING
        with app.app_context():
            for model, prices in MODEL_PRICING.items():
                assert "input" in prices
                assert "output" in prices
                assert prices["input"] > 0
                assert prices["output"] > 0


# ===========================================================================
# PERMISSIONS — decorator import + callable check
# ===========================================================================

class TestPermissionsDecorators:
    """permissions.py — verify all decorators are callable."""

    def test_role_required_callable(self, app):
        from app.core.permissions import role_required
        from app.models.user import UserRole
        with app.app_context():
            deco = role_required(UserRole.student)
            assert callable(deco)

    def test_any_role_needs_auth(self, app):
        from app.core.permissions import any_role
        from app.models.user import UserRole
        # any_role calls _has_any which accesses current_user (None outside request)
        with app.app_context():
            with pytest.raises(AttributeError):
                any_role(UserRole.student)

    def test_class_access_required_callable(self, app):
        from app.core.permissions import class_access_required
        with app.app_context():
            assert callable(class_access_required)

    def test_class_teach_required_callable(self, app):
        from app.core.permissions import class_teach_required
        with app.app_context():
            assert callable(class_teach_required)

    def test_parent_of_required_callable(self, app):
        from app.core.permissions import parent_of_required
        with app.app_context():
            assert callable(parent_of_required)

    def test_student_only_callable(self, app):
        from app.core.permissions import student_only
        with app.app_context():
            assert callable(student_only)


# Need db and User for some tests
from app.extensions import db
from app.models.user import User
