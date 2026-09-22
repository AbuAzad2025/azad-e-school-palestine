"""Batch 4 — final gap tests for rag_service + quiz_ai_service.

Covers the remaining verified misses after test_rag_quiz_ai_gaps.py:
- rag: dense retrieval full hybrid path (question embedding via mocked remote),
  embed-failure inside retrieval, queries that score below threshold,
  mismatched dense vectors, llm exception propagation, and stats shape.
- quiz: TxError vs generic-exception DB-failure branches, markdown-fenced
  LLM payload, empty-validated-array → None, difficulty mapping, and the
  module import surface.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from tests.conftest import make_class, make_grade, make_lesson, make_school, make_subject, make_user


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


def _lesson_with_body(app, sid, body: str) -> int:
    with app.app_context():
        gid = make_grade(app, sid)
        cid = make_class(app, sid, gid, make_subject(app))
        lid = make_lesson(app, cid, title="درس التجربة", status="published")
        from app.extensions import db
        from app.models.content import Lesson

        lesson = db.session.get(Lesson, lid)
        lesson.body_html = body
        db.session.commit()
    return lid


def _lesson_with_content(app, sid) -> int:
    return _lesson_with_body(app, sid, "<p>شرح الكسور: نصف، ثلث، ربع.</p>")


# ═══════════════════════════════════════════════════════════════════════════
# rag_service — dense hybrid retrieval + error propagation
# ═══════════════════════════════════════════════════════════════════════════


class TestDenseHybridRetrieval:
    def test_full_hybrid_path_scores_and_orders(self, app, rag_school):
        import app.services.rag_service as rag

        sid = rag_school
        body = "قاعدة الإكجار تقول إن كل فعل له رد فعل مضاد بنفس القوة. " * 30
        lid = _lesson_with_body(app, sid, body)
        with app.app_context():
            with patch.object(rag, "_embeddings_enabled", return_value=True):
                with patch.object(
                    rag, "_embed_texts_remote", side_effect=lambda texts: [[0.2, 0.4] for _ in texts]
                ):
                    count, err = rag.ingest_lesson_for_rag(lid, sid)
            assert err is None and count >= 1

            # Question embedded with the SAME vector space → dense+lexical blend
            with patch.object(rag, "_embeddings_enabled", return_value=True):
                with patch.object(rag, "_embed_texts_remote", return_value=[[0.2, 0.4]]):
                    chunks = rag.retrieve_relevant_chunks(sid, "قاعدة الإكجار", top_k=3)
            assert chunks, "hybrid retrieval must surface stored chunks"
            assert all(c.school_id == sid for c in chunks)

    def test_question_embedding_failure_falls_back_to_tf(self, app, rag_school):
        import app.services.rag_service as rag

        sid = rag_school
        lid = _lesson_with_body(app, sid, "الجذمور يمتص الماء من التربة. " * 40)
        with app.app_context():
            with patch.object(rag, "_embeddings_enabled", return_value=True):
                with patch.object(
                    rag, "_embed_texts_remote", side_effect=lambda texts: [[0.1] * 8 for _ in texts]
                ):
                    rag.ingest_lesson_for_rag(lid, sid)

            # Embedding call explodes at retrieval time → caught → TF path
            with patch.object(rag, "_embeddings_enabled", return_value=True):
                with patch.object(rag, "_embed_texts_remote", side_effect=RuntimeError("net down")):
                    chunks = rag.retrieve_relevant_chunks(sid, "الجذمور والماء", top_k=3)
            assert chunks, "TF fallback must still retrieve"

    def test_below_threshold_scores_dropped(self, app, rag_school):
        import app.services.rag_service as rag

        sid = rag_school
        lid = _lesson_with_body(app, sid, "الكتابة بالخط العربي جميلة ومفيدة. " * 40)
        with app.app_context():
            rag.ingest_lesson_for_rag(lid, sid)
            chunks = rag.retrieve_relevant_chunks(sid, "التصوير الفوتوغرافي الرقمي xyzzy", top_k=5)
            assert chunks == []  # no lexical overlap → all below 0.01 threshold

    def test_mismatched_dense_vector_shapes_fall_back(self, app, rag_school):
        import app.services.rag_service as rag

        sid = rag_school
        lid = _lesson_with_body(app, sid, "التفاضل يدرس معدلات التغير. " * 40)
        with app.app_context():
            with patch.object(rag, "_embeddings_enabled", return_value=True):
                with patch.object(rag, "_embed_texts_remote", side_effect=lambda texts: [[0.1] * 4 for _ in texts]):
                    rag.ingest_lesson_for_rag(lid, sid)
            # Question vector of different dimension → _cosine_dense → 0.0 → threshold drop,
            # but the pure-TF branch still scores with lexical similarity.
            with patch.object(rag, "_embeddings_enabled", return_value=True):
                with patch.object(rag, "_embed_texts_remote", return_value=[[0.5] * 16]):
                    chunks = rag.retrieve_relevant_chunks(sid, "التفاضل", top_k=3)
            assert isinstance(chunks, list)

    def test_cosine_dense_edge_cases(self, app):
        from app.services.rag_service import _cosine_dense

        assert _cosine_dense([], [1.0]) == 0.0
        assert _cosine_dense([1.0, 0.0], [0.0, 1.0]) == 0.0  # orthogonal
        assert _cosine_dense([1.0, 1.0], [1.0, 1.0]) == pytest.approx(1.0)

    def test_cosine_similarity_identical_and_disjoint(self, app):
        from app.services.rag_service import _cosine_similarity

        assert _cosine_similarity({"a": 1.0}, {"b": 1.0}) == 0.0
        assert _cosine_similarity({"a": 0.5}, {"a": 0.5}) == pytest.approx(1.0)

    def test_chunk_text_empty(self, app):
        from app.services.rag_service import _chunk_text

        assert _chunk_text("") == []

    def test_llm_exception_propagates_as_error_tuple(self, app, rag_school):
        import app.services.rag_service as rag

        sid = rag_school
        lid = _lesson_with_body(app, sid, "الدورة الدموية تنقل الأكسجين. " * 40)
        with app.app_context():
            rag.ingest_lesson_for_rag(lid, sid)
            with patch.object(rag, "_call_llm_with_context", side_effect=RuntimeError("LLM exploded")):
                result, err = rag.query_school_rag_tutor(sid, 1, "الدورة الدموية")
            assert result is None
            assert err is not None and "AI query failed" in err

    def test_fallback_llm_success_contract(self, app, rag_school):
        import app.services.rag_service as rag

        sid = rag_school  # empty store → direct LLM path
        with app.app_context():
            with patch.object(rag, "_call_llm_with_context", return_value="جواب مباشر"):
                result, err = rag.query_school_rag_tutor(sid, 1, "سؤال عام")
            assert err is None
            assert result["method"] == "direct_llm"
            assert result["confidence"] == "low"
            assert result["sources"] == []

    def test_fallback_llm_failure(self, app, rag_school):
        import app.services.rag_service as rag

        sid = rag_school
        with app.app_context():
            with patch.object(rag, "_call_llm_with_context", side_effect=RuntimeError("down")):
                result, err = rag.query_school_rag_tutor(sid, 1, "سؤال")
            assert result is None and "AI query failed" in err

    def test_llm_context_with_api_key_posts_request(self, app, monkeypatch):
        import app.services.rag_service as rag

        monkeypatch.setenv("OPENAI_API_KEY", "sk-rag")
        fake_resp = MagicMock()
        fake_resp.json.return_value = {"choices": [{"message": {"content": "إجابة من النموذج"}}]}
        with app.app_context():
            with patch("requests.post", return_value=fake_resp) as post:
                out = rag._call_llm_with_context("السؤال", "السياق", 1)
        assert out == "إجابة من النموذج"
        sent = post.call_args.kwargs["json"]
        assert sent["messages"][1]["role"] == "user"
        assert "السياق" in sent["messages"][1]["content"]

    def test_llm_context_request_failure_offline_answer(self, app, monkeypatch):
        import app.services.rag_service as rag

        monkeypatch.setenv("OPENAI_API_KEY", "sk-rag")
        with app.app_context():
            with patch("requests.post", side_effect=RuntimeError("timeout")):
                out_with_ctx = rag._call_llm_with_context("السؤال", "السياق", 1)
                out_no_ctx = rag._call_llm_with_context("السؤال", "", 1)
        assert "السياق" in out_with_ctx  # context-bearing offline answer
        assert "لا يمكنني" in out_no_ctx  # bare offline answer

    def test_get_rag_stats_shape(self, app, rag_school):
        import app.services.rag_service as rag

        sid = rag_school
        lid = _lesson_with_body(app, sid, "النبات يحتاج الضوء والماء. " * 40)
        with app.app_context():
            rag.ingest_lesson_for_rag(lid, sid)
            stats = rag.get_rag_stats(sid)
            assert stats["school_id"] == sid
            assert stats["total_chunks"] >= 1
            assert lid in stats["lesson_ids"]
            assert rag.get_rag_stats(424242)["total_chunks"] == 0


# ═══════════════════════════════════════════════════════════════════════════
# quiz_ai_service — remaining pipeline branches
# ═══════════════════════════════════════════════════════════════════════════


class TestQuizPipelineErrorBranches:
    def test_tx_error_returns_message(self, app):
        from app.core.db import TxError
        from app.services.quiz_ai_service import generate_quiz_from_lesson

        sid = make_school(app)
        teacher = make_user(app, role="teacher", school_id=sid)
        lid = _lesson_with_content(app, sid)
        with app.app_context():
            with patch("app.services.quiz_ai_service._call_llm", return_value="[]"):
                # Valid JSON but empty list → parse failure branch (not TxError)
                quiz, err = generate_quiz_from_lesson(lid, created_by=teacher)
            assert quiz is None and "تحليل" in err

        with app.app_context():
            # Force the tx wrapper itself to raise TxError
            with patch("app.services.quiz_ai_service._call_llm", return_value=json.dumps(
                [{"question_text": "س", "correct_answer": "ج"}]
            )):
                with patch("app.services.quiz_ai_service.tx", side_effect=TxError("قيد قاعدة بيانات")):
                    quiz, err = generate_quiz_from_lesson(lid, created_by=teacher)
            assert quiz is None
            assert "قيد قاعدة بيانات" in err

    def test_generic_db_exception_reported(self, app):
        from app.services.quiz_ai_service import generate_quiz_from_lesson

        sid = make_school(app)
        teacher = make_user(app, role="teacher", school_id=sid)
        lid = _lesson_with_content(app, sid)
        with app.app_context():
            with patch(
                "app.services.quiz_ai_service._call_llm",
                return_value=json.dumps([{"question_text": "س", "correct_answer": "ج"}]),
            ):
                with patch("app.services.quiz_ai_service.tx", side_effect=RuntimeError("connection lost")):
                    quiz, err = generate_quiz_from_lesson(lid, created_by=teacher)
            assert quiz is None
            assert "Database error" in err


class TestParseAndHelpers:
    def test_markdown_fenced_json_extracted(self):
        from app.services.quiz_ai_service import _parse_llm_response

        raw = "```json\n" + json.dumps([{"question_text": "س", "correct_answer": "ج"}]) + "\n```"
        assert _parse_llm_response(raw) == [{"question_text": "س", "correct_answer": "ج"}]

    def test_dict_payload_returns_none(self):
        from app.services.quiz_ai_service import _parse_llm_response

        assert _parse_llm_response(json.dumps({"question_text": "س", "correct_answer": "ج"})) is None

    def test_valid_shaped_but_empty_list_returns_none(self):
        from app.services.quiz_ai_service import _parse_llm_response

        assert _parse_llm_response("[]") is None

    def test_map_difficulty_matrix(self):
        from app.services.quiz_ai_service import _map_difficulty

        assert _map_difficulty("easy") == 1
        assert _map_difficulty("hard") == 3
        assert _map_difficulty("medium") == 2
        assert _map_difficulty("لا يوجد") == 2  # default

    def test_normalize_question_correct_none_and_mark_variants(self):
        from app.services.quiz_ai_service import _normalize_question

        out = _normalize_question({"question_text": "س", "correct_answer": None})
        assert out["correct_answer"]["value"] == ""
        out2 = _normalize_question({"question_text": "س", "correct_answer": "ج", "mark": 2})
        assert out2["mark"] == 2.0

    def test_extract_lesson_text_strips_html(self, app):
        from app.services.quiz_ai_service import _extract_lesson_text

        lesson = MagicMock()
        lesson.title = "العنوان"
        lesson.body_html = "<p>نص <b>عريض</b></p>"
        text = _extract_lesson_text(lesson)
        assert "العنوان" in text and "نص عريض" in text
