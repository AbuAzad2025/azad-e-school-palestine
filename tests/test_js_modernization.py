"""JavaScript modernization tests — Phase 4"""

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    not (Path(__file__).resolve().parent.parent / "app" / "static" / "js" / "modules").exists(),
    reason="app/static/js/modules/ directory not found — JS modules not yet implemented",
)


BASE_DIR = Path(__file__).resolve().parent.parent
JS_DIR = BASE_DIR / "app" / "static" / "js"
MODULES_DIR = JS_DIR / "modules"


def _read(path):
    return path.read_text(encoding="utf-8")


class TestModulesExist:
    """Core ES modules are present."""

    def test_entry_module_exists(self):
        assert (JS_DIR / "index.js").exists(), "Missing app/static/js/index.js entry module"

    def test_api_module_exists(self):
        assert (MODULES_DIR / "api.js").exists()

    def test_theme_module_exists(self):
        assert (MODULES_DIR / "theme.js").exists()

    def test_ui_module_exists(self):
        assert (MODULES_DIR / "ui.js").exists()

    def test_toast_module_exists(self):
        assert (MODULES_DIR / "toast.js").exists()


class TestApiModule:
    """API module has modern fetch wrapper with CSRF, timeout, and error handling."""

    def test_api_uses_fetch_with_abortcontroller(self):
        content = _read(MODULES_DIR / "api.js")
        assert "AbortController" in content
        assert "fetch(" in content

    def test_api_injects_csrf_token(self):
        content = _read(MODULES_DIR / "api.js")
        assert "X-CSRFToken" in content
        assert "csrf-token" in content or "csrf_token" in content

    def test_api_has_timeout_handling(self):
        content = _read(MODULES_DIR / "api.js")
        assert "setTimeout" in content
        assert "controller.abort" in content

    def test_api_exports_http_verbs(self):
        content = _read(MODULES_DIR / "api.js")
        for verb in ("export const get", "export const post", "export const put", "export const del"):
            assert verb in content, f"Missing {verb}"


class TestUiModule:
    """UI module uses event delegation."""

    def test_ui_module_has_delegate_helper(self):
        content = _read(MODULES_DIR / "ui.js")
        assert "export function delegate" in content
        assert "closest(selector)" in content

    def test_ui_uses_delegation_for_common_patterns(self):
        content = _read(MODULES_DIR / "ui.js")
        assert "document.body.addEventListener" in content or "delegate(document.body" in content


class TestBaseTemplateUsesModule:
    """base.html loads JS as an ES module."""

    def test_base_uses_module_script(self):
        base = _read(BASE_DIR / "app" / "templates" / "base.html")
        assert 'type="module"' in base
        assert "js/index.js" in base


class TestServiceWorkerCache:
    """Service worker caches module assets."""

    def test_sw_caches_new_js_assets(self):
        sw = _read(BASE_DIR / "app" / "static" / "sw.js")
        assert "/static/js/index.js" in sw
        assert "/static/js/modules/api.js" in sw
        assert "/static/js/modules/theme.js" in sw
        assert "/static/js/modules/ui.js" in sw
        assert "/static/js/modules/toast.js" in sw


class TestNoVarInModules:
    """Modern modules avoid var."""

    def test_modules_avoid_var(self):
        failures = []
        for path in MODULES_DIR.glob("*.js"):
            content = _read(path)
            if re.search(r"\bvar\b", content):
                failures.append(f"{path.name}: uses var")
        assert not failures, "\n".join(failures)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
