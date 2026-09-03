"""Test suite for Pillars 3, 4, and 5 of Azad E-School v2.0.

Pillar 3: Video Security & DRM (HMAC tokens, access control)
Pillar 4: AI Engine (RAG, Quiz generation)
Pillar 5: Wallet Ledger (double-entry, idempotency, Decimal precision)
"""

from __future__ import annotations

import time
import uuid
from decimal import Decimal

import pytest
from app.extensions import db as _db

# ═══════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════

# Module-level counter for unique subject codes across tests
_subject_counter = 0

# Uses the session-scoped `app` fixture from conftest.py.
# The conftest `_clean_db` autouse fixture handles per-test truncation.
# Do NOT define a local `app` fixture — it would override conftest's and
# calling `_db.drop_all()` would destroy all tables for subsequent tests.


def _make_school(app, name="Test School"):
    """Helper: create a school with default grade and subject.

    Subject codes are made unique globally to avoid UniqueViolation
    on the subjects_code_key constraint (Subject is a shared global table).
    """
    global _subject_counter
    from app.models.school import Grade, School, Subject

    with app.app_context():
        school = School(name_ar=name, settings={})
        _db.session.add(school)
        _db.session.flush()

        grade = Grade(school_id=school.id, grade_level=1)
        _db.session.add(grade)

        # Subject is global — use unique code to avoid constraint violation
        _subject_counter += 1
        subject = Subject(name_ar="Math", code=f"MATH_{_subject_counter}")
        _db.session.add(subject)
        _db.session.commit()
        return school.id


def _make_user(app, role="student", school_id=None):
    """Helper: create a user with a guaranteed-unique email."""
    from app.core.security import hash_password
    from app.models.user import User, UserApprovalStatus, UserRole, UserRoleLink

    unique_suffix = uuid.uuid4().hex[:12]
    with app.app_context():
        user = User(
            email=f"{role}_{unique_suffix}@test.com",
            password_hash=hash_password("TestPass123!"),
            role=UserRole(role),
            name_ar=f"Test {role}",
            approval_status=UserApprovalStatus.approved,
            is_active=True,
            locale="ar",
        )
        _db.session.add(user)
        _db.session.flush()

        if school_id:
            link = UserRoleLink(
                user_id=user.id,
                school_id=school_id,
                role=UserRole(role),
                is_active=True,
            )
            _db.session.add(link)
        _db.session.commit()
        return user.id


# ═══════════════════════════════════════════════════════════════════════
# PILLAR 3: Video Security Tests
# ═══════════════════════════════════════════════════════════════════════


class TestVideoTokenGeneration:
    """Test HMAC stream token generation and verification."""

    def test_generate_token_returns_string(self, app):
        with app.app_context():
            from app.services.video_service import generate_stream_token

            token = generate_stream_token(user_id=1, school_id=1, lesson_id=10)
            assert isinstance(token, str)
            assert len(token) > 10

    def test_verify_valid_token(self, app):
        with app.app_context():
            from app.services.video_service import (
                generate_stream_token,
                verify_stream_token,
            )

            token = generate_stream_token(user_id=42, school_id=5, lesson_id=20)
            valid, error = verify_stream_token(token, user_id=42, school_id=5, lesson_id=20)
            assert valid is True
            assert error is None

    def test_verify_wrong_user_fails(self, app):
        with app.app_context():
            from app.services.video_service import (
                generate_stream_token,
                verify_stream_token,
            )

            token = generate_stream_token(user_id=42, school_id=5, lesson_id=20)
            valid, error = verify_stream_token(token, user_id=99, school_id=5, lesson_id=20)
            assert valid is False
            assert "user" in error.lower()

    def test_verify_wrong_school_fails(self, app):
        with app.app_context():
            from app.services.video_service import (
                generate_stream_token,
                verify_stream_token,
            )

            token = generate_stream_token(user_id=42, school_id=5, lesson_id=20)
            valid, error = verify_stream_token(token, user_id=42, school_id=99, lesson_id=20)
            assert valid is False
            assert "school" in error.lower()

    def test_verify_wrong_lesson_fails(self, app):
        with app.app_context():
            from app.services.video_service import (
                generate_stream_token,
                verify_stream_token,
            )

            token = generate_stream_token(user_id=42, school_id=5, lesson_id=20)
            valid, error = verify_stream_token(token, user_id=42, school_id=5, lesson_id=99)
            assert valid is False
            assert "lesson" in error.lower()

    def test_expired_token_fails(self, app):
        with app.app_context():
            from app.services.video_service import (
                generate_stream_token,
                verify_stream_token,
            )

            # Generate token with 0 second expiry (already expired)
            token = generate_stream_token(user_id=42, school_id=5, lesson_id=20, expires_in=0)
            time.sleep(0.1)
            valid, error = verify_stream_token(token, user_id=42, school_id=5, lesson_id=20)
            assert valid is False
            assert "expired" in error.lower()

    def test_tampered_token_fails(self, app):
        with app.app_context():
            from base64 import urlsafe_b64decode, urlsafe_b64encode

            from app.services.video_service import (
                generate_stream_token,
                verify_stream_token,
            )

            token = generate_stream_token(user_id=42, school_id=5, lesson_id=20)
            # Decode, modify the payload (change user_id), re-encode.
            # The HMAC signature will no longer match.
            token_data = urlsafe_b64decode(token.encode()).decode()
            # Original: "user_id:school_id:lesson_id:expires_at:signature"
            parts = token_data.split(":")
            parts[0] = "999"  # tamper with user_id
            tampered = urlsafe_b64encode(":".join(parts).encode()).decode()
            valid, error = verify_stream_token(tampered, user_id=42, school_id=5, lesson_id=20)
            assert valid is False

    def test_invalid_format_fails(self, app):
        with app.app_context():
            from app.services.video_service import verify_stream_token

            valid, error = verify_stream_token("not-a-valid-token", 1, 1, 1)
            assert valid is False


