"""JavaScript modernization tests — Phase 4.

These asserted an ``app/static/js/modules/`` layout that no longer exists, and
skipped themselves out of the way when it was missing — which is why CI also
deselected the file. The modules live at ``js/core/``, ``js/components/`` and
``js/pages/`` now, so the checks below are pointed at the real tree and the
deselect is gone: a frontend guard that never runs is not a guard.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
JS_DIR = BASE_DIR / "app" / "static" / "js"
CORE_DIR = JS_DIR / "core"
COMPONENTS_DIR = JS_DIR / "components"
PAGES_DIR = JS_DIR / "pages"
STATIC_DIR = BASE_DIR / "app" / "static"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestModulesExist:
    """Core ES modules are present."""

    def test_entry_module_exists(self):
        assert (JS_DIR / "index.js").exists(), "Missing app/static/js/index.js entry module"

    @pytest.mark.parametrize(
        "rel",
        ["core/api.js", "core/theme.js", "components/ui.js", "components/toast.js", "components/forms.js"],
    )
    def test_module_exists(self, rel):
        assert (JS_DIR / rel).exists(), f"Missing app/static/js/{rel}"


class TestApiModule:
    """API module has modern fetch wrapper with CSRF, timeout, and error handling."""

    def test_api_uses_fetch_with_abortcontroller(self):
        content = _read(CORE_DIR / "api.js")
        assert "AbortController" in content
        assert "fetch(" in content

    def test_api_injects_csrf_token(self):
        content = _read(CORE_DIR / "api.js")
        assert "X-CSRFToken" in content
        assert "csrf-token" in content or "csrf_token" in content

    def test_api_has_timeout_handling(self):
        content = _read(CORE_DIR / "api.js")
        assert "setTimeout" in content
        assert "controller.abort" in content

    def test_api_exports_http_verbs(self):
        content = _read(CORE_DIR / "api.js")
        for verb in ("export const get", "export const post", "export const put", "export const del"):
            assert verb in content, f"Missing {verb}"


class TestUiModule:
    """UI module uses event delegation."""

    def test_ui_module_has_delegate_helper(self):
        content = _read(COMPONENTS_DIR / "ui.js")
        assert "export function delegate" in content
        assert "closest(selector)" in content

    def test_ui_uses_delegation_for_common_patterns(self):
        content = _read(COMPONENTS_DIR / "ui.js")
        assert "document.body.addEventListener" in content or "delegate(document.body" in content


class TestBaseTemplateUsesModule:
    """base.html loads JS as an ES module."""

    def test_base_uses_module_script(self):
        base = _read(BASE_DIR / "app" / "templates" / "base.html")
        assert 'type="module"' in base
        assert "js/index.js" in base


class TestNoRuntimeStyleInjection:
    """Reveal state lives in the stylesheet, not in a <style> built at runtime.

    index.js used to append `.azad-in-view { … !important }` on every page: a
    stylesheet parse per load, a CSP nonce dependency, and — because it was
    `!important` on `transform` — it cancelled the hover lift polish.css gives
    revealed stat cards.
    """

    def test_index_does_not_build_a_stylesheet(self):
        content = _read(JS_DIR / "index.js")
        assert 'createElement("style")' not in content
        assert "azad-scroll-styles" not in content

    def test_reveal_states_are_declared_in_css(self):
        app_css = _read(BASE_DIR / "app" / "static" / "css" / "app.css")
        assert ".azad-scroll-hidden" in app_css
        assert re.search(r"\.azad-scroll-hidden\.azad-in-view", app_css)
        # Not !important: the revealed rule must lose to the hover lift on
        # specificity, not pin every card's transform forever.
        assert "translateY(0) !important" not in app_css


class TestServiceWorkerCache:
    """The service worker precaches the entry module graph, not a stale list."""

    def test_sw_caches_new_js_assets(self):
        sw = _read(STATIC_DIR / "sw.js")
        for rel in ("index.js", "core/api.js", "core/theme.js", "components/ui.js", "components/toast.js"):
            assert f"/static/js/{rel}" in sw, f"sw.js does not precache {rel}"

    def test_sw_precaches_the_app_stylesheet_bundle(self):
        sw = _read(STATIC_DIR / "sw.js")
        assert "/static/css/dist/app.min.css" in sw

    def test_sw_precaches_every_module_the_entry_point_imports(self):
        """A module the entry point needs but the worker never cached is a
        first-visit offline failure — the exact gap the hand-written list had."""
        entry = _read(JS_DIR / "index.js")
        sw = _read(STATIC_DIR / "sw.js")
        imported = {rel for rel in re.findall(r"""(?:from|import)\s*\(?\s*["'](\./[^"']+)["']""", entry)}
        assert imported, "no imports found in index.js — the extraction is broken"
        missing = sorted(rel for rel in imported if f"/static/js/{rel[2:]}" not in sw)
        assert not missing, f"index.js imports modules the service worker never precaches: {missing}"


class TestNoVarInModules:
    """Modern modules avoid var."""

    def test_modules_avoid_var(self):
        failures = []
        for path in JS_DIR.rglob("*.js"):
            if re.search(r"\bvar\b", _read(path)):
                failures.append(f"{path.relative_to(JS_DIR).as_posix()}: uses var")
        assert not failures, "\n".join(failures)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
