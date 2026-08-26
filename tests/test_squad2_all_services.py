"""SQUAD 2 MEGA: Tests for AI, analytics, gamification, progress, offline,
quiz_stats, question_bank, tenant, individual, invoice services."""

import math
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import UTC, datetime, timedelta
from app.extensions import db
from app.models.user import User, UserRole, UserApprovalStatus
from app.models.school import School
from app.models.gamification import Badge, BadgeCriteriaType, StudentBadge
from app.models.progress import StudentProgress, VideoProgress
from app.models.offline import OfflineDownload
from app.models.tenant import TenantQuota
from app.models.class_room import ClassRoom, ClassMember

# ── AI Service ──
from app.services.ai import (
    AiConfig, AiService, RateLimiter, BudgetTracker,
    MODEL_PRICING, get_ai_service,
)


class TestRateLimiter:
    def test_init(self):
        rl = RateLimiter(max_rpm=10, max_tpm=5000)
        assert rl.max_rpm == 10

    def test_can_proceed(self):
        rl = RateLimiter(max_rpm=10, max_tpm=5000)
        ok, msg = rl.can_proceed(100)
        assert ok is True

    def test_exceed_rpm(self):
        rl = RateLimiter(max_rpm=2, max_tpm=5000)
        rl.record_request(100)
        rl.record_request(100)
        ok, msg = rl.can_proceed(100)
        assert ok is False

    def test_exceed_tpm(self):
        rl = RateLimiter(max_rpm=100, max_tpm=200)
        rl.record_request(100)
        rl.record_request(100)
        ok, msg = rl.can_proceed(100)
        assert ok is False

    def test_clean_old(self):
        rl = RateLimiter(max_rpm=10, max_tpm=5000)
        rl.request_times.append(datetime.utcnow().timestamp() - 120)
        rl.token_usage.append((datetime.utcnow().timestamp() - 120, 100))
        rl._clean_old()
        assert len(rl.request_times) == 0

    def test_record_request(self):
        rl = RateLimiter(max_rpm=10, max_tpm=5000)
        rl.record_request(500)
        assert len(rl.request_times) == 1


class TestBudgetTracker:
    def test_init(self):
        bt = BudgetTracker(100.0)
        assert bt.monthly_budget == 100.0

    def test_can_spend(self):
        bt = BudgetTracker(100.0)
        ok, msg = bt.can_spend(10.0)
        assert ok is True

    def test_exceed_budget(self):
        bt = BudgetTracker(5.0)
        ok, msg = bt.can_spend(10.0)
        assert ok is False

    def test_record_spending(self):
        bt = BudgetTracker(100.0)
        bt.record_spending(30.0)
        assert bt._monthly_spent == 30.0

    def test_get_usage(self):
        bt = BudgetTracker(100.0)
        bt.record_spending(25.0)
        usage = bt.get_usage()
        assert usage["spent_usd"] == 25.0
        assert usage["remaining_usd"] == 75.0


class TestAiService:
    def test_config(self):
        cfg = AiConfig()
        assert cfg.model in ("gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo")

    def test_estimate_cost(self):
        svc = AiService()
        cost = svc._estimate_cost(1000, 500)
        assert cost > 0

    def test_mock_grade_mcq(self):
        svc = AiService()
        result = svc._mock_grade("mcq", None)
        assert "score" in result

    def test_mock_grade_tf(self):
        svc = AiService()
        result = svc._mock_grade("true_false", True)
        assert "correct" in result

    def test_mock_grade_essay(self):
        svc = AiService()
        result = svc._mock_grade("essay", None)
        assert "strengths" in result

    def test_mock_grade_default(self):
        svc = AiService()
        result = svc._mock_grade("other", None)
        assert "score" in result

    def test_mock_generate_questions(self):
        svc = AiService()
        qs = svc._mock_generate_questions("Math", 3, ["mcq", "true_false", "essay"])
        assert len(qs) == 3

    def test_mock_ai_answer_math(self):
        svc = AiService()
        answer = svc._mock_ai_answer("solve this equation")
        assert isinstance(answer, str)

    def test_mock_ai_answer_question(self):
        svc = AiService()
        answer = svc._mock_ai_answer("what is a test question")
        assert isinstance(answer, str)

    def test_mock_ai_answer_grade(self):
        svc = AiService()
        answer = svc._mock_ai_answer("what is my grade score")
        assert isinstance(answer, str)

    def test_mock_ai_answer_homework(self):
        svc = AiService()
        answer = svc._mock_ai_answer("help with homework assignment")
        assert isinstance(answer, str)

    def test_mock_ai_answer_empty(self):
        svc = AiService()
        answer = svc._mock_ai_answer("")
        assert isinstance(answer, str)

    def test_mock_ai_answer_general(self):
        svc = AiService()
        answer = svc._mock_ai_answer("something random about chemistry")
        assert isinstance(answer, str)

    def test_model_pricing(self):
        assert "gpt-4o" in MODEL_PRICING
        assert "input" in MODEL_PRICING["gpt-4o"]

    def test_get_ai_service_singleton(self):
        svc1 = get_ai_service()
        svc2 = get_ai_service()
        assert svc1 is svc2

    def test_verify_permission(self):
        svc = AiService()
        u = User(name_ar="T", email="t@t.com", role=UserRole.teacher, password_hash="x")
        assert svc._verify_permission(u, UserRole.teacher) is True
        assert svc._verify_permission(u, UserRole.student) is False

    def test_verify_permission_super_admin(self):
        svc = AiService()
        u = User(name_ar="A", email="a@a.com", role=UserRole.super_admin, password_hash="x")
        assert svc._verify_permission(u, UserRole.student) is True

    def test_verify_permission_no_role(self):
        svc = AiService()
        u = User(name_ar="T", email="t@t.com", role=UserRole.teacher, password_hash="x")
        assert svc._verify_permission(u, None) is True

    def test_mock_stream_chunks(self):
        svc = AiService()
        chunks = svc._mock_stream_chunks("Hello world this is a test")
        assert len(chunks) > 0

    def test_usage_stats(self):
        svc = AiService()
        stats = svc.get_usage_stats()
        assert "total_requests" in stats


