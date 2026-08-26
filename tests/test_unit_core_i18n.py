"""Unit tests for app.core.i18n — safe translation wrapper."""

from app.core.i18n import _


class TestUnderscore:
    def test_returns_msgid_without_context(self):
        """Without Flask context, _() returns the original string."""
        result = _("Hello World")
        assert result == "Hello World"

    def test_formats_with_variables(self):
        result = _("Hello %(name)s", name="Ali")
        assert result == "Hello Ali"

    def test_empty_string(self):
        result = _("")
        assert result == ""

    def test_preserves_arabic_text(self):
        result = _("مرحبا بك")
        assert result == "مرحبا بك"

    def test_formats_multiple_variables(self):
        result = _("%(a)s and %(b)s", a="X", b="Y")
        assert result == "X and Y"
