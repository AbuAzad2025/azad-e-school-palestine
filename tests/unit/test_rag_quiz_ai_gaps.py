"""Batch 4 — RAG embedding/LLM paths + quiz-AI pipeline gaps (verified misses).

Targets from the coverage audit (previous suites stop at the TF path):
- rag_service: _embeddings_enabled env/config branches, _get_embedding_client
  (openai SDK + requests fallback + cache), _embed_texts_remote (requests
  shape + sorted indexing + failure→None), dense retrieval scoring, LLM call
  with real request shape, _fallback_llm_query both branches.
- quiz_ai_service: generate_quiz_from_lesson full pipeline (success, empty
  lesson, LLM exception, unparseable response), _normalize_question branches,
  _call_llm offline/remote/failure, _parse_llm_response array-extraction.

All external calls mocked at the boundary (requests.post / OpenAI SDK);
store and DB effects are real.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from tests.conftest import make_class, make_grade, make_lesson, make_school, make_subject, make_user

# ═══════════════════════════════════════════════════════════════════════════
# rag_service — embedding + LLM paths
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture()
def rag_school(app):
    sid = make_school(app)
    with app.app_context():
        from app.services.rag_service import _chunk_store

        _chunk_store.pop(sid, None)
    return sid


@pytest.fixture(autouse=True)
def _clean_chunk_store(app, rag_school):
    yield
    with app.app_context():
        from app.services.rag_service import _chunk_store

        _chunk_store.pop(rag_school, None)


class TestEmbeddingGate:
    def test_env_kill_switch(self, app, monkeypatch):
        from app.services.rag_service import _embeddings_enabled

        monkeypatch.setenv("RAG_DISABLE_EMBEDDINGS", "1")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        with app.app_context():
            assert _embeddings_enabled() is False

    def test_enabled_with_api_key_config(self, app, monkeypatch):
        from app.services.rag_service import _embeddings_enabled

        monkeypatch.delenv("RAG_DISABLE_EMBEDDINGS", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with app.app_context():
            app.config["OPENAI_API_KEY"] = "sk-cfg"
            assert _embeddings_enabled() is True
            app.config["OPENAI_API_KEY"] = ""

    def test_disabled_without_key(self, app, monkeypatch):
        from app.services.rag_service import _embeddings_enabled

        monkeypatch.delenv("RAG_DISABLE_EMBEDDINGS", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with app.app_context():
            app.config["OPENAI_API_KEY"] = ""
            assert _embeddings_enabled() is False


class TestEmbeddingClient:
    def setup_method(self):
        from app.services import rag_service

        rag_service._embedder_cache.clear()

    def test_cache_hit_returns_same_client(self, app, monkeypatch):
        import app.services.rag_service as rag

        monkeypatch.setenv("OPENAI_API_KEY", "sk-cache-test")
        with app.app_context():
            c1 = rag._get_embedding_client()
            c2 = rag._get_embedding_client()
            assert c1 is c2
            assert len(rag._embedder_cache) == 1

    def test_requests_fallback_when_openai_missing(self, app, monkeypatch):
        import builtins

        import app.services.rag_service as rag

        monkeypatch.setenv("OPENAI_API_KEY", "sk-requests-path")

        real_import = builtins.__import__

        def fake_import(name, *a, **kw):
            if name == "openai":
                raise ImportError("no openai")
            return real_import(name, *a, **kw)

        with app.app_context():
            with patch("builtins.__import__", side_effect=fake_import):
                client = rag._get_embedding_client()
            assert isinstance(client, tuple)
            assert client[0] == "requests"
            assert client[1] == "sk-requests-path"

    def test_openai_sdk_client_cached(self, app, monkeypatch):
        import sys
        import types

        import app.services.rag_service as rag

        monkeypatch.setenv("OPENAI_API_KEY", "sk-sdk-path")
        fake_openai = types.ModuleType("openai")

        class FakeOpenAI:
            def __init__(self, **kw):
                self.kwargs = kw

        fake_openai.OpenAI = FakeOpenAI
        monkeypatch.setitem(sys.modules, "openai", fake_openai)
        with app.app_context():
            client = rag._get_embedding_client()
            assert isinstance(client, FakeOpenAI)
            assert client.kwargs["api_key"] == "sk-sdk-path"


class TestEmbedTextsRemote:
    def test_empty_texts_returns_empty(self, app):
        from app.services.rag_service import _embed_texts_remote

        assert _embed_texts_remote([]) == []

    def test_requests_path_posts_and_sorts_by_index(self, app, monkeypatch):
        import app.services.rag_service as rag

        monkeypatch.setenv("OPENAI_API_KEY", "sk-req")
        with app.app_context():
            # force the requests-path tuple client
            with patch.object(rag, "_get_embedding_client", return_value=("requests", "sk-req", "https://x/v1")):
                fake_resp = MagicMock()
                fake_resp.json.return_value = {
                    "data": [
                        {"index": 1, "embedding": [0.4, 0.5]},
                        {"index": 0, "embedding": [0.1, 0.2]},
                    ]
                }
                with patch("requests.post", return_value=fake_resp) as post:
                    vecs = rag._embed_texts_remote(["أ", "ب"])

            assert vecs == [[0.1, 0.2], [0.4, 0.5]]  # sorted by index
            assert post.call_args.kwargs["json"]["model"].startswith("text-embedding")
            assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer sk-req"

    def test_any_failure_returns_none(self, app):
        import app.services.rag_service as rag

        with app.app_context():
            with patch.object(rag, "_get_embedding_client", side_effect=RuntimeError("down")):
                assert rag._embed_texts_remote(["x"]) is None

    def test_sdk_path_returns_embeddings(self, app):
        import app.services.rag_service as rag

        with app.app_context():
            sdk_client = MagicMock()
            sdk_client.embeddings.create.return_value.data = [
                MagicMock(embedding=[0.9, 0.8]),
            ]
            with patch.object(rag, "_get_embedding_client", return_value=sdk_client):
                vecs = rag._embed_texts_remote(["نص"])
            assert vecs == [[0.9, 0.8]]


class TestDenseRetrieval:
    def test_dense_path_blends_scores(self, app, rag_school, monkeypatch):
        import app.services.rag_service as rag
        from app.services.rag_service import RAGChunk, retrieve_relevant_chunks

        vec = [1.0, 0.0]
        rag._chunk_store[rag_school] = [
            RAGChunk(text="الكسور الرياضيات", lesson_id=1, school_id=rag_school, chunk_index=0, embedding=vec),
            RAGChunk(text="التاريخ الحديث", lesson_id=2, school_id=rag_school, chunk_index=0, embedding=[0.0, 1.0]),
        ]
        monkeypatch.setenv("OPENAI_API_KEY", "sk-dense")
        with app.app_context():
            app.config["OPENAI_API_KEY"] = "sk-dense"
            with patch.object(rag, "_embed_texts_remote", return_value=[vec]):
                chunks = retrieve_relevant_chunks(rag_school, "الكسور", top_k=2)
        assert chunks, "dense retrieval returned nothing"
        assert chunks[0].lesson_id == 1  # orthogonal vectors → lesson 1 wins

    def test_tf_fallback_when_embeddings_partial(self, app, rag_school):
        import app.services.rag_service as rag
        from app.services.rag_service import RAGChunk, retrieve_relevant_chunks

        rag._chunk_store[rag_school] = [
            RAGChunk(text="الكسور الرياضيات", lesson_id=1, school_id=rag_school, chunk_index=0, embedding=None),
            RAGChunk(text="التاريخ", lesson_id=2, school_id=rag_school, chunk_index=1, embedding=[0.1]),
        ]
        with app.app_context():
            chunks = retrieve_relevant_chunks(rag_school, "الكسور")
        assert [c.lesson_id for c in chunks] == [1]  # TF path, threshold filters lesson 2

    def test_below_threshold_filtered(self, app, rag_school):
        import app.services.rag_service as rag
        from app.services.rag_service import RAGChunk, retrieve_relevant_chunks

        rag._chunk_store[rag_school] = [
            RAGChunk(text="الجبر", lesson_id=1, school_id=rag_school, chunk_index=0, embedding=None)
        ]
        with app.app_context():
            assert retrieve_relevant_chunks(rag_school, "موسيقى غير مرتبطة") == []


class TestLLMWithContext:
    def test_no_key_uses_offline_response(self, app, monkeypatch):
        from app.services.rag_service import _call_llm_with_context

        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with app.app_context():
            app.config["OPENAI_API_KEY"] = ""
            out = _call_llm_with_context("سؤال", "سياق الدرس", 1)
            assert "بناءً على محتوى الدروس" in out

    def test_remote_call_extracts_choice_content(self, app, monkeypatch):
        from app.services.rag_service import _call_llm_with_context

        monkeypatch.setenv("OPENAI_API_KEY", "sk-live")
        fake_resp = MagicMock()
        fake_resp.json.return_value = {"choices": [{"message": {"content": "جواب من النموذج"}}]}
        with app.app_context():
            with patch("requests.post", return_value=fake_resp) as post:
                out = _call_llm_with_context("سؤال", "سياق", 1)
        assert out == "جواب من النموذج"
        body = post.call_args.kwargs["json"]
        assert body["messages"][0]["role"] == "system"
        assert "Context from school materials" in body["messages"][1]["content"]

    def test_request_failure_falls_back_offline(self, app, monkeypatch):
        from app.services.rag_service import _call_llm_with_context

        monkeypatch.setenv("OPENAI_API_KEY", "sk-live")
        with app.app_context():
            with patch("requests.post", side_effect=RuntimeError("boom")):
                out = _call_llm_with_context("سؤال", "", 1)
        assert "عذراً" in out  # no-context offline response

    def test_fallback_llm_query_success_contract(self, app, monkeypatch):
        from app.services.rag_service import _fallback_llm_query

        with app.app_context():
            with patch(
                "app.services.rag_service._call_llm_with_context",
                return_value="إجابة مباشرة",
            ):
                result, err = _fallback_llm_query("س", 1, 2)
        assert err is None
        assert result == {
            "answer": "إجابة مباشرة",
            "sources": [],
            "confidence": "low",
            "method": "direct_llm",
        }

    def test_fallback_llm_query_failure(self, app):
        from app.services.rag_service import _fallback_llm_query

        with app.app_context():
            with patch(
                "app.services.rag_service._call_llm_with_context",
                side_effect=RuntimeError("dead"),
            ):
                result, err = _fallback_llm_query("س", 1, 2)
        assert result is None
        assert "AI query failed" in err


class TestRAGIngestEmbeddingPath:
    def test_ingest_with_embeddings_attached(self, app, rag_school):
        import app.services.rag_service as rag

        sid = make_school(app)
        with app.app_context():
            gid = make_grade(app, sid)
            cid = make_class(app, sid, gid, make_subject(app))
            lid = make_lesson(app, cid, title="الكسور", status="published")
            from app.models.content import Lesson

            lesson = rag.db.session.get(Lesson, lid)
            lesson.body_html = f"<p>{'محتوى للاختبار ' * 200}</p>"  # multi-chunk
            rag.db.session.commit()

            with patch.object(rag, "_embeddings_enabled", return_value=True):
                with patch.object(
                    rag,
                    "_embed_texts_remote",
                    side_effect=lambda texts: [[0.1, 0.2] for _ in texts],
                ):
                    count, err = rag.ingest_lesson_for_rag(lid, sid)

            assert err is None
            assert count >= 1
            stored = rag._chunk_store[sid]
            assert stored and all(c.embedding == [0.1, 0.2] for c in stored)

    def test_ingest_embedding_failure_keeps_none(self, app, rag_school):
        import app.services.rag_service as rag

        sid = make_school(app)
        with app.app_context():
            gid = make_grade(app, sid)
            cid = make_class(app, sid, gid, make_subject(app))
            lid = make_lesson(app, cid, title="د", status="published")

            with patch.object(rag, "_embeddings_enabled", return_value=True):
                with patch.object(rag, "_embed_texts_remote", side_effect=RuntimeError("api down")):
                    count, err = rag.ingest_lesson_for_rag(lid, sid)

            assert err is None
            assert all(c.embedding is None for c in rag._chunk_store[sid])


# ═══════════════════════════════════════════════════════════════════════════
# quiz_ai_service — pipeline + helpers
# ═══════════════════════════════════════════════════════════════════════════


def _lesson_with_content(app, sid):
    with app.app_context():
        gid = make_grade(app, sid)
        cid = make_class(app, sid, gid, make_subject(app))
        lid = make_lesson(app, cid, title="الكسور", status="published")
        from app.extensions import db
        from app.models.content import Lesson

        lesson = db.session.get(Lesson, lid)
        lesson.body_html = "<p>شرح الكسور: نصف، ثلث، ربع.</p>"
        db.session.commit()
    return lid


class TestGenerateQuizPipeline:
    def test_full_success_creates_draft(self, app):
        from app.models.assessment import Question
        from app.services.quiz_ai_service import generate_quiz_from_lesson

        sid = make_school(app)
        teacher = make_user(app, role="teacher", school_id=sid)
        lid = _lesson_with_content(app, sid)
        llm_questions = [
            {
                "question_text": "كم ثلث الوحدة؟",
                "question_type": "mcq",
                "options": {"A": "1/2", "B": "1/3"},
                "correct_answer": "1/3",
                "marks": 2,
                "explanation": "تعريف الثلث",
            },
            {
                "question_text": "النصف أقل من الثلث",
                "question_type": "true_false",
                "correct_answer": "False",
                "marks": 1,
            },
        ]
        with app.app_context():
            with patch(
                "app.services.quiz_ai_service._call_llm",
                return_value=json.dumps(llm_questions, ensure_ascii=False),
            ):
                quiz, err = generate_quiz_from_lesson(lid, question_count=2, difficulty="easy", created_by=teacher)
            assert err is None
            assert quiz.status == "draft"
            assert quiz.created_by == teacher
            qs = Question.query.filter_by(quiz_id=quiz.id).all()
            assert len(qs) == 2
            assert {q.type for q in qs} == {"mcq", "true_false"}
            mcq = next(q for q in qs if q.type == "mcq")
            assert mcq.options == ["1/2", "1/3"]  # dict→sorted list
            assert mcq.correct_answer["value"] == "1/3"

    def test_missing_lesson(self, app):
        from app.services.quiz_ai_service import generate_quiz_from_lesson

        with app.app_context():
            quiz, err = generate_quiz_from_lesson(999_999)
            assert quiz is None and "غير موجود" in err

    def test_empty_lesson_content(self, app):
        from app.services.quiz_ai_service import generate_quiz_from_lesson

        sid = make_school(app)
        with app.app_context():
            gid = make_grade(app, sid)
            cid = make_class(app, sid, gid, make_subject(app))
            lid = make_lesson(app, cid, title="فارغ", status="published")
            from app.extensions import db
            from app.models.content import Lesson

            lesson = db.session.get(Lesson, lid)
            lesson.title = ""
            lesson.body_html = None
            db.session.commit()
            quiz, err = generate_quiz_from_lesson(lid)
            assert quiz is None and "محتوى" in err

    def test_llm_exception_reported(self, app):
        from app.services.quiz_ai_service import generate_quiz_from_lesson

        sid = make_school(app)
        lid = _lesson_with_content(app, sid)
        with app.app_context():
            with patch("app.services.quiz_ai_service._call_llm", side_effect=RuntimeError("api down")):
                quiz, err = generate_quiz_from_lesson(lid)
            assert quiz is None
            assert "LLM API error" in err

    def test_unparseable_llm_response(self, app):
        from app.services.quiz_ai_service import generate_quiz_from_lesson

        sid = make_school(app)
        lid = _lesson_with_content(app, sid)
        with app.app_context():
            with patch("app.services.quiz_ai_service._call_llm", return_value="ليس JSON إطلاقاً"):
                quiz, err = generate_quiz_from_lesson(lid)
            assert quiz is None
            assert "تحليل" in err


class TestNormalizeQuestion:
    def test_invalid_type_coerced_to_mcq(self):
        from app.services.quiz_ai_service import _normalize_question

        out = _normalize_question({"question_text": "س", "question_type": "weird", "correct_answer": "x"})
        assert out["type"] == "mcq"

    def test_non_string_prompt_replaced(self):
        from app.services.quiz_ai_service import _normalize_question

        out = _normalize_question({"question_text": 42, "correct_answer": "x"})
        assert out["prompt"] == "سؤال"

    def test_empty_prompt_replaced(self):
        from app.services.quiz_ai_service import _normalize_question

        out = _normalize_question({"question_text": "   ", "correct_answer": "x"})
        assert out["prompt"] == "سؤال"

    def test_true_false_options_cleared(self):
        """options column is MCQ-only — true_false gets options=None (correct
        answers live in correct_answer.value)."""
        from app.services.quiz_ai_service import _normalize_question

        out = _normalize_question(
            {
                "question_text": "س",
                "question_type": "true_false",
                "options": ["True", "False"],
                "correct_answer": "True",
            }
        )
        assert out["options"] is None
        assert out["correct_answer"]["value"] == "True"

    def test_mcq_dict_options_sorted(self):
        from app.services.quiz_ai_service import _normalize_question

        out = _normalize_question(
            {
                "question_text": "س",
                "question_type": "mcq",
                "options": {"C": "ثلاثة", "A": "واحد", "B": "اثنان"},
                "correct_answer": "واحد",
                "explanation": "تعريف",
                "marks": "3",
            }
        )
        assert out["options"] == ["واحد", "اثنان", "ثلاثة"]
        assert out["correct_answer"] == {"value": "واحد", "explanation": "تعريف"}
        assert out["mark"] == 3.0

    def test_non_mcq_options_cleared_and_bad_mark_defaulted(self):
        from app.services.quiz_ai_service import _normalize_question

        out = _normalize_question({"question_text": "س", "question_type": "essay", "options": ["أ"], "marks": "abc"})
        assert out["options"] is None
        assert out["mark"] == 1.0

    def test_correct_answer_dict_without_value_key(self):
        from app.services.quiz_ai_service import _normalize_question

        out = _normalize_question({"question_text": "س", "question_type": "mcq", "correct_answer": {"index": 2}})
        assert out["correct_answer"]["value"] == {"index": 2}


class TestCallLLMQuiz:
    def test_no_key_offline_quiz(self, app, monkeypatch):
        from app.services.quiz_ai_service import _call_llm, _parse_llm_response

        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with app.app_context():
            app.config["OPENAI_API_KEY"] = ""
            raw = _call_llm("بروميت العنوان: الكسور")
        questions = _parse_llm_response(raw)
        assert questions and len(questions) == 2  # deterministic offline quiz

    def test_remote_success_returns_content(self, app, monkeypatch):
        from app.services.quiz_ai_service import _call_llm

        monkeypatch.setenv("OPENAI_API_KEY", "sk-live")
        fake_resp = MagicMock()
        fake_resp.json.return_value = {
            "choices": [{"message": {"content": json.dumps([{"question_text": "س", "correct_answer": "ج"}])}}]
        }
        with app.app_context():
            with patch("requests.post", return_value=fake_resp) as post:
                out = _call_llm("بروميت")
        assert json.loads(out)[0]["question_text"] == "س"
        assert post.call_args.kwargs["json"]["max_tokens"] == 2000

    def test_remote_failure_offline_fallback(self, app, monkeypatch):
        from app.services.quiz_ai_service import _call_llm

        monkeypatch.setenv("OPENAI_API_KEY", "sk-live")
        with app.app_context():
            with patch("requests.post", side_effect=RuntimeError("timeout")):
                out = _call_llm("العنوان: التكامل")
        assert "التكامل" in out  # offline quiz extracted the title


class TestParseLLMResponse:
    def test_json_array_embedded_in_text(self):
        from app.services.quiz_ai_service import _parse_llm_response

        raw = 'مقدمة عشوائية [{"question_text": "س", "correct_answer": "ج"}] خاتمة'
        assert _parse_llm_response(raw) == [{"question_text": "س", "correct_answer": "ج"}]

    def test_items_without_required_keys_dropped(self):
        from app.services.quiz_ai_service import _parse_llm_response

        raw = json.dumps(
            [
                {"question_text": "س1", "correct_answer": "ج1"},
                {"foo": "bar"},
                {"question_text": "س2"},
            ]
        )
        out = _parse_llm_response(raw)
        assert out == [{"question_text": "س1", "correct_answer": "ج1"}]

    def test_broken_embedded_array_returns_none(self):
        from app.services.quiz_ai_service import _parse_llm_response

        assert _parse_llm_response("قبل [غير مغلق صالح {{ بعد") is None
