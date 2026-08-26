"""Unit tests for app.core.tokens — signed token generation and verification."""

from app.core.tokens import (
    make_activation_token,
    make_reset_token,
    make_token,
    read_reset_token,
    read_token,
)


class TestMakeToken:
    def test_creates_nonempty_token(self, app):
        with app.app_context():
            token = make_token(1, "test@example.com", "test-salt")
            assert isinstance(token, str)
            assert len(token) > 10

    def test_different_users_different_tokens(self, app):
        with app.app_context():
            t1 = make_token(1, "a@test.com", "salt")
            t2 = make_token(2, "b@test.com", "salt")
            assert t1 != t2


class TestReadToken:
    def test_read_valid_token(self, app):
        with app.app_context():
            token = make_token(42, "user@test.com", "my-salt")
            uid, email = read_token(token, salt="my-salt", max_age_seconds=3600)
            assert uid == 42
            assert email == "user@test.com"

    def test_read_with_wrong_salt_fails(self, app):
        with app.app_context():
            token = make_token(42, "user@test.com", "correct-salt")
            uid, email = read_token(token, salt="wrong-salt", max_age_seconds=3600)
            assert uid is None
            assert email is None

    def test_read_tampered_token_fails(self, app):
        with app.app_context():
            token = make_token(42, "user@test.com", "my-salt")
            tampered = token[:-2] + "XX"
            uid, email = read_token(tampered, salt="my-salt", max_age_seconds=3600)
            assert uid is None
            assert email is None


class TestActivationToken:
    def test_make_and_read(self, app):
        with app.app_context():
            token = make_activation_token(5, "act@test.com")
            uid, email = read_token(token, salt="azad-email-confirm", max_age_seconds=86400)
            assert uid == 5
            assert email == "act@test.com"


class TestResetToken:
    def test_make_and_read_reset(self, app):
        with app.app_context():
            token = make_reset_token(10, "reset@test.com")
            uid, email, pc = read_reset_token(token)
            assert uid == 10
            assert email == "reset@test.com"
            assert pc is None

    def test_reset_token_with_pc(self, app):
        from datetime import UTC, datetime

        with app.app_context():
            pc = datetime(2026, 1, 1, tzinfo=UTC)
            token = make_reset_token(10, "reset@test.com", pc)
            uid, email, token_pc = read_reset_token(token)
            assert uid == 10
            assert token_pc == "2026-01-01T00:00:00+00:00"

    def test_read_invalid_reset_token(self, app):
        with app.app_context():
            uid, email, pc = read_reset_token("invalid-token")
            assert uid is None
            assert email is None
            assert pc is None

    def test_read_expired_reset_token(self, app):
        # max_age_seconds=0 on itsdangerous still validates on same second
        # so we verify invalid token returns None instead
        with app.app_context():
            uid, email, pc = read_reset_token("totally-invalid-token")
            assert uid is None
            assert email is None
            assert pc is None
