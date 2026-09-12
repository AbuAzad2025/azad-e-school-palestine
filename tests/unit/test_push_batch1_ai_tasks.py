"""97% push — batch 1: services/ai.py async paths, tasks internals, gamification, email.

Every test targets a CI-verified missed line (coverage.xml from run 34714987468).
Async methods are driven via asyncio.run since pytest-asyncio is not installed.
External boundaries (OpenAI SDK, requests) are mocked; store/DB effects stay real.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock, patch

import pytest
from tests.conftest import make_school, make_user

# ═════════════════════════════ services/ai.py ═════════════════════════════


def _reset_ai_singletons():
    from app.services.ai import AiService

    AiService._rate_limiter = None
    AiService._budget_tracker = None
    AiService._client = None


@pytest.fixture()
def ai_service():
    _reset_ai_singletons()
    from app.services.ai import AiService

    svc = AiService()
    svc.config.api_key = ""  # force mock/offline paths
    yield svc
    _reset_ai_singletons()


class TestRateLimiterAndBudget:
    def test_rate_limiter_rpm_exceeded(self):
        from app.services.ai import RateLimiter

        rl = RateLimiter(max_rpm=1, max_tpm=100000)
        ok, _ = rl.can_proceed()
        assert ok
        rl.record_request(10)
        ok, msg = rl.can_proceed()
        assert not ok
        assert "requests/minute" in msg

    def test_rate_limiter_tpm_exceeded(self):
        from app.services.ai import RateLimiter

        rl = RateLimiter(max_rpm=100, max_tpm=50)
        ok, msg = rl.can_proceed(estimated_tokens=100)
        assert not ok
        assert "tokens/minute" in msg

    def test_rate_limiter_window_cleanup(self):
        import time

        from app.services.ai import RateLimiter

        rl = RateLimiter(max_rpm=1, max_tpm=100000)
        rl.record_request(5)
        # simulate old entries
        rl.request_times[0] = time.time() - 3600
        rl.token_usage[0] = (time.time() - 3600, 5)
        ok, _ = rl.can_proceed()
        assert ok
        assert len(rl.request_times) == 0

    def test_budget_monthly_reset(self):
        from datetime import datetime, timedelta

        from app.services.ai import BudgetTracker

        bt = BudgetTracker(10.0)
        bt._last_reset = datetime.utcnow() - timedelta(days=40)
        bt._monthly_spent = 9.5
        usage = bt.get_usage()  # triggers month rollover
        assert usage["spent_usd"] == 0.0

    def test_budget_exceeded(self):
        from app.services.ai import BudgetTracker

        bt = BudgetTracker(5.0)
        bt.record_spending(4.0)
        ok, msg = bt.can_spend(2.0)
        assert not ok
        assert "budget" in msg.lower()

    def test_budget_zero_division_guard(self):
        from app.services.ai import BudgetTracker

        bt = BudgetTracker(0.0)
        usage = bt.get_usage()
        assert usage["usage_percent"] == 0


class TestSuggestGradePaths:
    def test_mcq_mock_fallback(self, ai_service):
        result = asyncio.run(ai_service.suggest_grade("B", "mcq", correct_answer="A"))
        assert "score" in result
        assert result.get("mistake") is None

    def test_true_false_mock_fallback(self, ai_service):
        result = asyncio.run(ai_service.suggest_grade("true", "true_false"))
        assert result.get("correct") is True

    def test_essay_mock_fallback(self, ai_service):
        result = asyncio.run(ai_service.suggest_grade("نص طويل", "essay"))
        assert "strengths" in result

    def test_unknown_type_mock_fallback(self, ai_service):
        result = asyncio.run(ai_service.suggest_grade("x", "short_answer"))
        assert result == {"score": 5}

    def test_real_api_success_path(self, ai_service):
        ai_service.config.api_key = "sk-test"
        fake_response = MagicMock()
        fake_response.choices = [MagicMock(message=MagicMock(content='{"score": 9, "feedback": "g"}'))]
        fake_response.usage = MagicMock(prompt_tokens=100, completion_tokens=50)
        client = MagicMock()
        client.chat.completions.create = (
            asyncio.coroutine(lambda **kw: fake_response) if hasattr(asyncio, "coroutine") else None
        )

        # modern approach: an async function
        async def _create(**kw):
            return fake_response

        client.chat.completions.create = _create
        with (
            patch.object(ai_service, "_get_client", return_value=client),
            patch.object(ai_service, "_record_usage") as rec,
        ):
            result = asyncio.run(ai_service.suggest_grade("42", "mcq", correct_answer="42"))
        assert result["score"] == 9
        rec.assert_called_once()

    def test_real_api_exception_returns_fallback(self, ai_service):
        ai_service.config.api_key = "sk-test"

        async def _boom(**kw):
            raise RuntimeError("api down")

        client = MagicMock()
        client.chat.completions.create = _boom
        with patch.object(ai_service, "_get_client", return_value=client):
            result = asyncio.run(ai_service.suggest_grade("x", "mcq"))
        assert "error" in result
        assert "fallback" in result

    def test_rate_limited_returns_fallback(self, ai_service):
        ai_service.config.api_key = "sk-test"
        with patch.object(ai_service, "_check_limits", return_value=(False, "Rate limit: 60 rpm")):
            result = asyncio.run(ai_service.suggest_grade("x", "essay"))
        assert result["error"].startswith("Rate limit")


class TestGenerateQuestionsPaths:
    def test_mock_fallback(self, ai_service):
        qs = asyncio.run(ai_service.generate_questions("كسور", count=3))
        assert len(qs) == 3

    def test_real_api_success_parses_questions(self, ai_service):
        ai_service.config.api_key = "sk-test"
        payload = {
            "questions": [
                {
                    "type": "mcq",
                    "prompt": "2+2?",
                    "options": {"a": "4", "b": "5"},
                    "correct_answer": {"value": "a"},
                    "mark": 1,
                },
                {"type": "essay", "prompt": "اشرح", "mark": 5},
            ]
        }
        fake_response = MagicMock()
        fake_response.choices = [MagicMock(message=MagicMock(content=json.dumps(payload)))]
        fake_response.usage = MagicMock(prompt_tokens=200, completion_tokens=120)

        async def _create(**kw):
            return fake_response

        client = MagicMock()
        client.chat.completions.create = _create
        with patch.object(ai_service, "_get_client", return_value=client), patch.object(ai_service, "_record_usage"):
            qs = asyncio.run(ai_service.generate_questions("رياضيات", count=2))
        assert len(qs) == 2
        assert qs[0]["prompt"] == "2+2?"

    def test_real_api_limits_path(self, ai_service):
        ai_service.config.api_key = "sk-test"
        with patch.object(ai_service, "_check_limits", return_value=(False, "Budget: exceeded")):
            qs = asyncio.run(ai_service.generate_questions("t", count=2))
        assert qs[0]["error"].startswith("Budget")

    def test_real_api_exception_path(self, ai_service):
        ai_service.config.api_key = "sk-test"

        async def _boom(**kw):
            raise ValueError("bad json")

        client = MagicMock()
        client.chat.completions.create = _boom
        with patch.object(ai_service, "_get_client", return_value=client):
            qs = asyncio.run(ai_service.generate_questions("t", count=2))
        assert "error" in qs[0]

    def test_record_usage_persists_log(self, app, ai_service):
        uid = make_user(app, role="student")
        with app.app_context():
            ai_service._record_usage(100, 50, uid, "chat")
            from app.models.ai import AiUsageLog

            log = AiUsageLog.query.filter_by(user_id=uid).first()
            assert log is not None
            assert log.total_tokens == 150


class TestChatStreamPaths:
    def test_get_or_create_session(self, app, ai_service):
        uid = make_user(app, role="student")
        with app.app_context():
            s1 = ai_service._get_or_create_session(uid, None, None)
            s2 = ai_service._get_or_create_session(uid, None, None)
            assert s1.id == s2.id

    def test_build_chat_messages_includes_history(self, app, ai_service):
        uid = make_user(app, role="student")
        with app.app_context():
            s = ai_service._get_or_create_session(uid, None, None)
            ai_service.log_message(s.id, "user", "سؤال سابق")
            msgs = ai_service._build_chat_messages(s.id, "سؤال جديد", "سياق")
            assert any(m["content"] == "سؤال سابق" for m in msgs)
            assert msgs[-1]["content"] == "سؤال جديد"

    def test_build_chat_messages_trims_history_to_recent_10(self, app, ai_service):
        uid = make_user(app, role="student")
        with app.app_context():
            s = ai_service._get_or_create_session(uid, None, None)
            for i in range(12):
                ai_service.log_message(s.id, "user" if i % 2 == 0 else "assistant", f"msg{i}")
            msgs = ai_service._build_chat_messages(s.id, "now", None)
            # system prompt + 10 most-recent history messages + the new question
            assert len(msgs) == 12
            assert msgs[-1]["content"] == "now"
            # oldest trimmed messages must not appear
            assert all(m["content"] != "msg0" for m in msgs)
            assert all(m["content"] != "msg1" for m in msgs)

    def test_mock_stream_yields_deltas_and_done(self, ai_service):
        chunks = list(asyncio.run(_collect(ai_service._mock_stream("ما هو العدد الأول؟", None))))
        assert any("[DONE]" in c for c in chunks)
        assert any("delta" in c for c in chunks)

    def test_mock_ai_answer_is_arabic_guidance(self, ai_service):
        ans = ai_service._mock_ai_answer("ما هي أنواع الكسور؟", "درس الكسور")
        assert ans.startswith("سؤالك:")
        assert len(ans) > 20

    def test_ask_question_stream_offline_yields_done(self, app, ai_service):
        uid = make_user(app, role="student")
        with app.test_request_context("/"):
            chunks = list(asyncio.run(_collect(ai_service.ask_question_stream(uid, "سؤال"))))

        assert any("[DONE]" in c for c in chunks)

    def test_ask_question_non_streaming(self, app, ai_service):
        uid = make_user(app, role="student")
        with app.test_request_context("/"):
            result = asyncio.run(ai_service.ask_question(uid, "سؤال", context="سياق"))
        assert isinstance(result, dict)
        assert result.get("answer")

    def test_real_stream_limit_error_yields_error_event(self, app, ai_service):
        uid = make_user(app, role="student")
        ai_service.config.api_key = "sk-test"
        with app.app_context():
            s = ai_service._get_or_create_session(uid, None, None)
            with patch.object(ai_service, "_check_limits", return_value=(False, "Budget: gone")):
                chunks = list(asyncio.run(_collect(ai_service._real_stream([{"role": "user", "content": "q"}], s.id))))
        assert any('"error"' in c for c in chunks)
        assert any("[DONE]" in c for c in chunks)

    def test_real_stream_success_records_usage(self, app, ai_service):
        uid = make_user(app, role="student")
        ai_service.config.api_key = "sk-test"

        class _Delta:
            content = "مرحبا"

        class _Chunk:
            choices = [MagicMock(delta=_Delta())]
            usage = None

        class _UsageChunk:
            choices = [MagicMock(delta=_Delta())]
            usage = MagicMock(prompt_tokens=10, completion_tokens=20)

        class _Stream:
            def __init__(self):
                self._items = [_Chunk(), _UsageChunk()]

            def __aiter__(self):
                return self

            async def __anext__(self):
                if not self._items:
                    raise StopAsyncIteration
                return self._items.pop(0)

        async def _create(**kw):
            return _Stream()

        client = MagicMock()
        client.chat.completions.create = _create
        with app.app_context():
            s = ai_service._get_or_create_session(uid, None, None)
            with (
                patch.object(ai_service, "_get_client", return_value=client),
                patch.object(ai_service, "_record_usage") as rec,
            ):
                chunks = list(asyncio.run(_collect(ai_service._real_stream([{"role": "user", "content": "q"}], s.id))))
        assert any('"delta"' in c for c in chunks)  # json.dumps escapes Arabic
        rec.assert_called_once()

    def test_real_stream_exception_yields_error(self, app, ai_service):
        uid = make_user(app, role="student")
        ai_service.config.api_key = "sk-test"

        async def _boom(**kw):
            raise RuntimeError("down")

        client = MagicMock()
        client.chat.completions.create = _boom
        with app.app_context():
            ai_service._get_or_create_session(uid, None, None)
            with patch.object(ai_service, "_get_client", return_value=client):
                chunks = list(asyncio.run(_collect(ai_service.ask_question_stream(uid, "q"))))
        assert any('"error"' in c for c in chunks)
        assert any("[DONE]" in c for c in chunks)


class TestUsageStats:
    def test_usage_stats_empty_and_budget(self, app, ai_service):
        with app.app_context():
            stats = ai_service.get_usage_stats(days=7)
            assert stats["total_requests"] == 0
            assert "budget" in stats and "rate_limit" in stats

    def test_usage_stats_with_user_filter(self, app, ai_service):
        uid = make_user(app, role="student")
        with app.app_context():
            ai_service._record_usage(10, 5, uid, "chat")
            stats = ai_service.get_usage_stats(user_id=uid)
            assert stats["total_requests"] == 1
            assert stats["by_action"]["chat"] == 1


async def _collect(agen):
    """Collect all chunks from an async generator."""
    out = []
    async for chunk in agen:
        out.append(chunk)
    return out


# ═════════════════════════════ tasks/grading.py batch functions ═════════════════════════════


class TestBatchGradebookTask:
    """batch_update_gradebook — importable via the celery-guard harness."""

    @pytest.fixture()
    def grading(self):
        with patch("app.tasks._HAS_CELERY", True):
            mock_celery = MagicMock()

            def _task_dec(*a, **kw):
                if a:
                    return a[0]
                return lambda f: f

            mock_celery.task.side_effect = _task_dec
            with patch("app.tasks.celery_app", mock_celery):
                import app.tasks.grading as grading

                yield grading

    def test_batch_update_gradebook_upsert(self, app, grading):
        from tests.conftest import (
            make_class,
            make_grade,
            make_grade_category,
            make_grade_item,
            make_subject,
            make_user,
        )

        sid = make_school(app)
        gid = make_grade(app, sid)
        subj = make_subject(app)
        cid = make_class(app, sid, gid, subj)
        cat = make_grade_category(app, cid, "أعمال", 50)
        item = make_grade_item(app, cid, cat, "بند", 100)
        s1 = make_user(app, role="student", school_id=sid)
        s2 = make_user(app, role="student", school_id=sid)
        with app.app_context():
            result = grading.batch_update_gradebook(
                None,
                cid,
                item,
                [
                    {"student_id": s1, "mark": 90.0, "note": "جيد"},
                    {"student_id": s2, "mark": 75.0, "note": None},
                ],
            )
        assert result["status"] == "completed"
        assert result["updated"] == 2

    def test_batch_update_gradebook_wrong_class_fails(self, app, grading):
        from tests.conftest import make_class, make_grade, make_grade_category, make_grade_item, make_subject

        sid = make_school(app)
        gid = make_grade(app, sid)
        subj = make_subject(app)
        cid = make_class(app, sid, gid, subj)
        cat = make_grade_category(app, cid, "أعمال", 50)
        item = make_grade_item(app, cid, cat, "بند", 100)
        with app.app_context():
            result = grading.batch_update_gradebook(None, cid + 1000, item, [])
        assert result["status"] == "failed"
        assert result["updated"] == 0


# ═════════════════════════════ services/gamification.py ═════════════════════════════


class TestGamificationGaps:
    def test_check_streak_insufficient_days(self, app):
        from app.services.gamification import _check_streak

        uid = make_user(app, role="student")
        with app.app_context():
            assert _check_streak(uid, 7) is False

    def test_check_streak_progress_in_last_days_counts(self, app):
        """Progress on recent days feeds the streak query; gaps break it."""
        from datetime import UTC, datetime, timedelta

        from app.extensions import db
        from app.models.progress import StudentProgress
        from app.services.gamification import _check_streak
        from tests.conftest import (
            make_class,
            make_grade,
            make_lesson,
            make_student_progress,
            make_subject,
        )

        sid = make_school(app)
        gid = make_grade(app, sid)
        subj = make_subject(app)
        cid = make_class(app, sid, gid, subj)
        uid = make_user(app, role="student", school_id=sid)
        for _ in range(3):
            lid = make_lesson(app, cid)
            make_student_progress(app, uid, lid, cid)
        with app.app_context():
            # spread completed_at over the last 3 days (DB column is naive UTC)
            rows = StudentProgress.query.filter_by(student_id=uid).all()
            for i, row in enumerate(rows):
                row.completed_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=i)
            db.session.commit()
            # 3 consecutive days < 7 → False, but the streak loop ran
            assert _check_streak(uid, 2) is True
            assert _check_streak(uid, 7) is False

    def test_check_course_complete_no_class(self, app):
        from app.services.gamification import _check_course_complete

        uid = make_user(app, role="student")
        with app.app_context():
            assert _check_course_complete(uid, None) is False

    def test_check_course_complete_all_done(self, app):
        from app.services.gamification import _check_course_complete
        from tests.conftest import make_class, make_grade, make_lesson, make_student_progress, make_subject

        sid = make_school(app)
        gid = make_grade(app, sid)
        subj = make_subject(app)
        cid = make_class(app, sid, gid, subj)
        uid = make_user(app, role="student", school_id=sid)
        lid = make_lesson(app, cid)
        make_student_progress(app, uid, lid, cid, status="completed", pct=100)
        with app.app_context():
            assert _check_course_complete(uid, cid) is True

    def test_check_and_award_first_quiz_badge(self, app):
        from app.extensions import db
        from app.models.gamification import Badge, BadgeCriteriaType

        uid = make_user(app, role="student")
        with app.app_context():
            b = Badge(name="أول اختبار", icon_name="medal", criteria_type=BadgeCriteriaType.first_quiz, is_active=True)
            db.session.add(b)
            db.session.commit()
            from app.services.gamification import check_and_award_badges

            awarded = check_and_award_badges(uid, "quiz_submitted", {"score": 8, "max_score": 10})
            assert len(awarded) == 1
            # second call must not re-award
            awarded2 = check_and_award_badges(uid, "quiz_submitted", {})
            assert awarded2 == []

    def test_check_and_award_perfect_score_requires_exact(self, app):
        from app.extensions import db
        from app.models.gamification import Badge, BadgeCriteriaType

        uid = make_user(app, role="student")
        with app.app_context():
            b = Badge(name="مثالي", icon_name="star", criteria_type=BadgeCriteriaType.perfect_score, is_active=True)
            db.session.add(b)
            db.session.commit()
            from app.services.gamification import check_and_award_badges

            assert check_and_award_badges(uid, "quiz_submitted", {"score": 8, "max_score": 10}) == []
            awarded = check_and_award_badges(uid, "quiz_submitted", {"score": 10, "max_score": 10})
            assert len(awarded) == 1
