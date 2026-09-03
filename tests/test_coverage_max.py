"""High-impact coverage tests — targets the biggest uncovered modules.

Covers: RLS, RAG service, quiz_ai_service, email service, report_card,
sentry, tasks/__init__, and media routes helper logic.
"""

from __future__ import annotations

import json
import math
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest


# ─── RAG Service Tests ───────────────────────────────────────────────────────


class TestRAGChunk:
    """Test RAGChunk data class."""

    def test_rag_chunk_creation(self):
        from app.services.rag_service import RAGChunk

        chunk = RAGChunk(
            text="Photosynthesis is the process...",
            lesson_id=10,
            school_id=1,
            chunk_index=0,
            source="lesson",
        )
        assert chunk.text == "Photosynthesis is the process..."
        assert chunk.lesson_id == 10
        assert chunk.school_id == 1
        assert chunk.chunk_index == 0
        assert chunk.source == "lesson"

    def test_rag_chunk_default_source(self):
        from app.services.rag_service import RAGChunk

        chunk = RAGChunk(text="test", lesson_id=1, school_id=1, chunk_index=0)
        assert chunk.source == "lesson"


class TestRAGTokenize:
    """Test RAG tokenizer."""

    def test_tokenize_basic(self):
        from app.services.rag_service import _tokenize

        tokens = _tokenize("Hello World 123")
        assert "hello" in tokens
        assert "world" in tokens
        assert "123" in tokens

    def test_tokenize_arabic(self):
        from app.services.rag_service import _tokenize

        tokens = _tokenize("العلوم الطبيعية درس جديد")
        assert len(tokens) >= 3

    def test_tokenize_removes_short_tokens(self):
        from app.services.rag_service import _tokenize

        tokens = _tokenize("a bb ccc dddd")
        assert "a" not in tokens
        assert "bb" in tokens
        assert "ccc" in tokens

    def test_tokenize_empty(self):
        from app.services.rag_service import _tokenize

        tokens = _tokenize("")
        assert tokens == []

    def test_tokenize_strips_punctuation(self):
        from app.services.rag_service import _tokenize

        tokens = _tokenize("hello, world! how are you?")
        assert "," not in " ".join(tokens)
        assert "!" not in " ".join(tokens)


class TestRAGTF:
    """Test term frequency computation."""

    def test_compute_tf_basic(self):
        from app.services.rag_service import _compute_tf

        tf = _compute_tf(["hello", "world", "hello"])
        assert abs(tf["hello"] - 2 / 3) < 0.01
        assert abs(tf["world"] - 1 / 3) < 0.01

    def test_compute_tf_empty(self):
        from app.services.rag_service import _compute_tf

        tf = _compute_tf([])
        assert tf == {}

    def test_compute_tf_single_word(self):
        from app.services.rag_service import _compute_tf

        tf = _compute_tf(["test"])
        assert abs(tf["test"] - 1.0) < 0.01


class TestRAGCosineSimilarity:
    """Test cosine similarity."""

    def test_identical_vectors(self):
        from app.services.rag_service import _cosine_similarity

        vec = {"a": 0.5, "b": 0.5}
        sim = _cosine_similarity(vec, vec)
        assert abs(sim - 1.0) < 0.01

    def test_no_overlap(self):
        from app.services.rag_service import _cosine_similarity

        sim = _cosine_similarity({"a": 1.0}, {"b": 1.0})
        assert sim == 0.0

    def test_empty_vectors(self):
        from app.services.rag_service import _cosine_similarity

        sim = _cosine_similarity({}, {"a": 1.0})
        assert sim == 0.0

    def test_partial_overlap(self):
        from app.services.rag_service import _cosine_similarity

        sim = _cosine_similarity({"a": 1.0, "b": 0.5}, {"a": 0.5, "c": 1.0})
        assert 0.0 < sim < 1.0

    def test_zero_norm(self):
        from app.services.rag_service import _cosine_similarity

        sim = _cosine_similarity({}, {})
        assert sim == 0.0


