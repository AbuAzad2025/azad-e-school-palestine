"""Critical frontend tests — Phase 1 blockers"""
import pytest
from bs4 import BeautifulSoup


class TestNestedMain:
    """Test that no template has nested <main> elements."""

    def test_admin_base_no_nested_main(self):
        import os
        path = os.path.join(
            os.path.dirname(__file__), "..", "app", "templates", "admin", "base.html"
        )
        with open(path, encoding="utf-8") as f:
            content = f.read()

        soup = BeautifulSoup(content, "html.parser")
        mains = soup.find_all("main")
        # Should have NO <main> in admin/base.html (it extends base.html which has one)
        assert len(mains) == 0, f"admin/base.html has {len(mains)} <main> elements, should have 0"

    def test_ai_chat_no_nested_main(self):
        import os
        path = os.path.join(
            os.path.dirname(__file__), "..", "app", "templates", "ai", "chat.html"
        )
        with open(path, encoding="utf-8") as f:
            content = f.read()

        soup = BeautifulSoup(content, "html.parser")
        mains = soup.find_all("main")
        assert len(mains) == 0, f"ai/chat.html has {len(mains)} <main> elements, should have 0"


class TestSearchInputLabel:
    """Test that search inputs have proper labels."""

    def test_search_macro_has_aria_label(self):
        import os
        path = os.path.join(
            os.path.dirname(__file__), "..", "app", "templates", "macros", "forms.html"
        )
        with open(path, encoding="utf-8") as f:
            content = f.read()

        assert 'id="{{ name }}-search"' in content, "Search input must have id"
        assert 'aria-label' in content or 'label for=' in content, "Search input must have label or aria-label"


class TestAiChatNoInnerHTML:
    """Test that AI chat uses textContent not innerHTML for user content."""

    def test_render_messages_uses_textcontent(self):
        import os
        path = os.path.join(
            os.path.dirname(__file__), "..", "app", "static", "js", "ai-chat.js"
        )
        with open(path, encoding="utf-8") as f:
            content = f.read()

        # Should NOT use innerHTML for user-generated content
        assert "innerHTML = " not in content or "innerHTML = html" not in content, \
            "renderMessages should not use innerHTML for message content"

        # Should use textContent or createTextNode
        assert "textContent" in content or "createTextNode" in content or "document.createElement" in content, \
            "Should use safe DOM methods"


class TestFetchErrorHandling:
    """Test that fetch calls have proper error handling."""

    def test_sendmessage_has_abortcontroller(self):
        import os
        path = os.path.join(
            os.path.dirname(__file__), "..", "app", "static", "js", "ai-chat.js"
        )
        with open(path, encoding="utf-8") as f:
            content = f.read()

        assert "AbortController" in content, "sendMessage must use AbortController"
        assert "signal: controller.signal" in content, "fetch must use abort signal"
        assert "setTimeout" in content and "controller.abort" in content, \
            "Must have timeout that aborts controller"

    def test_fetch_has_try_catch(self):
        import os
        path = os.path.join(
            os.path.dirname(__file__), "..", "app", "static", "js", "ai-chat.js"
        )
        with open(path, encoding="utf-8") as f:
            content = f.read()

        assert "try {" in content and "} catch (error)" in content, \
            "fetch must be wrapped in try/catch"
        assert "finally {" in content, "fetch must have finally block"


class TestHeadingHierarchy:
    """Test that heading hierarchy doesn't skip levels."""

    def test_invoice_has_no_skipped_headings(self):
        import os
        path = os.path.join(
            os.path.dirname(__file__), "..", "app", "templates", "billing", "invoice.html"
        )
        with open(path, encoding="utf-8") as f:
            content = f.read()

        soup = BeautifulSoup(content, "html.parser")
        headings = soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"])
        levels = [int(h.name[1]) for h in headings]

        # No skipped levels
        for i in range(1, len(levels)):
            assert levels[i] - levels[i - 1] <= 1, \
                f"Heading level skip: {levels[i-1]} -> {levels[i]}"

    def test_azad_card_macro_has_heading_level_param(self):
        import os
        path = os.path.join(
            os.path.dirname(__file__), "..", "app", "templates", "macros", "ui.html"
        )
        with open(path, encoding="utf-8") as f:
            content = f.read()

        assert "heading_level" in content, "azad_card macro must accept heading_level param"
        assert "h{{ heading_level }}" in content, "Macro must use heading_level for h-tag"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])