class TestVideoAccessValidation:
    """Test lesson access validation with tenancy."""

    def test_lesson_not_found(self, app):
        with app.app_context():
            from app.services.video_service import validate_lesson_access

            allowed, error = validate_lesson_access(user_id=1, school_id=1, lesson_id=999)
            assert allowed is False
            assert "not found" in error.lower()

    def test_cross_school_access_denied(self, app):
        school1 = _make_school(app, "School 1")
        school2 = _make_school(app, "School 2")
        user = _make_user(app, role="student", school_id=school1)

        with app.app_context():
            from app.models.class_room import ClassMember, ClassRoom
            from app.models.content import Lesson

            # Create class in school1
            cls = ClassRoom(
                school_id=school1,
                subject_id=1,
                grade_id=1,
                join_code=f"CLS_{uuid.uuid4().hex[:6]}",
            )
            _db.session.add(cls)
            _db.session.flush()

            # Add user as class member so access is granted
            member = ClassMember(class_id=cls.id, user_id=user, status="active")
            _db.session.add(member)

            # Create lesson in school1's class
            lesson = Lesson(class_id=cls.id, title="Test", status="published")
            _db.session.add(lesson)
            _db.session.commit()

            # User from school1 tries to access — should work
            from app.services.video_service import validate_lesson_access

            allowed, _ = validate_lesson_access(user, school1, lesson.id)
            assert allowed is True

            # Cross-school access should fail
            allowed, error = validate_lesson_access(user, school2, lesson.id)
            assert allowed is False
            assert "different school" in error.lower()


# ═══════════════════════════════════════════════════════════════════════
# PILLAR 4: AI Engine Tests
# ═══════════════════════════════════════════════════════════════════════