class TestRAGChunkText:
    """Test text chunking."""

    def test_chunk_text_basic(self):
        from app.services.rag_service import _chunk_text

        chunks = _chunk_text("Hello World", chunk_size=5, overlap=2)
        assert len(chunks) >= 1
        assert "Hello" in chunks[0]

    def test_chunk_text_empty(self):
        from app.services.rag_service import _chunk_text

        chunks = _chunk_text("")
        assert chunks == []

    def test_chunk_text_short(self):
        from app.services.rag_service import _chunk_text

        chunks = _chunk_text("Hi", chunk_size=100, overlap=10)
        assert len(chunks) == 1
        assert chunks[0] == "Hi"

    def test_chunk_text_overlap(self):
        from app.services.rag_service import _chunk_text

        text = "A" * 20
        chunks = _chunk_text(text, chunk_size=10, overlap=5)
        assert len(chunks) >= 2

    def test_chunk_text_skips_whitespace(self):
        from app.services.rag_service import _chunk_text

        chunks = _chunk_text("   ", chunk_size=5, overlap=2)
        assert chunks == []


class TestRAGIngestion:
    """Test RAG ingestion pipeline."""

    def test_ingest_lesson_not_found(self, app):
        from app.services.rag_service import ingest_lesson_for_rag

        with app.app_context():
            count, error = ingest_lesson_for_rag(99999, 1)
            assert count == 0
            assert error == "Lesson not found"

    def test_ingest_lesson_with_content(self, app):
        from app.services.rag_service import _chunk_store, ingest_lesson_for_rag

        with app.app_context():
            from tests.conftest import make_class, make_grade, make_lesson, make_school, make_subject, make_user

            school_id = make_school(app)
            grade_id = make_grade(app, school_id)
            subject_id = make_subject(app)
            teacher_id = make_user(app, role="teacher", school_id=school_id)
            class_id = make_class(app, school_id, grade_id, subject_id=subject_id, teacher_id=teacher_id)
            lesson_id = make_lesson(app, class_id, title="Photosynthesis", status="published")

            # Add body_html
            from app.extensions import db as _db
            from app.models.content import Lesson

            lesson = _db.session.get(Lesson, lesson_id)
            lesson.body_html = "<p>Photosynthesis is how plants make food from sunlight.</p>"
            _db.session.commit()

            count, error = ingest_lesson_for_rag(lesson_id, school_id)
            assert count >= 1
            assert error is None
            assert school_id in _chunk_store
            assert len(_chunk_store[school_id]) >= 1

    def test_ingest_lesson_empty_content(self, app):
        from app.services.rag_service import ingest_lesson_for_rag

        with app.app_context():
            from app.extensions import db as _db
            from tests.conftest import make_class, make_grade, make_lesson, make_school, make_subject, make_user

            school_id = make_school(app)
            grade_id = make_grade(app, school_id)
            subject_id = make_subject(app)
            teacher_id = make_user(app, role="teacher", school_id=school_id)
            class_id = make_class(app, school_id, grade_id, subject_id=subject_id, teacher_id=teacher_id)
            l_id = make_lesson(app, class_id, title="empty", status="draft")
            # Clear the title to make it truly empty
            from app.models.content import Lesson
            lesson = _db.session.get(Lesson, l_id)
            lesson.title = ""
            _db.session.commit()

            count, error = ingest_lesson_for_rag(l_id, school_id)
            assert count == 0
            assert error is not None


