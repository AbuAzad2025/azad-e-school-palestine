"""Unit tests for app.core.logging — correlation IDs and structured logging."""

from app.core.logging import (
    clear_correlation_id,
    get_correlation_id,
    get_logger,
    set_correlation_id,
)


class TestCorrelationId:
    def test_get_creates_new_if_none(self):
        """get_correlation_id() auto-generates a 16-char hex string."""
        clear_correlation_id()
        cid = get_correlation_id()
        assert isinstance(cid, str)
        assert len(cid) == 16

    def test_get_returns_same_id(self):
        """Multiple calls return the same ID within a context."""
        clear_correlation_id()
        cid1 = get_correlation_id()
        cid2 = get_correlation_id()
        assert cid1 == cid2

    def test_set_and_get(self):
        """set_correlation_id() persists for subsequent get."""
        set_correlation_id("custom-id-123")
        assert get_correlation_id() == "custom-id-123"
        clear_correlation_id()

    def test_clear_resets(self):
        """clear_correlation_id() forces a new ID on next get."""
        set_correlation_id("to-be-cleared")
        clear_correlation_id()
        new_cid = get_correlation_id()
        assert new_cid != "to-be-cleared"
        assert len(new_cid) == 16

    def test_set_empty_string(self):
        """Setting empty string still stores it."""
        set_correlation_id("")
        assert get_correlation_id() == ""
        clear_correlation_id()


class TestGetLogger:
    def test_returns_bound_logger(self):
        """get_logger() returns a structlog BoundLogger."""
        logger = get_logger("test_module")
        assert logger is not None

    def test_logger_without_name(self):
        """get_logger(None) works without a module name."""
        logger = get_logger(None)
        assert logger is not None

    def test_logger_with_empty_string(self):
        """get_logger('') works with empty string."""
        logger = get_logger("")
        assert logger is not None