class TestRAGService:
    """Test RAG ingestion and retrieval."""

    def test_chunk_text(self, app):
        with app.app_context():
            from app.services.rag_service import _chunk_text

            text = "A" * 1000
            chunks = _chunk_text(text, chunk_size=200, overlap=20)
            assert len(chunks) > 1
            assert all(len(c) <= 220 for c in chunks)

    def test_cosine_similarity_identical(self, app):
        with app.app_context():
            from app.services.rag_service import (
                _compute_tf,
                _cosine_similarity,
                _tokenize,
            )

            tokens = _tokenize("hello world hello world")
            tf = _compute_tf(tokens)
            sim = _cosine_similarity(tf, tf)
            assert sim == pytest.approx(1.0, abs=0.01)

    def test_cosine_similarity_different(self, app):
        with app.app_context():
            from app.services.rag_service import (
                _compute_tf,
                _cosine_similarity,
                _tokenize,
            )

            tf_a = _compute_tf(_tokenize("photosynthesis plant sunlight"))
            tf_b = _compute_tf(_tokenize("algebra equation mathematics"))
            sim = _cosine_similarity(tf_a, tf_b)
            assert sim < 0.3

    def test_ingest_and_retrieve(self, app):
        school_id = _make_school(app)
        _make_user(app, role="teacher", school_id=school_id)

        with app.app_context():
            from app.models.class_room import ClassRoom
            from app.models.content import Lesson

            cls = ClassRoom(
                school_id=school_id,
                subject_id=1,
                grade_id=1,
                join_code=f"RAG_{uuid.uuid4().hex[:6]}",
            )
            _db.session.add(cls)
            _db.session.flush()

            lesson = Lesson(
                class_id=cls.id,
                title="Photosynthesis",
                body_html="<p>Photosynthesis converts sunlight into energy in plants.</p>",
                status="published",
            )
            _db.session.add(lesson)
            _db.session.commit()
            lesson_id = lesson.id

            from app.services.rag_service import (
                ingest_lesson_for_rag,
                retrieve_relevant_chunks,
            )

            count, error = ingest_lesson_for_rag(lesson_id, school_id)
            assert error is None
            assert count > 0

            chunks = retrieve_relevant_chunks(school_id, "What is photosynthesis?")
            assert len(chunks) > 0
            assert any("photosynthesis" in c.text.lower() for c in chunks)

    def test_tenant_isolation_rag(self, app):
        school1 = _make_school(app, "School A")
        school2 = _make_school(app, "School B")

        with app.app_context():
            from app.models.class_room import ClassRoom
            from app.models.content import Lesson

            # Ingest into school1 only
            cls = ClassRoom(
                school_id=school1,
                subject_id=1,
                grade_id=1,
                join_code=f"ISO_{uuid.uuid4().hex[:6]}",
            )
            _db.session.add(cls)
            _db.session.flush()
            lesson = Lesson(
                class_id=cls.id,
                title="Secret Content",
                body_html="<p>Top secret school A material.</p>",
                status="published",
            )
            _db.session.add(lesson)
            _db.session.commit()

            from app.services.rag_service import (
                ingest_lesson_for_rag,
                retrieve_relevant_chunks,
            )

            ingest_lesson_for_rag(lesson.id, school1)

            # School1 can find it
            chunks1 = retrieve_relevant_chunks(school1, "secret material")
            assert len(chunks1) > 0

            # School2 cannot find it (RLS equivalent at app level)
            chunks2 = retrieve_relevant_chunks(school2, "secret material")
            assert len(chunks2) == 0


class TestQuizAIGenerator:
    """Test AI quiz generation parsing."""

    def test_parse_valid_json(self, app):
        with app.app_context():
            from app.services.quiz_ai_service import _parse_llm_response

            response = """
            [
                {"question_text": "What is 2+2?", "question_type": "mcq",
                 "options": ["3", "4", "5", "6"], "correct_answer": "4",
                 "marks": 1, "explanation": "Basic math"},
                {"question_text": "The sky is blue.", "question_type": "true_false",
                 "options": ["True", "False"], "correct_answer": "True",
                 "marks": 1, "explanation": "Observable fact"}
            ]
            """
            result = _parse_llm_response(response)
            assert result is not None
            assert len(result) == 2
            assert result[0]["question_text"] == "What is 2+2?"

    def test_parse_with_markdown_fences(self, app):
        with app.app_context():
            from app.services.quiz_ai_service import _parse_llm_response

            response = (
                "```json\n"
                '[{"question_text": "Test?", "correct_answer": "Yes", '
                '"question_type": "mcq", "options": ["Yes", "No"], '
                '"marks": 1}]\n'
                "```"
            )
            result = _parse_llm_response(response)
            assert result is not None
            assert len(result) == 1

    def test_parse_invalid_json(self, app):
        with app.app_context():
            from app.services.quiz_ai_service import _parse_llm_response

            result = _parse_llm_response("This is not JSON at all.")
            assert result is None

    def test_generate_offline_quiz(self, app):
        with app.app_context():
            from app.services.quiz_ai_service import _generate_offline_quiz

            response = _generate_offline_quiz("Generate quiz about math")
            import json

            data = json.loads(response)
            assert isinstance(data, list)
            assert len(data) >= 1
            assert "question_text" in data[0]


# ═══════════════════════════════════════════════════════════════════════
# PILLAR 5: Wallet Ledger Tests
# ═══════════════════════════════════════════════════════════════════════


class TestWalletCreation:
    """Test wallet creation and retrieval."""

    def test_create_wallet(self, app):
        school_id = _make_school(app)
        user_id = _make_user(app, role="student", school_id=school_id)

        with app.app_context():
            from app.services.wallet_service import get_or_create_wallet

            wallet, error = get_or_create_wallet(school_id, user_id)
            assert error is None
            assert wallet is not None
            assert wallet.school_id == school_id
            assert wallet.user_id == user_id
            assert wallet.currency == "ILS"
            assert Decimal(str(wallet.balance)) == Decimal("0.00")

    def test_wallet_idempotent(self, app):
        school_id = _make_school(app)
        user_id = _make_user(app, role="student", school_id=school_id)

        with app.app_context():
            from app.services.wallet_service import get_or_create_wallet

            w1, _ = get_or_create_wallet(school_id, user_id)
            w2, _ = get_or_create_wallet(school_id, user_id)
            assert w1.id == w2.id  # Same wallet returned

    def test_separate_wallets_per_school(self, app):
        school1 = _make_school(app, "School A")
        school2 = _make_school(app, "School B")
        user_id = _make_user(app, role="student", school_id=school1)

        with app.app_context():
            from app.services.wallet_service import get_or_create_wallet

            w1, _ = get_or_create_wallet(school1, user_id)
            w2, _ = get_or_create_wallet(school2, user_id)
            assert w1.id != w2.id  # Different wallets