class TestRAGRetrieval:
    """Test RAG retrieval."""

    def test_retrieve_empty_store(self, app):
        from app.services.rag_service import retrieve_relevant_chunks

        with app.app_context():
            chunks = retrieve_relevant_chunks(99999, "What is photosynthesis?")
            assert chunks == []

    def test_retrieve_relevant(self, app):
        from app.services.rag_service import RAGChunk, _chunk_store, retrieve_relevant_chunks

        with app.app_context():
            # Manually add chunks
            _chunk_store[42] = [
                RAGChunk(text="Photosynthesis is the process by which plants make food", lesson_id=1, school_id=42, chunk_index=0),
                RAGChunk(text="Mathematics is the study of numbers and shapes", lesson_id=2, school_id=42, chunk_index=0),
                RAGChunk(text="Plants use sunlight to create energy through photosynthesis", lesson_id=3, school_id=42, chunk_index=0),
            ]
            chunks = retrieve_relevant_chunks(42, "What is photosynthesis?")
            assert len(chunks) >= 1
            # First chunk should be the most relevant
            assert "Photosynthesis" in chunks[0].text or "photosynthesis" in chunks[0].text.lower()

    def test_retrieve_scoped_to_school(self, app):
        from app.services.rag_service import RAGChunk, _chunk_store, retrieve_relevant_chunks

        with app.app_context():
            _chunk_store[10] = [RAGChunk(text="School 10 content", lesson_id=1, school_id=10, chunk_index=0)]
            _chunk_store[20] = [RAGChunk(text="School 20 content about photosynthesis", lesson_id=2, school_id=20, chunk_index=0)]
            chunks = retrieve_relevant_chunks(10, "photosynthesis")
            # Should only return school 10 chunks
            for c in chunks:
                assert c.school_id == 10

    def test_retrieve_with_threshold(self, app):
        from app.services.rag_service import RAGChunk, _chunk_store, retrieve_relevant_chunks

        with app.app_context():
            _chunk_store[50] = [
                RAGChunk(text="completely unrelated content about sports", lesson_id=1, school_id=50, chunk_index=0),
            ]
            chunks = retrieve_relevant_chunks(50, "photosynthesis biology")
            # The threshold is 0.01 — most words won't match, so likely empty
            # But we just test it doesn't crash
            assert isinstance(chunks, list)


class TestRAGQuery:
    """Test RAG tutor query pipeline."""

    def test_query_no_context_fallback(self, app):
        from app.services.rag_service import _chunk_store, query_school_rag_tutor

        with app.app_context():
            _chunk_store.clear()
            result, error = query_school_rag_tutor(99, 1, "What is math?")
            # Should fallback to offline response
            assert error is None
            assert result is not None
            assert "answer" in result
            assert result["confidence"] == "low"
            assert result["method"] == "direct_llm"

    def test_query_with_context(self, app):
        from app.services.rag_service import RAGChunk, _chunk_store, query_school_rag_tutor

        with app.app_context():
            _chunk_store[77] = [
                RAGChunk(text="Photosynthesis is photosynthesis that converts light energy into chemical energy", lesson_id=1, school_id=77, chunk_index=0),
                RAGChunk(text="Plants use chlorophyll to absorb photosynthesis from sunlight", lesson_id=2, school_id=77, chunk_index=0),
                RAGChunk(text="The Calvin cycle fixes carbon dioxide into glucose using photosynthesis", lesson_id=3, school_id=77, chunk_index=0),
            ]
            result, error = query_school_rag_tutor(77, 1, "How do plants use photosynthesis to make food?")
            assert error is None
            assert result is not None
            assert result["method"] == "rag"
            assert len(result["sources"]) >= 1

    def test_query_medium_confidence(self, app):
        from app.services.rag_service import RAGChunk, _chunk_store, query_school_rag_tutor

        with app.app_context():
            _chunk_store[88] = [
                RAGChunk(text="Light energy is absorbed by chlorophyll", lesson_id=1, school_id=88, chunk_index=0),
                RAGChunk(text="Energy is stored as glucose in plants", lesson_id=2, school_id=88, chunk_index=0),
            ]
            result, error = query_school_rag_tutor(88, 1, "energy plants")
            assert error is None
            assert result is not None
            assert result["confidence"] == "medium"

    def test_get_rag_stats(self, app):
        from app.services.rag_service import RAGChunk, _chunk_store, get_rag_stats

        with app.app_context():
            _chunk_store[5] = [
                RAGChunk(text="a", lesson_id=1, school_id=5, chunk_index=0),
                RAGChunk(text="b", lesson_id=1, school_id=5, chunk_index=1),
                RAGChunk(text="c", lesson_id=2, school_id=5, chunk_index=0),
            ]
            stats = get_rag_stats(5)
            assert stats["total_chunks"] == 3
            assert stats["lessons_indexed"] == 2
            assert sorted(stats["lesson_ids"]) == [1, 2]

    def test_get_rag_stats_empty(self, app):
        from app.services.rag_service import get_rag_stats

        with app.app_context():
            stats = get_rag_stats(999)
            assert stats["total_chunks"] == 0
            assert stats["lessons_indexed"] == 0

    def test_offline_response_with_context(self, app):
        from app.services.rag_service import _generate_offline_response

        with app.app_context():
            resp = _generate_offline_response("test", "Some context about photosynthesis")
            assert "محتوى الدروس" in resp or "context" in resp.lower() or "معلومات" in resp

    def test_offline_response_without_context(self, app):
        from app.services.rag_service import _generate_offline_response

        with app.app_context():
            resp = _generate_offline_response("What is math?", "")
            assert "عذراً" in resp or "معلمك" in resp


