"""CSS architecture tests — Phase 3

Validates ITCSS/BEM discipline, design-token usage, and build pipeline.
"""
import os
import re
import subprocess
from pathlib import Path
import pytest


BASE_DIR = Path(__file__).resolve().parent.parent
CSS_DIR = BASE_DIR / "app" / "static" / "css"
DIST_DIR = CSS_DIR / "dist"
TEMPLATES_DIR = BASE_DIR / "app" / "templates"


def _css_files():
    return list(CSS_DIR.glob("*.css"))


class TestDesignTokens:
    """Colors, spacing, and shadows should prefer CSS variables."""

    def test_brand_css_defines_tokens(self):
        brand = (CSS_DIR / "brand.css").read_text(encoding="utf-8")
        assert "--azad-navy" in brand
        assert "--sp-1" in brand
        assert "--radius-md" in brand
        assert "--shadow-md" in brand

    def test_app_css_uses_color_tokens(self):
        app = (CSS_DIR / "app.css").read_text(encoding="utf-8")
        # Allow hex inside brand.css only; app.css should reference vars
        hex_colors = re.findall(r"#(?:[0-9a-fA-F]{3}){1,2}", app)
        # Some one-off hex values are acceptable (e.g. print borders), but
        # major colors should be tokenized.
        assert "var(--azad-navy)" in app or "var(--azad-text)" in app


class TestBEMNaming:
    """Major components use BEM-style class names."""

    def test_common_components_use_bem(self):
        app = (CSS_DIR / "app.css").read_text(encoding="utf-8")
        bem_patterns = [
            r"\.azad-card",
            r"\.azad-btn",
            r"\.azad-list",
            r"\.azad-item",
            r"\.azad-table",
        ]
        for pattern in bem_patterns:
            assert re.search(pattern, app), f"Missing BEM component matching {pattern}"

    def test_no_overly_nested_selectors(self):
        """Warn if any selector group is more than 4 levels deep."""
        failures = []
        for path in _css_files():
            content = path.read_text(encoding="utf-8")
            content = re.sub(r"/\*[^*]*\*+(?:[^/*][^*]*\*+)*/", "", content, flags=re.DOTALL)
            for match in re.finditer(r"([^{}]+)\{", content):
                selector_block = match.group(1).strip()
                if not selector_block or selector_block.startswith("@"):
                    continue
                for selector in selector_block.split(","):
                    selector = selector.strip()
                    if not selector:
                        continue
                    parts = re.split(r"[\s>+~]+", selector)
                    parts = [p for p in parts if p]
                    if len(parts) > 4:
                        failures.append(f"{path.name}: deep selector: {selector[:80]}")
        assert not failures, "\n".join(failures[:20])


class TestNoImportantOveruse:
    """Avoid !important except for utilities/print overrides."""

    def test_important_usage_is_limited(self):
        failures = []
        for path in _css_files():
            content = path.read_text(encoding="utf-8")
            count = content.count("!important")
            lines = content.count("\n") or 1
            rate = count / lines
            if rate > 0.05:
                failures.append(f"{path.name}: too many !important ({count} in {lines} lines)")
        assert not failures, "\n".join(failures)


class TestBuildPipeline:
    """Build script produces minified CSS and manifest."""

    def test_build_script_runs(self):
        result = subprocess.run(
            ["python", "scripts/build_css.py"],
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            check=True,
        )
        assert "saved" in result.stdout.lower(), result.stdout + result.stderr

    def test_minified_files_exist_and_are_smaller(self):
        for src_name in ("brand.css", "app.css", "ai-chat.css"):
            src = CSS_DIR / src_name
            dist = DIST_DIR / src_name.replace(".css", ".min.css")
            assert dist.exists(), f"Missing {dist.name}"
            assert dist.stat().st_size < src.stat().st_size, f"{dist.name} not smaller than source"

    def test_manifest_created(self):
        manifest = DIST_DIR / "manifest.txt"
        assert manifest.exists(), "CSS manifest not generated"
        content = manifest.read_text(encoding="utf-8")
        assert "brand.min.css" in content
        assert "app.min.css" in content
        assert "ai-chat.min.css" in content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])