class TestWalletTransfer:
    """Test double-entry ledger transfers."""

    def test_basic_transfer(self, app):
        school_id = _make_school(app)
        user_a = _make_user(app, role="student", school_id=school_id)
        user_b = _make_user(app, role="student", school_id=school_id)

        with app.app_context():
            from app.services.wallet_service import (
                get_or_create_wallet,
                process_transfer,
            )

            # Create wallets for both users
            wallet_a, _ = get_or_create_wallet(school_id, user_a)
            wallet_b, _ = get_or_create_wallet(school_id, user_b)
            wallet_a.balance = Decimal("1000.00")
            _db.session.commit()

            # Transfer 250.50 from A to B
            tx, error = process_transfer(
                school_id=school_id,
                source_user_id=user_a,
                dest_user_id=user_b,
                amount=Decimal("250.50"),
                idempotency_key=f"tx-test-{uuid.uuid4().hex[:8]}",
                description="Test transfer",
            )
            assert error is None
            assert tx is not None
            assert Decimal(str(tx.amount)) == Decimal("250.50")

            # Verify balances
            from app.services.wallet_service import get_balance

            balance_a = get_balance(school_id, user_a)
            balance_b = get_balance(school_id, user_b)
            assert balance_a == Decimal("749.50")
            assert balance_b == Decimal("250.50")

    def test_insufficient_balance_fails(self, app):
        school_id = _make_school(app)
        user_a = _make_user(app, role="student", school_id=school_id)
        user_b = _make_user(app, role="student", school_id=school_id)

        with app.app_context():
            from app.services.wallet_service import (
                get_or_create_wallet,
                process_transfer,
            )

            wallet_a, _ = get_or_create_wallet(school_id, user_a)
            wallet_b, _ = get_or_create_wallet(school_id, user_b)
            wallet_a.balance = Decimal("100.00")
            _db.session.commit()

            tx, error = process_transfer(
                school_id=school_id,
                source_user_id=user_a,
                dest_user_id=user_b,
                amount=Decimal("500.00"),
                idempotency_key=f"tx-test-{uuid.uuid4().hex[:8]}",
                description="Should fail",
            )
            assert tx is None
            assert error is not None

    def test_idempotency_prevents_duplicate(self, app):
        school_id = _make_school(app)
        user_a = _make_user(app, role="student", school_id=school_id)
        user_b = _make_user(app, role="student", school_id=school_id)

        with app.app_context():
            from app.services.wallet_service import (
                get_or_create_wallet,
                process_transfer,
            )

            wallet_a, _ = get_or_create_wallet(school_id, user_a)
            wallet_b, _ = get_or_create_wallet(school_id, user_b)
            wallet_a.balance = Decimal("1000.00")
            _db.session.commit()

            idempotency_key = f"idempotent-{uuid.uuid4().hex[:8]}"

            # First transfer
            tx1, _ = process_transfer(
                school_id=school_id,
                source_user_id=user_a,
                dest_user_id=user_b,
                amount=Decimal("100.00"),
                idempotency_key=idempotency_key,
                description="First",
            )

            # Duplicate with same idempotency key
            tx2, _ = process_transfer(
                school_id=school_id,
                source_user_id=user_a,
                dest_user_id=user_b,
                amount=Decimal("100.00"),
                idempotency_key=idempotency_key,
                description="Duplicate",
            )

            assert tx1.id == tx2.id  # Same transaction returned

    def test_self_transfer_fails(self, app):
        school_id = _make_school(app)
        user_a = _make_user(app, role="student", school_id=school_id)

        with app.app_context():
            from app.services.wallet_service import process_transfer

            tx, error = process_transfer(
                school_id=school_id,
                source_user_id=user_a,
                dest_user_id=user_a,
                amount=Decimal("100.00"),
                idempotency_key=f"tx-test-{uuid.uuid4().hex[:8]}",
                description="Self transfer",
            )
            assert tx is None
            assert error is not None
            # Arabic: "same user" — check for the word after التحويل
            assert "نفسه" in error or "المستخدم" in error

    def test_zero_amount_fails(self, app):
        school_id = _make_school(app)
        user_a = _make_user(app, role="student", school_id=school_id)
        user_b = _make_user(app, role="student", school_id=school_id)

        with app.app_context():
            from app.services.wallet_service import process_transfer

            tx, error = process_transfer(
                school_id=school_id,
                source_user_id=user_a,
                dest_user_id=user_b,
                amount=Decimal("0.00"),
                idempotency_key=f"tx-test-{uuid.uuid4().hex[:8]}",
                description="Zero",
            )
            assert tx is None
            assert error is not None