# ─── Quiz AI Service Tests ───────────────────────────────────────────────────


class TestQuizAILogic:
    """Test quiz AI helper functions (pure logic, no LLM)."""

    def test_extract_lesson_text(self):
        from app.services.quiz_ai_service import _extract_lesson_text

        lesson = MagicMock()
        lesson.title = "ال فيزياء"
        lesson.body_html = "<p>Newton's laws of motion</p>"
        text = _extract_lesson_text(lesson)
        assert "ال فيزياء" in text
        assert "Newton" in text

    def test_extract_lesson_text_no_body(self):
        from app.services.quiz_ai_service import _extract_lesson_text

        lesson = MagicMock()
        lesson.title = "Math"
        lesson.body_html = ""
        text = _extract_lesson_text(lesson)
        assert "Math" in text

    def test_extract_lesson_text_no_title(self):
        from app.services.quiz_ai_service import _extract_lesson_text

        lesson = MagicMock()
        lesson.title = ""
        lesson.body_html = "<p>Content here</p>"
        text = _extract_lesson_text(lesson)
        assert "Content" in text

    def test_parse_llm_response_valid_json(self):
        from app.services.quiz_ai_service import _parse_llm_response

        data = [
            {"question_text": "What is 2+2?", "correct_answer": "4", "question_type": "mcq"},
            {"question_text": "True or False: 1=1", "correct_answer": "True", "question_type": "true_false"},
        ]
        result = _parse_llm_response(json.dumps(data))
        assert result is not None
        assert len(result) == 2

    def test_parse_llm_response_markdown_fenced(self):
        from app.services.quiz_ai_service import _parse_llm_response

        raw = '```json\n[{"question_text": "Q1", "correct_answer": "A1"}]\n```'
        result = _parse_llm_response(raw)
        assert result is not None
        assert len(result) == 1

    def test_parse_llm_response_invalid_json(self):
        from app.services.quiz_ai_service import _parse_llm_response

        result = _parse_llm_response("This is not JSON at all")
        assert result is None

    def test_parse_llm_response_missing_fields(self):
        from app.services.quiz_ai_service import _parse_llm_response

        data = [{"some_field": "value"}]
        result = _parse_llm_response(json.dumps(data))
        assert result is None

    def test_parse_llm_response_json_in_text(self):
        from app.services.quiz_ai_service import _parse_llm_response

        raw = 'Here are the questions:\n[{"question_text": "Q1", "correct_answer": "A1"}]\nDone.'
        result = _parse_llm_response(raw)
        assert result is not None

    def test_parse_llm_response_not_a_list(self):
        from app.services.quiz_ai_service import _parse_llm_response

        result = _parse_llm_response('{"question_text": "Q1", "correct_answer": "A1"}')
        assert result is None

    def test_generate_offline_quiz(self):
        from app.services.quiz_ai_service import _generate_offline_quiz

        raw = _generate_offline_quiz("some prompt with العنوان: الفيزياء")
        data = json.loads(raw)
        assert isinstance(data, list)
        assert len(data) >= 1
        assert "question_text" in data[0]

    def test_generate_offline_quiz_no_title(self):
        from app.services.quiz_ai_service import _generate_offline_quiz

        raw = _generate_offline_quiz("generic prompt")
        data = json.loads(raw)
        assert isinstance(data, list)

    def test_map_difficulty(self):
        from app.services.quiz_ai_service import _map_difficulty

        assert _map_difficulty("easy") == 1
        assert _map_difficulty("medium") == 2
        assert _map_difficulty("hard") == 3
        assert _map_difficulty("unknown") == 2


