"""SQUAD 1 EXTRA: Tests for i18n module and expanded uploads."""

import pytest
from app.core.i18n import _


class TestI18n:
    def test_underscore_returns_string(self):
        result = _("Hello")
        assert isinstance(result, str)

    def test_underscore_with_variables(self):
        result = _("Hello %(name)s", name="World")
        assert "World" in result

    def test_underscore_arabic(self):
        result = _("مرحباً")
        assert isinstance(result, str)

    def test_underscore_empty(self):
        result = _("")
        assert result == ""

    def test_underscore_fallback_outside_context(self):
        """Outside Flask request context, _() should still work via RuntimeError handler."""
        result = _("Some text")
        assert isinstance(result, str)
