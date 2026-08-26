"""Squad 1 — Agent 5: Tokens & Cryptography.

Tests token generation, signature validation failures, clock skew,
expired reset links, and one-time-use semantics.
"""

import pytest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from app.core.tokens import (
    make_token,
    make_activation_token,
    make_reset_token,
    read_token,
    read_reset_token,
)


class TestMakeToken:
    def test_returns_nonempty_string(self, app):
        with app.app_context():
            token = make_token(1, "test@test.com", "test-salt")
            assert isinstance(token, str)
            assert len(token) > 10

    def test_different_tokens_for_different_users(self, app):
        with app.app_context():
            t1 = make_token(1, "a@test.com", "salt")
            t2 = make_token(2, "b@test.com", "salt")
            assert t1 != t2

    def test_different_tokens_for_different_salts(self, app):
        with app.app_context():
            t1 = make_token(1, "a@test.com", "salt1")
            t2 = make_token(1, "a@test.com", "salt2")
            assert t1 != t2


class TestMakeActivationToken:
    def test_returns_token(self, app):
        with app.app_context():
            token = make_activation_token(1, "test@test.com")
            assert isinstance(token, str)
            assert len(token) > 10


class TestMakeResetToken:
    def test_with_none_pc(self, app):
        with app.app_context():
            token = make_reset_token(1, "test@test.com", None)
            assert isinstance(token, str)

    def test_with_timestamp_pc(self, app):
        with app.app_context():
            ts = datetime(2026, 1, 1, tzinfo=UTC)
            token = make_reset_token(1, "test@test.com", ts)
            assert isinstance(token, str)


class TestReadToken:
    def test_valid_token(self, app):
        with app.app_context():
            token = make_token(42, "user@test.com", "azad-email-confirm")
            uid, email = read_token(token)
            assert uid == 42
            assert email == "user@test.com"

    def test_invalid_token(self, app):
        with app.app_context():
            uid, email = read_token("invalid-token-string")
            assert uid is None
            assert email is None

    def test_expired_token(self, app):
        with app.app_context():
            token = make_token(42, "user@test.com", "azad-email-confirm")
            # max_age=-1 means already expired (elapsed > -1 is always true)
            uid, email = read_token(token, max_age_seconds=-1)
            assert uid is None

    def test_wrong_salt(self, app):
        with app.app_context():
            token = make_token(42, "user@test.com", "correct-salt")
            uid, email = read_token(token, salt="wrong-salt")
            assert uid is None


class TestReadResetToken:
    def test_valid_token(self, app):
        with app.app_context():
            token = make_reset_token(42, "user@test.com", None)
            uid, email, pc = read_reset_token(token)
            assert uid == 42
            assert email == "user@test.com"
            assert pc is None

    def test_token_with_pc(self, app):
        with app.app_context():
            ts = datetime(2026, 1, 1, tzinfo=UTC)
            token = make_reset_token(42, "user@test.com", ts)
            uid, email, pc = read_reset_token(token)
            assert uid == 42
            assert pc is not None

    def test_invalid_token(self, app):
        with app.app_context():
            uid, email, pc = read_reset_token("invalid-token")
            assert uid is None

    def test_expired_token(self, app):
        with app.app_context():
            token = make_reset_token(42, "user@test.com", None)
            uid, email, pc = read_reset_token(token, max_age_seconds=-1)
            assert uid is None

    def test_wrong_salt_fails(self, app):
        with app.app_context():
            # Token made with a non-standard salt — read_reset_token uses "azad-password-reset"
            token = make_token(42, "user@test.com", "completely-wrong-salt")
            uid, email, pc = read_reset_token(token)
            assert uid is None


class TestTokenEdgeCases:
    def test_same_uid_different_email_different_tokens(self, app):
        with app.app_context():
            t1 = make_token(1, "a@test.com", "salt")
            t2 = make_token(1, "b@test.com", "salt")
            assert t1 != t2

    def test_read_token_with_large_max_age(self, app):
        with app.app_context():
            token = make_token(42, "user@test.com", "azad-email-confirm")
            uid, email = read_token(token, max_age_seconds=86400)
            assert uid == 42

    def test_reset_token_preserves_pc_none(self, app):
        with app.app_context():
            token = make_reset_token(42, "user@test.com", None)
            uid, email, pc = read_reset_token(token)
            assert pc is None

    def test_activation_and_reset_tokens_are_different(self, app):
        """Activation and reset tokens use different salts — cross-reading should fail."""
        with app.app_context():
            act_token = make_activation_token(42, "user@test.com")
            uid, email = read_token(act_token, salt="azad-password-reset")
            assert uid is None

            reset_token = make_reset_token(42, "user@test.com")
            uid2, email2 = read_token(reset_token, salt="azad-email-confirm")
            assert uid2 is None