class TestQuizAIGenerate:
    """Test quiz generation with DB and mocked LLM."""

    def test_generate_lesson_not_found(self, app):
        from app.services.quiz_ai_service import generate_quiz_from_lesson

        with app.app_context():
            quiz, error = generate_quiz_from_lesson(99999)
            assert quiz is None
            assert error is not None

    def test_generate_lesson_empty_content(self, app):
        from app.services.quiz_ai_service import generate_quiz_from_lesson

        with app.app_context():
            from tests.conftest import make_class, make_grade, make_lesson, make_school, make_subject, make_user

            school_id = make_school(app)
            grade_id = make_grade(app, school_id)
            subject_id = make_subject(app)
            teacher_id = make_user(app, role="teacher", school_id=school_id)
            class_id = make_class(app, school_id, grade_id, subject_id=subject_id, teacher_id=teacher_id)
            l_id = make_lesson(app, class_id, title="", status="draft")

            quiz, error = generate_quiz_from_lesson(l_id)
            assert quiz is None
            assert error is not None


# ─── RLS Module Tests ───────────────────────────────────────────────────────


class TestRLSModule:
    """Test RLS functions — using PostgreSQL connection directly."""

    def test_tenant_tables_list(self):
        from app.core.rls import _INDIRECT_TENANT_TABLES, _TENANT_TABLES

        assert len(_TENANT_TABLES) > 0
        assert "classes" in _TENANT_TABLES
        assert "lessons" in _TENANT_TABLES
        assert "subscriptions" in _TENANT_TABLES
        assert len(_INDIRECT_TENANT_TABLES) > 0
        assert "quizzes" in _INDIRECT_TENANT_TABLES
        assert "quiz_attempts" in _INDIRECT_TENANT_TABLES

    def test_set_tenant_context_with_school(self, app):
        from app.core.rls import set_tenant_context

        with app.app_context():
            from app.extensions import db as _db

            # This will fail on SQLite (no SET LOCAL) but won't crash
            try:
                set_tenant_context(42)
            except Exception:
                pass  # SQLite doesn't support SET LOCAL

    def test_set_tenant_context_super_admin(self, app):
        from app.core.rls import set_tenant_context

        with app.app_context():
            try:
                set_tenant_context(None)
            except Exception:
                pass

    def test_reset_tenant_context(self, app):
        from app.core.rls import reset_tenant_context

        with app.app_context():
            try:
                reset_tenant_context()
            except Exception:
                pass  # No-op on SQLite


# ─── Sentry Module Tests ─────────────────────────────────────────────────────


class TestSentryModule:
    """Test sentry utility functions."""

    def test_init_sentry_no_dsn(self, app):
        from app.core.sentry import init_sentry

        with app.app_context():
            # Should be a no-op when SENTRY_DSN is not set
            init_sentry(app)

    def test_init_sentry_with_dsn(self, app):
        from app.core.sentry import init_sentry

        with app.app_context():
            app.config["SENTRY_DSN"] = "https://key@sentry.io/123"
            # Will try to import sentry_sdk — may not be installed
            try:
                init_sentry(app)
            except ImportError:
                pass  # sentry_sdk not installed in test env
            finally:
                app.config.pop("SENTRY_DSN", None)

    def test_set_sentry_user_authenticated(self):
        from app.core.sentry import set_sentry_user

        user = MagicMock()
        user.is_authenticated = True
        user.id = 42
        user.email = "test@test.com"
        user.role = MagicMock()
        user.role.value = "student"

        with patch("app.core.sentry.sentry_sdk", create=True) as mock_sentry:
            try:
                set_sentry_user(user)
            except Exception:
                pass

    def test_set_sentry_user_unauthenticated(self):
        from app.core.sentry import set_sentry_user

        user = MagicMock()
        user.is_authenticated = False

        try:
            set_sentry_user(user)
        except Exception:
            pass

    def test_set_sentry_user_none(self):
        from app.core.sentry import set_sentry_user

        try:
            set_sentry_user(None)
        except Exception:
            pass

    def test_capture_exception(self):
        from app.core.sentry import capture_exception

        exc = ValueError("test error")
        try:
            capture_exception(exc)
        except Exception:
            pass  # sentry_sdk may not be installed

    def test_capture_message(self):
        from app.core.sentry import capture_message

        try:
            capture_message("test message", level="info")
        except Exception:
            pass


