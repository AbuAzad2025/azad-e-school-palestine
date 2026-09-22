"""Batch 3 — app/services/ai.py deep branches (deterministic, offline).

Targets the uncovered half of AiService: rate-limit/budget refusal paths,
_record_usage DB logging, real-API paths via mocked AsyncOpenAI client
(SDK present in this venv), streaming error paths, session management and
usage statistics — without any network access.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.conftest import _uid, make_user

PASSWORD = "TestPass123!"


@pytest.fixture(autouse=True)
def _reset_ai_singletons():
    """Isolate class-level singletons between tests (rate/budget state leaks)."""
    from app.services.ai import AiService

    saved = (AiService._rate_limiter, AiService._budget_tracker, AiService._client)
    AiService._rate_limiter = None
    AiService._budget_tracker = None
    AiService._client = None
    yield
    AiService._rate_limiter, AiService._budget_tracker, AiService._client = saved


def _mock_completion(content: str, prompt_tokens: int = 120, completion_tokens: int = 60) -> MagicMock:
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content=content))]
    resp.usage = MagicMock(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
    return resp


def _with_api_key(svc) -> None:
    """Force the 'real API' code paths offline-deterministically."""
    svc.config.api_key = "sk-test-key"


class TestLimitsRefusalPaths:
    def test_check_limits_rate_refused(self, app):
        from app.services.ai import AiService

        with app.app_context():
            svc = AiService()
            _with_api_key(svc)
            assert svc._rate_limiter is not None
            for _ in range(svc._rate_limiter.max_rpm):
                svc._rate_limiter.record_request(10)
            can, msg = svc._check_limits(100)
            assert can is False
            assert "Rate limit" in msg

    def test_check_limits_budget_refused(self, app):
        from app.services.ai import AiService, BudgetTracker

        with app.app_context():
            svc = AiService()
            _with_api_key(svc)
            # _check_limits reads the CLASS singleton, not the instance attr.
            AiService._budget_tracker = BudgetTracker(monthly_budget_usd=0.0)
            can, msg = svc._check_limits(1000)
            assert can is False
            assert "Budget" in msg

    def test_check_limits_no_singletons_allows(self, app):
        from app.services.ai import AiService

        with app.app_context():
            svc = AiService()
            AiService._rate_limiter = None
            AiService._budget_tracker = None
            can, msg = svc._check_limits(5000)
            assert (can, msg) == (True, "")


class TestRecordUsageAndPricing:
    def test_record_usage_writes_db_log(self, app):
        from app.extensions import db
        from app.models.ai import AiUsageLog
        from app.services.ai import AiService

        uid = make_user(app, role="student", email=f"b3-{_uid()}@t.com")
        with app.app_context():
            svc = AiService()
            svc._record_usage(prompt_tokens=100, completion_tokens=40, user_id=uid, action="chat")
            log = AiUsageLog.query.filter_by(user_id=uid, action="chat").first()
            assert log is not None
            assert log.total_tokens == 140
            assert log.estimated_cost_usd >= 0
            db.session.rollback()  # leave clean state for the guard

    def test_estimate_cost_unknown_model_falls_back(self, app):
        from app.services.ai import MODEL_PRICING, AiService

        with app.app_context():
            svc = AiService()
            svc.config.model = "definitely-unknown-model"
            cost = svc._estimate_cost(1000, 1000)
            mini = MODEL_PRICING["gpt-4o-mini"]
            expected = mini["input"] + mini["output"]
            assert cost == pytest.approx(expected)


class TestSuggestGradeRealAndErrors:
    def _svc(self, app):
        from app.services.ai import AiService

        return AiService()

    def test_mcq_success_records_usage(self, app):
        from app.services.ai import AiService

        with app.app_context():
            svc = self._svc(app)
            _with_api_key(svc)
            svc._record_usage = MagicMock()
            payload = json.dumps({"score": 9, "feedback": "ممتاز", "mistake": None})
            with patch.object(AiService, "_get_client") as gc:
                gc.return_value.chat.completions.create = AsyncMock(
                    return_value=_mock_completion(payload, 200, 80)
                )
                result = asyncio.run(
                    svc.suggest_grade(
                        student_answer="B",
                        question_type="mcq",
                        correct_answer="B",
                        rubric="قياسي",
                        user_id=1,
                    )
                )
            assert result == {"score": 9, "feedback": "ممتاز", "mistake": None}
            svc._record_usage.assert_called_once_with(200, 80, 0, "suggest_grade")

    def test_true_false_and_essay_and_other_prompt_branches(self, app):
        """All prompt-construction branches run with a failing client → fallback dict."""
        from app.services.ai import AiService

        with app.app_context():
            svc = self._svc(app)
            _with_api_key(svc)
            for qt in ("true_false", "essay", "short_answer"):
                with patch.object(AiService, "_get_client") as gc:
                    gc.return_value.chat.completions.create = AsyncMock(
                        side_effect=RuntimeError("boom")
                    )
                    result = asyncio.run(
                        svc.suggest_grade(student_answer="ج", question_type=qt, correct_answer="ص")
                    )
                assert "error" in result
                assert "fallback" in result
                assert result["fallback"]["score"] >= 5

    def test_rate_limited_returns_error_with_fallback(self, app):
        from app.services.ai import AiService, RateLimiter

        with app.app_context():
            svc = self._svc(app)
            _with_api_key(svc)
            AiService._rate_limiter = RateLimiter(max_rpm=0, max_tpm=10_000)
            result = asyncio.run(svc.suggest_grade(student_answer="x", question_type="essay"))
            assert "error" in result
            assert "fallback" in result

    def test_mock_grade_question_type_matrix(self, app):
        from app.services.ai import AiService

        with app.app_context():
            svc = self._svc(app)
            mcq = svc._mock_grade("mcq", "A")
            assert set(mcq) == {"score", "feedback", "mistake"}
            tf = svc._mock_grade("true_false", True)
            assert tf["correct"] is True
            essay = svc._mock_grade("essay", None)
            assert essay["strengths"] and essay["improvements"]
            assert svc._mock_grade("other", None) == {"score": 5}


class TestGenerateQuestionsRealAndErrors:
    def test_success_parses_dict_payload_and_truncates(self, app):
        from app.services.ai import AiService

        with app.app_context():
            svc = AiService()
            _with_api_key(svc)
            svc._record_usage = MagicMock()  # hardcoded user_id=0 would violate FK
            payload = json.dumps(
                {
                    "questions": [
                        {"type": "mcq", "prompt": f"س{i}"} for i in range(4)
                    ]
                }
            )
            with patch.object(AiService, "_get_client") as gc:
                gc.return_value.chat.completions.create = AsyncMock(
                    return_value=_mock_completion(payload, 300, 150)
                )
                qs = asyncio.run(svc.generate_questions(topic="الكسور", count=2, user_id=1))
            assert len(qs) == 2  # truncated to count
            assert qs[0]["prompt"] == "س0"
            svc._record_usage.assert_called_once_with(300, 150, 0, "generate_questions")

    def test_success_parses_bare_list_payload(self, app):
        from app.services.ai import AiService

        with app.app_context():
            svc = AiService()
            _with_api_key(svc)
            svc._record_usage = MagicMock()  # hardcoded user_id=0 would violate FK
            payload = json.dumps([{"type": "essay", "prompt": "ق1"}])
            with patch.object(AiService, "_get_client") as gc:
                gc.return_value.chat.completions.create = AsyncMock(
                    return_value=_mock_completion(payload)
                )
                qs = asyncio.run(svc.generate_questions(topic="قواعد", count=5))
            assert qs == [{"type": "essay", "prompt": "ق1"}]

    def test_exception_returns_error_plus_mocks(self, app):
        from app.services.ai import AiService

        with app.app_context():
            svc = AiService()
            _with_api_key(svc)
            with patch.object(AiService, "_get_client") as gc:
                gc.return_value.chat.completions.create = AsyncMock(
                    side_effect=RuntimeError("network down")
                )
                qs = asyncio.run(svc.generate_questions(topic="هندسة", count=3))
            assert "error" in qs[0]
            assert len(qs) == 4  # error marker + 3 mock questions

    def test_rate_limited_prepends_error(self, app):
        from app.services.ai import AiService, RateLimiter

        with app.app_context():
            svc = AiService()
            _with_api_key(svc)
            AiService._rate_limiter = RateLimiter(max_rpm=0, max_tpm=10_000)
            qs = asyncio.run(svc.generate_questions(topic="قياس", count=2))
            assert "error" in qs[0]

    def test_mock_questions_type_cycle(self, app):
        from app.services.ai import AiService

        with app.app_context():
            qs = AiService()._mock_generate_questions("نحو", 5, ["mcq", "true_false", "essay"])
            assert [q["type"] for q in qs] == ["mcq", "true_false", "essay", "mcq", "true_false"]


class TestChatStreamingPaths:
    def test_real_stream_emits_deltas_usage_and_saves_message(self, app):
        from app.extensions import db
        from app.models.ai import AiMessage
        from app.services.ai import AiService

        uid = make_user(app, role="student", email=f"b3-{_uid()}@t.com")
        with app.app_context():
            svc = AiService()
            svc._record_usage = MagicMock()  # hardcoded user_id=0 would violate FK
            session = svc.start_session(uid, "student_helper")

            def _chunk(text, usage=None):
                c = MagicMock()
                c.choices = [MagicMock(delta=MagicMock(content=text))]
                c.usage = usage
                return c

            stream_obj = MagicMock()
            stream_obj.__aiter__.return_value = iter(
                [
                    _chunk("مرحبا "),
                    _chunk("بك"),
                    _chunk(None),  # empty delta skipped
                    _chunk("",
                           usage=MagicMock(prompt_tokens=90, completion_tokens=30)),
                ]
            )
            with patch.object(AiService, "_get_client") as gc:
                gc.return_value.chat.completions.create = AsyncMock(return_value=stream_obj)
                chunks = asyncio.run(
                    _collect(svc._real_stream([{"role": "user", "content": "hi"}], session.id))
                )

            assert chunks[-1] == "data: [DONE]\n\n"
            joined = "".join(chunks)
            # JSON-escaped unicode — decode the deltas before asserting content
            deltas = [
                json.loads(c[6:])["delta"]
                for c in chunks
                if c.startswith("data: {")
            ]
            assert "مرحبا" in "".join(deltas) and "بك" in "".join(deltas)
            assistant = (
                AiMessage.query.filter_by(session_id=session.id, role="assistant")
                .order_by(AiMessage.id.desc())
                .first()
            )
            assert assistant is not None and "مرحبا بك" in assistant.content
            db.session.rollback()

    def test_real_stream_rate_limited_emits_error_event(self, app):
        from app.services.ai import AiService, RateLimiter

        with app.app_context():
            svc = AiService()
            AiService._rate_limiter = RateLimiter(max_rpm=0, max_tpm=10_000)
            chunks = asyncio.run(
                _collect(svc._real_stream([{"role": "user", "content": "hi"}], 1))
            )
            assert any("error" in c for c in chunks)
            assert chunks[-1] == "data: [DONE]\n\n"

    def test_ask_question_stream_real_path_yields_then_error_event(self, app):
        from app.services.ai import AiService

        uid = make_user(app, role="student", email=f"b3-{_uid()}@t.com")
        with app.app_context():
            svc = AiService()
            _with_api_key(svc)
            with patch.object(svc, "_real_stream") as rs:
                async def _boom(*a, **k):
                    raise RuntimeError("connection reset")
                    yield  # pragma: no cover

                rs.side_effect = _boom
                chunks = asyncio.run(
                    _collect(svc.ask_question_stream(uid, "سؤال", context="رياضيات", class_id=None, lesson_id=None))
                )
            assert any('"error"' in c for c in chunks)
            assert chunks[-1] == "data: [DONE]\n\n"

    def test_ask_question_collects_deltas_and_skips_bad_json(self, app):
        from app.services.ai import AiService

        uid = make_user(app, role="student", email=f"b3-{_uid()}@t.com")
        with app.app_context():
            svc = AiService()
            svc.start_session(uid, "student_helper")  # so ask_question finds session_id

            async def _synthetic(*a, **k):
                for raw in (
                    'data: {"delta": "جزء"}\n\n',
                    "data: not-json\n\n",  # JSONDecodeError branch
                    'data: {"other": 1}\n\n',  # KeyError branch
                    "data: [DONE]\n\n",
                ):
                    yield raw

            with patch.object(svc, "ask_question_stream", _synthetic):
                result = asyncio.run(svc.ask_question(uid, "س"))
            assert result["answer"] == "جزء"
            assert result["session_id"] is not None

    def test_get_or_create_session_reuses_existing(self, app):
        from app.services.ai import AiService

        uid = make_user(app, role="student", email=f"b3-{_uid()}@t.com")
        with app.app_context():
            svc = AiService()
            s1 = svc._get_or_create_session(uid, None, None)
            s2 = svc._get_or_create_session(uid, 5, 7)
            assert s1.id == s2.id  # reused, not duplicated

    def test_build_chat_messages_history_filtering(self, app):
        from app.services.ai import AiService

        uid = make_user(app, role="student", email=f"b3-{_uid()}@t.com")
        with app.app_context():
            svc = AiService()
            session = svc._get_or_create_session(uid, None, None)
            svc.log_message(session.id, "user", "س1")
            svc.log_message(session.id, "assistant", "ج1")
            svc.log_message(session.id, "system", "ملاحظة داخلية")  # filtered out
            msgs = svc._build_chat_messages(session.id, "سؤال جديد", "سياق الدرس")
            assert msgs[0]["role"] == "system"
            assert "سياق الدرس" in msgs[0]["content"]
            roles = [m["role"] for m in msgs[1:]]
            assert roles == ["user", "assistant", "user"]


class TestSessionAndStats:
    def test_start_session_and_log_message_persist(self, app):
        from app.extensions import db
        from app.models.ai import AiMessage, AiSession
        from app.services.ai import AiService

        uid = make_user(app, role="student", email=f"b3-{_uid()}@t.com")
        with app.app_context():
            svc = AiService()
            s = svc.start_session(uid, "quiz_gen", class_id=None, lesson_id=None)
            assert db.session.get(AiSession, s.id) is not None
            m = svc.log_message(s.id, "assistant", "إجابة")
            assert db.session.get(AiMessage, m.id).content == "إجابة"
            db.session.rollback()

    def test_get_usage_stats_empty_and_populated(self, app):
        from app.extensions import db
        from app.models.ai import AiUsageLog
        from app.services.ai import AiService

        with app.app_context():
            svc = AiService()
            empty = svc.get_usage_stats(days=7)
            assert empty["period_days"] == 7
            assert empty["total_requests"] == 0
            assert "requests_per_minute" in empty["rate_limit"]

            db.session.add(
                AiUsageLog(
                    user_id=None,
                    model="gpt-4o-mini",
                    prompt_tokens=10,
                    completion_tokens=5,
                    total_tokens=15,
                    estimated_cost_usd=0.01,
                    action="chat",
                )
            )
            db.session.commit()
            stats = svc.get_usage_stats(days=30)
            assert stats["total_requests"] >= 1
            assert stats["total_tokens"] >= 15
            assert stats["by_action"].get("chat", 0) >= 1
            assert stats["by_model"].get("gpt-4o-mini", 0) >= 1
            db.session.rollback()


async def _collect(agen) -> list[str]:
    out = []
    async for chunk in agen:
        out.append(chunk)
    return out
