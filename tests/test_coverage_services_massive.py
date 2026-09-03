"""Massive service coverage tests — covers ALL remaining uncovered service + core modules."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest


# ═══════ GAMIFICATION ═══════

class TestGamificationService:
    def test_get_active_badges_empty(self, app):
        from app.services.gamification import get_active_badges
        with app.app_context():
            assert isinstance(get_active_badges(), list)

    def test_get_student_badges_empty(self, app):
        from app.services.gamification import get_student_badges
        with app.app_context():
            assert isinstance(get_student_badges(99999), list)

    def test_has_badge_false(self, app):
        from app.services.gamification import has_badge
        with app.app_context():
            assert has_badge(99999, 99999) is False

    def test_check_and_award_unknown_event(self, app):
        from app.services.gamification import check_and_award_badges
        with app.app_context():
            result = check_and_award_badges(99999, "unknown_event_type")
            assert isinstance(result, list) and len(result) == 0

    def test_check_and_award_first_quiz(self, app):
        from app.services.gamification import check_and_award_badges
        with app.app_context():
            assert isinstance(check_and_award_badges(99999, "quiz_submitted"), list)

    def test_check_and_award_perfect_score(self, app):
        from app.services.gamification import check_and_award_badges
        with app.app_context():
            assert isinstance(check_and_award_badges(99999, "quiz_completed", {"score": 100}), list)


# ═══════ ASSESSMENT ═══════

class TestAssessmentService:
    def test_list_quizzes_empty(self, app):
        from app.services.assessment import list_quizzes
        with app.app_context():
            assert isinstance(list_quizzes(class_id=99999), list)

    def test_get_attempt_none(self, app):
        from app.services.assessment import get_attempt
        with app.app_context():
            assert get_attempt(99999) is None


# ═══════ PROGRESS ═══════

class TestProgressService:
    def test_student_class_progress_empty(self, app):
        from app.services.progress import student_class_progress
        with app.app_context():
            assert isinstance(student_class_progress(99999, 99999), list)

    def test_class_progress_overview_empty(self, app):
        from app.services.progress import class_progress_overview
        with app.app_context():
            assert isinstance(class_progress_overview(99999), list)

    def test_last_active_days(self, app):
        from app.services.progress import last_active_days
        with app.app_context():
            assert isinstance(last_active_days(99999), list)


# ═══════ VIDEO SERVICE ═══════

class TestVideoService:
    def test_generate_and_verify_token(self, app):
        from app.services.video_service import generate_stream_token, verify_stream_token
        with app.app_context():
            token = generate_stream_token(1, 10, 100)
            valid, _ = verify_stream_token(token, 1, 10, 100)
            assert valid is True

    def test_verify_wrong_user(self, app):
        from app.services.video_service import generate_stream_token, verify_stream_token
        with app.app_context():
            token = generate_stream_token(1, 10, 100)
            valid, _ = verify_stream_token(token, 2, 10, 100)
            assert valid is False

    def test_verify_expired(self, app):
        from app.services.video_service import generate_stream_token, verify_stream_token
        with app.app_context():
            token = generate_stream_token(1, 10, 100, expires_in=-1)
            valid, _ = verify_stream_token(token, 1, 10, 100)
            assert valid is False

    def test_verify_tampered(self, app):
        from app.services.video_service import generate_stream_token, verify_stream_token
        import base64
        with app.app_context():
            token = generate_stream_token(1, 10, 100)
            raw = base64.urlsafe_b64decode(token + "==")
            parts = raw.split(b":")
            if len(parts) == 5:
                parts[1] = b"999"
                tampered = base64.urlsafe_b64encode(b":".join(parts)).decode().rstrip("=")
                valid, _ = verify_stream_token(tampered, 1, 10, 100)
                assert valid is False

    def test_verify_empty_token(self, app):
        from app.services.video_service import verify_stream_token
        with app.app_context():
            valid, _ = verify_stream_token("", 1, 10, 100)
            assert valid is False

    def test_verify_garbage(self, app):
        from app.services.video_service import verify_stream_token
        with app.app_context():
            valid, _ = verify_stream_token("GARBAGE", 1, 10, 100)
            assert valid is False

    def test_verify_wrong_school(self, app):
        from app.services.video_service import generate_stream_token, verify_stream_token
        with app.app_context():
            token = generate_stream_token(1, 10, 100)
            valid, _ = verify_stream_token(token, 1, 99, 100)
            assert valid is False

    def test_verify_wrong_lesson(self, app):
        from app.services.video_service import generate_stream_token, verify_stream_token
        with app.app_context():
            token = generate_stream_token(1, 10, 100)
            valid, _ = verify_stream_token(token, 1, 10, 999)
            assert valid is False

    def test_get_protected_media_path(self, app):
        from app.services.video_service import get_protected_media_path
        with app.app_context():
            path = get_protected_media_path(1, 10)
            assert "1" in path and "10" in path

    def test_validate_lesson_access_nonexistent(self, app):
        from app.services.video_service import validate_lesson_access
        with app.app_context():
            allowed, _ = validate_lesson_access(99999, 99999, 99999)
            assert allowed is False


# ═══════ TUTORING ═══════

class TestTutoringService:
    def test_search_tutors_empty(self, app):
        from app.services.tutoring import search_tutors
        with app.app_context():
            assert isinstance(search_tutors(q="nonexistent"), list)

    def test_find_by_invite_code_none(self, app):
        from app.services.tutoring import find_by_invite_code
        with app.app_context():
            assert find_by_invite_code("INVALID") is None

    def test_get_profile_none(self, app):
        from app.services.tutoring import get_profile
        with app.app_context():
            assert get_profile(99999) is None

    def test_list_requests_tutor_empty(self, app):
        from app.services.tutoring import list_requests_for_tutor
        with app.app_context():
            assert isinstance(list_requests_for_tutor(99999), list)

    def test_list_requests_student_empty(self, app):
        from app.services.tutoring import list_requests_for_student
        with app.app_context():
            assert isinstance(list_requests_for_student(99999), list)

    def test_list_sessions_empty(self, app):
        from app.services.tutoring import list_sessions_for
        with app.app_context():
            assert isinstance(list_sessions_for(99999, as_tutor=False), list)

    def test_get_tutor_earnings(self, app):
        from app.services.tutoring import get_tutor_earnings
        with app.app_context():
            result = get_tutor_earnings(99999)
            assert isinstance(result, dict)


# ═══════ WALLET ═══════

class TestWalletService:
    def test_money(self):
        from app.services.wallet_service import _money
        assert _money(10) == Decimal("10.00")
        assert _money("5.50") == Decimal("5.50")
        assert _money(7.99) == Decimal("7.99")

    def test_get_balance_nonexistent(self, app):
        from app.services.wallet_service import get_balance
        with app.app_context():
            assert get_balance(99999, 99999) == Decimal("0.00")

    def test_get_wallet_summary(self, app):
        from app.services.wallet_service import get_wallet_summary
        with app.app_context():
            assert isinstance(get_wallet_summary(99999, 99999), dict)


# ═══════ BILLING ═══════

class TestBillingService:
    def test_money(self):
        from app.services.billing import money
        assert money(10) == Decimal("10.00")
        assert money("5.50") == Decimal("5.50")

    def test_list_plans_empty(self, app):
        from app.services.billing import list_plans
        with app.app_context():
            assert isinstance(list_plans(), list)

    def test_get_plan_none(self, app):
        from app.services.billing import get_plan
        with app.app_context():
            assert get_plan(99999) is None

    def test_has_active_subscription_false(self, app):
        from app.services.billing import has_active_subscription
        with app.app_context():
            assert has_active_subscription(99999, 99999) is False

    def test_pending_payments_empty(self, app):
        from app.services.billing import pending_payments
        with app.app_context():
            assert isinstance(pending_payments(), list)

    def test_list_subscriptions_empty(self, app):
        from app.services.billing import list_subscriptions
        with app.app_context():
            assert isinstance(list_subscriptions(), list)

    def test_expire_subscriptions(self, app):
        from app.services.billing import expire_subscriptions
        with app.app_context():
            assert isinstance(expire_subscriptions(), int)


# ═══════ SCHOOL APPROVALS ═══════

class TestSchoolApprovalsService:
    def test_get_pending_empty(self, app):
        from app.services.school_approvals import get_pending_approvals_for_school
        with app.app_context():
            assert isinstance(get_pending_approvals_for_school(99999), list)

    def test_get_pending_super_admin(self, app):
        from app.services.school_approvals import get_pending_approvals_for_super_admin
        with app.app_context():
            assert isinstance(get_pending_approvals_for_super_admin(), list)

    def test_get_school_admins_empty(self, app):
        from app.services.school_approvals import get_school_admins
        with app.app_context():
            assert isinstance(get_school_admins(99999), list)

    def test_approve_nonexistent(self, app):
        from app.services.school_approvals import approve_user_role_link
        with app.app_context():
            ok, _ = approve_user_role_link(99999, 99999)
            assert ok is False

    def test_reject_nonexistent(self, app):
        from app.services.school_approvals import reject_user_role_link
        with app.app_context():
            ok, _ = reject_user_role_link(99999, 99999)
            assert ok is False

    def test_get_approval_queue(self, app):
        from app.services.school_approvals import get_approval_queue_for_user
        with app.app_context():
            assert isinstance(get_approval_queue_for_user(99999), list)


# ═══════ CORE: DB ═══════

class TestCoreDB:
    def test_tx_success(self, app):
        from app.core.db import tx
        with app.app_context():
            assert tx(lambda: 42) == 42

    def test_tx_error(self, app):
        from app.core.db import TxError, tx
        with app.app_context():
            with pytest.raises(TxError):
                tx(lambda: (_ for _ in ()).throw(TxError("fail")))

    def test_tx_on_commit_no_crash(self, app):
        from app.core.db import tx_on_commit
        with app.app_context():
            tx_on_commit(lambda: None)  # Should not crash


# ═══════ CORE: CONTEXT ═══════

class TestCoreContext:
    def test_has_role_unauthenticated(self, app):
        from app.core.context import has_role
        with app.app_context():
            with patch("app.core.context.current_user") as m:
                m.is_authenticated = False
                assert has_role("student") is False

    def test_has_any_role_unauthenticated(self, app):
        from app.core.context import has_any_role
        with app.app_context():
            with patch("app.core.context.current_user") as m:
                m.is_authenticated = False
                assert has_any_role("student", "teacher") is False

    def test_role_checks(self, app):
        from app.core.context import (
            is_super_admin, is_school_admin, is_teacher,
            is_student, is_parent, can_access_admin, can_manage_schools,
        )
        with app.app_context():
            with patch("app.core.context.current_user") as m:
                m.is_authenticated = True
                m.role = "student"
                assert is_super_admin() is False
                assert is_school_admin() is False
                assert is_teacher() is False
                assert is_student() is True
                assert is_parent() is False
                assert can_access_admin() is False
                assert can_manage_schools() is False


# ═══════ PERMISSIONS ═══════

class TestPermissions:
    def test_role_required_callable(self):
        from app.core.permissions import role_required
        assert callable(role_required("student"))


# ═══════ EMAIL — more coverage ═══════

class TestEmailMore:
    def test_recipient_locale(self, app):
        from app.services.email import _recipient_locale
        m = MagicMock()
        m.locale = "en"
        assert _recipient_locale(m) == "en"

    def test_dir(self, app):
        from app.services.email import _dir
        assert _dir("ar") == "rtl"
        assert _dir("en") == "ltr"


# ═══════ AI SERVICE — more coverage ═══════

class TestAIServiceMore:
    def test_rate_limiter(self):
        from app.services.ai import RateLimiter
        rl = RateLimiter(max_rpm=5, max_tpm=1000)
        can, _ = rl.can_proceed(100)
        assert can is True
        rl.record_request(100)
        rl._clean_old()
        assert len(rl.request_times) == 1

    def test_budget_tracker(self):
        from app.services.ai import BudgetTracker
        bt = BudgetTracker(10.0)
        bt.record_spending(5.0)
        usage = bt.get_usage()
        assert usage["spent_usd"] == 5.0
        assert usage["remaining_usd"] == 5.0

    def test_ai_config(self):
        from app.services.ai import AiConfig
        c = AiConfig(api_key="k", model="m", max_tokens=8000, temperature=0.5)
        assert c.api_key == "k"


# ═══════ RAG — more ═══════

class TestRAGMore:
    def test_tokenize_arabic(self):
        from app.services.rag_service import _tokenize
        tokens = _tokenize("العلوم! الطبيعية، والرياضيات.")
        assert len(tokens) >= 2

    def test_chunk_long(self):
        from app.services.rag_service import _chunk_text
        text = "word " * 200
        chunks = _chunk_text(text, chunk_size=100, overlap=20)
        assert len(chunks) > 1

    def test_cosine_partial(self):
        from app.services.rag_service import _cosine_similarity
        sim = _cosine_similarity({"x": 1.0, "y": 0.5}, {"x": 0.8})
        assert sim > 0


# ═══════ QUIZ AI — more ═══════

class TestQuizAIMore:
    def test_parse_code_fences(self):
        from app.services.quiz_ai_service import _parse_llm_response
        raw = '```json\n[{"question_text": "Q", "correct_answer": "A"}]\n```'
        result = _parse_llm_response(raw)
        assert result is not None

    def test_parse_empty_list(self):
        from app.services.quiz_ai_service import _parse_llm_response
        assert _parse_llm_response("[]") is None

    def test_difficulty_map(self):
        from app.services.quiz_ai_service import _map_difficulty
        assert _map_difficulty("easy") == 1
        assert _map_difficulty("hard") == 3
        assert _map_difficulty("") == 2


# ═══════ RLS ═══════

class TestRLSMore:
    def test_tables_exist(self):
        from app.core.rls import _INDIRECT_TENANT_TABLES, _TENANT_TABLES
        assert len(_TENANT_TABLES) >= 10
        assert len(_INDIRECT_TENANT_TABLES) >= 3


# ═══════ SENTRY ═══════

class TestSentryMore:
    def test_init_no_dsn(self, app):
        from app.core.sentry import init_sentry
        with app.app_context():
            init_sentry(app)

    def test_set_user_none(self):
        from app.core.sentry import set_sentry_user
        set_sentry_user(None)

    def test_capture(self):
        from app.core.sentry import capture_exception, capture_message
        capture_exception(ValueError("test"))
        capture_message("test")