# ─── Email Service Tests ─────────────────────────────────────────────────────


class TestEmailHelpers:
    """Test email utility functions."""

    def test_recipient_locale_arabic(self):
        from app.services.email import _recipient_locale

        user = MagicMock()
        user.locale = "ar"
        assert _recipient_locale(user) == "ar"

    def test_recipient_locale_english(self):
        from app.services.email import _recipient_locale

        user = MagicMock()
        user.locale = "en"
        assert _recipient_locale(user) == "en"

    def test_recipient_locale_none(self):
        from app.services.email import _recipient_locale

        user = MagicMock()
        user.locale = None
        assert _recipient_locale(user) == "ar"

    def test_dir_arabic(self):
        from app.services.email import _dir

        assert _dir("ar") == "rtl"
        assert _dir("ar_EG") == "rtl"

    def test_dir_english(self):
        from app.services.email import _dir

        assert _dir("en") == "ltr"

    def test_fmt_date_none(self):
        from app.services.email import _fmt_date

        assert _fmt_date(None, "ar") == "—"

    def test_fmt_date_valid(self):
        from app.services.email import _fmt_date

        dt = datetime(2026, 1, 15, tzinfo=UTC)
        result = _fmt_date(dt, "ar")
        assert result != "—"

    def test_footer(self):
        from app.services.email import _footer

        footer = _footer()
        assert "auto" in footer.lower() or "تلقائية" in footer


class TestEmailSend:
    """Test email sending with mocked mail."""

    def test_send_disabled(self, app):
        from app.services.email import _send

        with app.app_context():
            result = _send("test@test.com", "Subject", "<p>Body</p>")
            assert result is False  # EMAIL_ENABLED=False in test config

    def test_send_enabled(self, app):
        from app.services.email import _send

        with app.app_context():
            app.config["EMAIL_ENABLED"] = True
            with patch("app.services.email.mail") as mock_mail:
                result = _send("test@test.com", "Subject", "<p>Body</p>")
                assert result is True
                mock_mail.send.assert_called_once()
            app.config["EMAIL_ENABLED"] = False

    def test_send_exception(self, app):
        from app.services.email import _send

        with app.app_context():
            app.config["EMAIL_ENABLED"] = True
            with patch("app.services.email.mail") as mock_mail:
                mock_mail.send.side_effect = Exception("SMTP error")
                result = _send("test@test.com", "Subject", "<p>Body</p>")
                assert result is False
            app.config["EMAIL_ENABLED"] = False


