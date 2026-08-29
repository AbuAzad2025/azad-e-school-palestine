"""Unit tests for app.core.security — password hashing, policy, and reuse checks."""

from app.core.security import (
    COMMON_PASSWORDS,
    check_password_reuse,
    hash_password,
    validate_password_policy,
    verify_password,
)


class TestHashPassword:
    def test_hash_returns_string(self):
        h = hash_password("StrongP@ss1")
        assert isinstance(h, str)

    def test_hash_is_not_plaintext(self):
        h = hash_password("StrongP@ss1")
        assert h != "StrongP@ss1"
        assert len(h) > 20

    def test_same_password_different_hashes(self):
        h1 = hash_password("StrongP@ss1")
        h2 = hash_password("StrongP@ss1")
        # Argon2 produces unique hashes due to random salt
        assert h1 != h2


class TestVerifyPassword:
    def test_verify_correct_password(self):
        h = hash_password("StrongP@ss1")
        assert verify_password(h, "StrongP@ss1") is True

    def test_verify_wrong_password(self):
        h = hash_password("StrongP@ss1")
        assert verify_password(h, "WrongP@ss1") is False

    def test_verify_invalid_hash(self):
        assert verify_password("not-a-hash", "anything") is False

    def test_verify_empty_password(self):
        h = hash_password("StrongP@ss1")
        assert verify_password(h, "") is False


class TestValidatePasswordPolicy:
    def test_valid_password(self, app):
        with app.app_context():
            ok, msg = validate_password_policy("MyStr0ng!Pass")
            assert ok is True
            assert msg is None

    def test_too_short(self, app):
        with app.app_context():
            ok, msg = validate_password_policy("Ab1!")
            assert ok is False
            assert "10" in msg

    def test_no_uppercase(self, app):
        with app.app_context():
            ok, msg = validate_password_policy("mystr0ng!pass")
            assert ok is False
            assert "كبير" in msg

    def test_no_lowercase(self, app):
        with app.app_context():
            ok, msg = validate_password_policy("MYSTR0NG!PASS")
            assert ok is False
            assert "صغير" in msg

    def test_no_digit(self, app):
        with app.app_context():
            ok, msg = validate_password_policy("MyStrong!Pass")
            assert ok is False
            assert "رقم" in msg

    def test_no_special_char(self, app):
        with app.app_context():
            ok, msg = validate_password_policy("MyStr0ngPass")
            assert ok is False
            assert "رمز" in msg

    def test_common_password_rejected(self, app):
        # Common passwords fail uppercase check before reaching the common check,
        # so we verify the set exists and the function catches them at policy level
        with app.app_context():
            for pw in ["password", "123456", "qwerty"]:
                ok, _ = validate_password_policy(pw)
                assert ok is False

    def test_another_common_password(self, app):
        assert "password" in COMMON_PASSWORDS
        assert "123456" in COMMON_PASSWORDS

    def test_custom_policy_min_length(self, app):
        with app.app_context():
            app.config["PASSWORD_MIN_LENGTH"] = 5
            ok, msg = validate_password_policy("Ab1!x")
            assert ok is True

    def test_custom_policy_no_upper(self, app):
        with app.app_context():
            app.config["PASSWORD_REQUIRE_UPPER"] = False
            ok, msg = validate_password_policy("mystr0ng!pass")
            assert ok is True


class TestCheckPasswordReuse:
    def test_no_history(self):
        class FakeUser:
            password_history = []

        new_hash = hash_password("NewP@ss1")
        ok, msg = check_password_reuse(FakeUser(), new_hash)
        assert ok is True
        assert msg is None

    def test_reuse_detected(self):
        h = hash_password("SameP@ss1")

        class FakeUser:
            password_history = [h]

        ok, msg = check_password_reuse(FakeUser(), h)
        assert ok is False
        assert "سابقة" in msg

    def test_different_password_not_reuse(self):
        h1 = hash_password("OldP@ss1")
        h2 = hash_password("NewP@ss1")

        class FakeUser:
            password_history = [h1]

        ok, msg = check_password_reuse(FakeUser(), h2)
        assert ok is True

    def test_none_history(self):
        """User with None password_history should not crash."""
        class FakeUser:
            password_history = None

        new_hash = hash_password("NewP@ss1")
        ok, msg = check_password_reuse(FakeUser(), new_hash)
        assert ok is True


class TestValidatePasswordPolicyEdgeCases:
    def test_custom_min_length_boundary(self, app):
        with app.app_context():
            app.config["PASSWORD_MIN_LENGTH"] = 3
            ok, _ = validate_password_policy("Ab1!")
            assert ok is True

    def test_disable_all_requirements(self, app):
        with app.app_context():
            app.config["PASSWORD_REQUIRE_UPPER"] = False
            app.config["PASSWORD_REQUIRE_LOWER"] = False
            app.config["PASSWORD_REQUIRE_DIGIT"] = False
            app.config["PASSWORD_REQUIRE_SPECIAL"] = False
            app.config["PASSWORD_MIN_LENGTH"] = 1
            ok, _ = validate_password_policy("a")
            assert ok is True

    def test_exact_min_length(self, app):
        with app.app_context():
            app.config["PASSWORD_MIN_LENGTH"] = 8
            ok, _ = validate_password_policy("Ab1!Ab1!")
            assert ok is True
            ok, _ = validate_password_policy("Ab1!Ab1")
            assert ok is False

    def test_all_common_passwords_rejected(self, app):
        """Every password in COMMON_PASSWORDS should fail policy checks."""
        with app.app_context():
            for pw in COMMON_PASSWORDS:
                # Common passwords lack uppercase/digit/special, so they fail
                ok, _ = validate_password_policy(pw)
                assert ok is False, f"'{pw}' should be rejected"

    def test_very_long_password_accepted(self, app):
        with app.app_context():
            long_pw = "A" + "1" + "!" + "a" * 200
            ok, _ = validate_password_policy(long_pw)
            assert ok is True