# ── Analytics ──
class TestAnalytics:
    def test_get_analytics_data(self, app):
        with app.app_context():
            from app.services.analytics import get_analytics_data
            data = get_analytics_data()
            assert "dau" in data
            assert "role_distribution" in data
            assert "total_lessons" in data


# ── Gamification ──
class TestGamification:
    def test_get_active_badges(self, app):
        with app.app_context():
            from app.services.gamification import get_active_badges
            badges = get_active_badges()
            assert isinstance(badges, list)

    def test_award_badge(self, app):
        with app.app_context():
            from app.services.gamification import award_badge
            badge = Badge(name="Test Badge", description="desc", icon="star", criteria_type=BadgeCriteriaType.first_quiz, is_active=True)
            db.session.add(badge)
            db.session.flush()
            sb = award_badge(1, badge.id)
            assert sb is not None

    def test_award_badge_duplicate(self, app):
        with app.app_context():
            from app.services.gamification import award_badge
            badge = Badge(name="Dup Badge", description="desc", icon="star", criteria_type=BadgeCriteriaType.first_quiz, is_active=True)
            db.session.add(badge)
            db.session.flush()
            award_badge(1, badge.id)
            sb2 = award_badge(1, badge.id)
            assert sb2 is None

    def test_has_badge(self, app):
        with app.app_context():
            from app.services.gamification import has_badge, award_badge
            badge = Badge(name="Check Badge", description="d", icon="t", criteria_type=BadgeCriteriaType.first_quiz, is_active=True)
            db.session.add(badge)
            db.session.flush()
            assert has_badge(1, badge.id) is False
            award_badge(1, badge.id)
            assert has_badge(1, badge.id) is True

    def test_check_and_award_badges_no_match(self, app):
        with app.app_context():
            from app.services.gamification import check_and_award_badges
            new = check_and_award_badges(1, "random_event")
            assert new == []


# ── Progress ──
class TestProgress:
    def test_record_lesson_view(self, app):
        with app.app_context():
            from app.services.progress import record_lesson_view
            p = record_lesson_view(1, 1, 1)
            assert p.status == "in_progress"

    def test_record_lesson_view_existing(self, app):
        with app.app_context():
            from app.services.progress import record_lesson_view
            p1 = record_lesson_view(1, 1, 1)
            p2 = record_lesson_view(1, 1, 1)
            assert p1.id == p2.id

    def test_update_time_spent_no_progress(self, app):
        with app.app_context():
            from app.services.progress import update_time_spent
            result = update_time_spent(999, 999, 60)
            assert result is None

    def test_last_active_days(self, app):
        with app.app_context():
            from app.services.progress import last_active_days
            days = last_active_days(1)
            assert isinstance(days, list)