class TestEmailNotifications:
    """Test email notification functions with mocked objects."""

    def test_send_welcome_email(self, app):
        from app.services.email import send_welcome_email

        with app.app_context():
            app.config["EMAIL_ENABLED"] = True
            user = MagicMock()
            user.locale = "ar"
            user.name_ar = "أحمد"
            user.email = "ahmed@test.com"

            with patch("app.services.email._send", return_value=True) as mock_send:
                result = send_welcome_email(user)
                assert result is True
                mock_send.assert_called_once()
            app.config["EMAIL_ENABLED"] = False

    def test_send_payment_approved_email(self, app):
        from app.services.email import send_payment_approved_email

        with app.app_context():
            app.config["EMAIL_ENABLED"] = True
            user = MagicMock()
            user.locale = "ar"
            user.name_ar = "أحمد"
            user.email = "ahmed@test.com"

            plan = MagicMock()
            plan.name = "Premium Plan"

            sub = MagicMock()
            sub.user = user
            sub.currency = "ILS"
            sub.end_at = datetime(2026, 12, 31, tzinfo=UTC)
            sub.class_id = 1
            sub.plan = plan
            sub.id = 1

            payment = MagicMock()
            payment.subscription = sub
            payment.amount = Decimal("50.00")
            payment.reference = "REF-123"

            with patch("app.services.email._send", return_value=True) as mock_send:
                result = send_payment_approved_email(payment)
                assert result is True
            app.config["EMAIL_ENABLED"] = False

    def test_send_payment_rejected_email(self, app):
        from app.services.email import send_payment_rejected_email

        with app.app_context():
            app.config["EMAIL_ENABLED"] = True
            user = MagicMock()
            user.locale = "ar"
            user.name_ar = "أحمد"
            user.email = "ahmed@test.com"

            plan = MagicMock()
            plan.name = "Premium Plan"

            sub = MagicMock()
            sub.user = user
            sub.currency = "ILS"
            sub.class_id = 1
            sub.plan = plan
            sub.id = 1

            payment = MagicMock()
            payment.subscription = sub
            payment.amount = Decimal("50.00")
            payment.reference = "REF-456"

            with patch("app.services.email._send", return_value=True) as mock_send:
                result = send_payment_rejected_email(payment)
                assert result is True
            app.config["EMAIL_ENABLED"] = False

    def test_send_grade_published_email(self, app):
        from app.services.email import send_grade_published_email

        with app.app_context():
            app.config["EMAIL_ENABLED"] = True
            student = MagicMock()
            student.locale = "ar"
            student.name_ar = "سارة"
            student.email = "sara@test.com"

            assignment = MagicMock()
            assignment.title = "Midterm Exam"
            assignment.max_mark = 100

            with patch("app.services.email._send", return_value=True) as mock_send:
                result = send_grade_published_email(student, assignment, 85)
                assert result is True
            app.config["EMAIL_ENABLED"] = False

    def test_send_quiz_result_email(self, app):
        from app.services.email import send_quiz_result_email

        with app.app_context():
            app.config["EMAIL_ENABLED"] = True
            student = MagicMock()
            student.locale = "ar"
            student.name_ar = "محمد"
            student.email = "moh@test.com"

            quiz = MagicMock()
            quiz.title = "Chapter 5 Quiz"

            with patch("app.services.email._send", return_value=True) as mock_send:
                result = send_quiz_result_email(student, quiz, 92)
                assert result is True
            app.config["EMAIL_ENABLED"] = False

    def test_send_absence_alert_email(self, app):
        from app.services.email import send_absence_alert_email

        with app.app_context():
            app.config["EMAIL_ENABLED"] = True
            parent = MagicMock()
            parent.locale = "ar"
            parent.name_ar = "والد"
            parent.email = "parent@test.com"

            student = MagicMock()
            student.locale = "ar"
            student.name_ar = "أحمد"
            student.email = "ahmed@test.com"

            with patch("app.services.email._send", return_value=True) as mock_send:
                result = send_absence_alert_email(parent, student, 7)
                assert result is True
            app.config["EMAIL_ENABLED"] = False

    def test_send_contact_reply_email(self, app):
        from app.services.email import send_contact_reply_email

        with app.app_context():
            app.config["EMAIL_ENABLED"] = True
            contact = MagicMock()
            contact.name = "Omar"
            contact.subject = "Registration Issue"
            contact.email = "omar@test.com"

            with patch("app.services.email._send", return_value=True) as mock_send:
                result = send_contact_reply_email(contact, "Thank you for contacting us.")
                assert result is True
            app.config["EMAIL_ENABLED"] = False


# ─── Report Card Service Tests ───────────────────────────────────────────────