class TestWalletDecimalPrecision:
    """Test Decimal(10,2) precision and ROUND_HALF_UP."""

    def test_money_rounding(self, app):
        with app.app_context():
            from app.services.wallet_service import _money

            # 100.005 should round up to 100.01 (ROUND_HALF_UP)
            assert _money("100.005") == Decimal("100.01")
            # 100.004 should round down to 100.00
            assert _money("100.004") == Decimal("100.00")
            # 100.006 should round up to 100.01
            assert _money("100.006") == Decimal("100.01")
            # Float precision handled correctly via str() conversion
            assert _money(0.1 + 0.2) == Decimal("0.30")

    def test_transfer_with_precise_amounts(self, app):
        school_id = _make_school(app)
        user_a = _make_user(app, role="student", school_id=school_id)
        user_b = _make_user(app, role="student", school_id=school_id)

        with app.app_context():
            from app.services.wallet_service import (
                get_or_create_wallet,
                process_transfer,
            )

            wallet_a, _ = get_or_create_wallet(school_id, user_a)
            wallet_b, _ = get_or_create_wallet(school_id, user_b)
            wallet_a.balance = Decimal("100.00")
            _db.session.commit()

            # Transfer 33.33 (repeating decimal)
            tx, error = process_transfer(
                school_id=school_id,
                source_user_id=user_a,
                dest_user_id=user_b,
                amount=Decimal("33.33"),
                idempotency_key=f"tx-precision-{uuid.uuid4().hex[:8]}",
                description="Precise",
            )
            assert error is None
            assert Decimal(str(tx.amount)) == Decimal("33.33")

            from app.services.wallet_service import get_balance

            balance_a = get_balance(school_id, user_a)
            balance_b = get_balance(school_id, user_b)
            assert balance_a == Decimal("66.67")
            assert balance_b == Decimal("33.33")


class TestWalletTransactionHistory:
    """Test transaction history and summaries."""

    def test_transaction_history(self, app):
        school_id = _make_school(app)
        user_a = _make_user(app, role="student", school_id=school_id)
        user_b = _make_user(app, role="student", school_id=school_id)

        with app.app_context():
            from app.services.wallet_service import (
                get_or_create_wallet,
                get_transaction_history,
                process_transfer,
            )

            wallet_a, _ = get_or_create_wallet(school_id, user_a)
            wallet_b, _ = get_or_create_wallet(school_id, user_b)
            wallet_a.balance = Decimal("500.00")
            _db.session.commit()

            # Make 3 transfers with unique idempotency keys
            for i in range(3):
                process_transfer(
                    school_id=school_id,
                    source_user_id=user_a,
                    dest_user_id=user_b,
                    amount=Decimal("10.00"),
                    idempotency_key=f"tx-history-{uuid.uuid4().hex[:8]}-{i}",
                    description=f"Transfer {i}",
                )

            history = get_transaction_history(school_id, user_a)
            assert len(history) == 3

    def test_wallet_summary(self, app):
        school_id = _make_school(app)
        user_a = _make_user(app, role="student", school_id=school_id)
        user_b = _make_user(app, role="student", school_id=school_id)

        with app.app_context():
            from app.services.wallet_service import (
                get_or_create_wallet,
                get_wallet_summary,
                process_transfer,
            )

            wallet_a, _ = get_or_create_wallet(school_id, user_a)
            wallet_b, _ = get_or_create_wallet(school_id, user_b)
            wallet_a.balance = Decimal("500.00")
            _db.session.commit()

            process_transfer(
                school_id=school_id,
                source_user_id=user_a,
                dest_user_id=user_b,
                amount=Decimal("150.00"),
                idempotency_key=f"tx-summary-{uuid.uuid4().hex[:8]}",
                description="Test",
            )

            summary = get_wallet_summary(school_id, user_a)
            assert summary["balance"] == "350.00"
            assert summary["total_sent"] == "150.00"
            assert summary["transaction_count"] == 1