# ── Offline ──
class TestOffline:
    def test_mark_for_download(self, app):
        with app.app_context():
            from app.services.offline import mark_for_download
            od = mark_for_download(1, 1, 1)
            assert od is not None
            assert od.status == "ready"

    def test_mark_for_download_duplicate(self, app):
        with app.app_context():
            from app.services.offline import mark_for_download
            mark_for_download(1, 1, 1)
            od2 = mark_for_download(1, 1, 1)
            assert od2 is None

    def test_get_offline_items(self, app):
        with app.app_context():
            from app.services.offline import mark_for_download, get_offline_items
            mark_for_download(1, 1, 1)
            items = get_offline_items(1)
            assert len(items) == 1

    def test_expire_old_downloads(self, app):
        with app.app_context():
            from app.services.offline import expire_old_downloads
            count = expire_old_downloads()
            assert count >= 0


# ── Quiz Stats ──
class TestQuizStats:
    def test_get_quiz_stats_nonexistent(self, app):
        with app.app_context():
            from app.services.quiz_stats import get_quiz_stats
            result = get_quiz_stats(99999)
            assert result is None


# ── Question Bank ──
class TestQuestionBank:
    def test_create_bank_question(self, app):
        with app.app_context():
            from app.services.question_bank import create_bank_question
            sid = make_school(app)
            tid = make_user(app, "teacher", school_id=sid)
            q, err = create_bank_question(tid, sid, "What is 2+2?", "mcq")
            assert err is None
            assert q is not None

    def test_create_empty_text(self, app):
        with app.app_context():
            from app.services.question_bank import create_bank_question
            q, err = create_bank_question(1, 1, "", "mcq")
            assert q is None

    def test_create_invalid_type(self, app):
        with app.app_context():
            from app.services.question_bank import create_bank_question
            q, err = create_bank_question(1, 1, "Q?", "invalid")
            assert q is None

    def test_create_invalid_difficulty(self, app):
        with app.app_context():
            from app.services.question_bank import create_bank_question
            q, err = create_bank_question(1, 1, "Q?", "mcq", difficulty=10)
            assert q is None

    def test_list_bank_questions(self, app):
        with app.app_context():
            from app.services.question_bank import create_bank_question, list_bank_questions
            sid = make_school(app)
            tid = make_user(app, "teacher", school_id=sid)
            create_bank_question(tid, sid, "Q1?", "mcq")
            create_bank_question(tid, sid, "Q2?", "essay")
            result = list_bank_questions(tid)
            assert len(result) == 2

    def test_list_filtered(self, app):
        with app.app_context():
            from app.services.question_bank import create_bank_question, list_bank_questions
            sid = make_school(app)
            tid = make_user(app, "teacher", school_id=sid)
            create_bank_question(tid, sid, "Q1?", "mcq", difficulty=3)
            create_bank_question(tid, sid, "Q2?", "essay", difficulty=5)
            result = list_bank_questions(tid, question_type="mcq")
            assert len(result) == 1


# ── Tenant Quotas ──
class TestTenantQuotas:
    def test_get_quota_creates_default(self, app):
        with app.app_context():
            from app.services.tenant import get_quota
            sid = make_school(app)
            q = get_quota(sid)
            assert q.tier == "free"
            assert q.max_students == 50

    def test_check_quota_classes(self, app):
        with app.app_context():
            from app.services.tenant import check_quota
            sid = make_school(app)
            ok, msg = check_quota(sid, "classes")
            assert ok is True

    def test_check_quota_ai_disabled(self, app):
        with app.app_context():
            from app.services.tenant import check_quota
            sid = make_school(app)
            ok, msg = check_quota(sid, "ai")
            assert ok is False

    def test_set_tier(self, app):
        with app.app_context():
            from app.services.tenant import set_tier
            sid = make_school(app)
            q, err = set_tier(sid, "pro")
            assert err is None
            assert q.tier == "pro"
            assert q.ai_enabled is True

    def test_set_invalid_tier(self, app):
        with app.app_context():
            from app.services.tenant import set_tier
            q, err = set_tier(1, "invalid")
            assert q is None

    def test_tier_defaults(self):
        from app.services.tenant import TIER_DEFAULTS
        assert "free" in TIER_DEFAULTS
        assert "enterprise" in TIER_DEFAULTS
        assert TIER_DEFAULTS["enterprise"]["max_students"] > TIER_DEFAULTS["free"]["max_students"]


# ── Individual ──
class TestIndividual:
    def test_get_public_classes(self, app):
        with app.app_context():
            from app.services.individual import get_public_classes
            classes = get_public_classes()
            assert isinstance(classes, list)


# ── Invoice ──
class TestInvoice:
    def test_generate_invoice_number(self, app):
        with app.app_context():
            from app.services.invoice import generate_invoice_number
            from unittest.mock import MagicMock
            sub = MagicMock()
            sub.class_id = 5
            sub.id = 42
            num = generate_invoice_number(sub)
            assert "INV-5" in num
            assert "42" in num


# Import helper
from tests.conftest import make_school, make_user