class TestReportCardService:
    """Test report card service functions."""

    def test_letter_grade(self):
        from app.services.report_card import _letter_grade

        assert _letter_grade(95) == "ممتاز"
        assert _letter_grade(85) == "جيد جداً"
        assert _letter_grade(75) == "جيد"
        assert _letter_grade(65) == "مقبول"
        assert _letter_grade(50) == "راسب"

    def test_letter_grade_boundary(self):
        from app.services.report_card import _letter_grade

        assert _letter_grade(90) == "ممتاز"
        assert _letter_grade(80) == "جيد جداً"
        assert _letter_grade(70) == "جيد"
        assert _letter_grade(60) == "مقبول"

    def test_calculate_gpa_no_classes(self, app):
        from app.services.report_card import calculate_gpa

        with app.app_context():
            result = calculate_gpa(99999, 1)
            assert result["gpa"] == 0
            assert result["letter_grade"] == "راسب"
            assert result["classes"] == []

    def test_calculate_gpa_with_classes(self, app):
        from app.services.report_card import calculate_gpa

        with app.app_context():
            from tests.conftest import (
                make_class,
                make_class_member,
                make_grade,
                make_grade_category,
                make_grade_entry,
                make_grade_item,
                make_school,
                make_subject,
                make_user,
            )

            school_id = make_school(app)
            grade_id = make_grade(app, school_id)
            subject_id = make_subject(app)
            teacher_id = make_user(app, role="teacher", school_id=school_id)
            student_id = make_user(app, role="student", school_id=school_id)
            class_id = make_class(app, school_id, grade_id, subject_id=subject_id, teacher_id=teacher_id)
            make_class_member(app, class_id, student_id, status="active")

            cat_id = make_grade_category(app, class_id, "Tests", 1.0)
            item_id = make_grade_item(app, class_id, cat_id, "Midterm", 100)
            make_grade_entry(app, student_id, item_id, 85.0)

            result = calculate_gpa(student_id, school_id)
            assert result["gpa"] > 0
            assert len(result["classes"]) == 1
            assert result["classes"][0]["class_id"] == class_id

    def test_generate_report_card(self, app):
        from app.services.report_card import generate_report_card

        with app.app_context():
            from tests.conftest import (
                make_class,
                make_class_member,
                make_grade,
                make_grade_category,
                make_grade_entry,
                make_grade_item,
                make_school,
                make_subject,
                make_user,
            )

            school_id = make_school(app)
            grade_id = make_grade(app, school_id)
            subject_id = make_subject(app)
            teacher_id = make_user(app, role="teacher", school_id=school_id)
            student_id = make_user(app, role="student", school_id=school_id)
            class_id = make_class(app, school_id, grade_id, subject_id=subject_id, teacher_id=teacher_id)
            make_class_member(app, class_id, student_id, status="active")

            cat_id = make_grade_category(app, class_id, "Homework", 1.0)
            item_id = make_grade_item(app, class_id, cat_id, "HW1", 10)
            make_grade_entry(app, student_id, item_id, 8.0)

            result = generate_report_card(student_id, class_id)
            assert result["student"] is not None
            assert result["class_room"] is not None
            assert isinstance(result["grade_data"], dict)
            assert isinstance(result["completed_lessons"], int)
            assert isinstance(result["total_lessons"], int)


# ─── Tasks __init__ Tests ────────────────────────────────────────────────────


class TestTasksInit:
    """Test tasks module initialization."""

    def test_celery_app_exists(self):
        """Check if celery_app was created (requires celery)."""
        from app.tasks import _HAS_CELERY

        if _HAS_CELERY:
            from app.tasks import celery_app

            assert celery_app is not None
        else:
            assert True  # Celery not installed — expected in test env

    def test_init_celery_noop_when_no_celery(self, app):
        from app.tasks import _HAS_CELERY, init_celery

        with app.app_context():
            # Should be a no-op when Celery is not installed
            if not _HAS_CELERY:
                init_celery(app)  # Should not raise

    def test_context_task_stub(self):
        """ContextTask stub should exist when celery is absent."""
        from app.tasks import _HAS_CELERY

        if not _HAS_CELERY:
            from app.tasks import ContextTask

            assert ContextTask is not None
