"""CSS architecture tests — Phase 3

Validates ITCSS/BEM discipline, design-token usage, and build pipeline.
"""

import re
import subprocess
import sys
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
CSS_DIR = BASE_DIR / "app" / "static" / "css"
DIST_DIR = CSS_DIR / "dist"
TEMPLATES_DIR = BASE_DIR / "app" / "templates"
STATIC_DIR = BASE_DIR / "app" / "static"

# Static files that are legitimately referenced without a direct
# url_for('static', ...) call in a Jinja template. Documented, not hidden.
ALLOWED_ORPHANS = {
    "js/video_player.js",  # HLS player: exercised by tests, not yet wired to a template
}


def _all_templates():
    return sorted(TEMPLATES_DIR.rglob("*.html"))


def _asset_refs(template_path: Path) -> list[str]:
    """All static css/js filenames referenced via url_for in a template."""
    src = template_path.read_text(encoding="utf-8")
    refs = re.findall(
        r"filename='([^']+\.(?:css|js)[^']*)'|filename=\"([^\"]+\.(?:css|js)[^\"]*)\"",
        src,
    )
    return [(a or b).split("?")[0] for a, b in refs]


def _referenced_static_names() -> set[str]:
    """Every static path referenced anywhere: templates, python, sw.js, JS
    module imports, CSS @imports, and build sources."""
    referenced: set[str] = set()
    # 1. Jinja templates: url_for('static', filename='...')
    for tp in _all_templates():
        src = tp.read_text(encoding="utf-8")
        for a, b in re.findall(r"filename='([^']+)'|filename=\"([^\"]+)\"", src):
            referenced.add((a or b).split("?")[0])
    # 2. Python code (routes/services/scripts referencing asset paths)
    for py in [*BASE_DIR.glob("app/**/*.py"), *BASE_DIR.glob("scripts/**/*.py")]:
        try:
            txt = py.read_text(encoding="utf-8")
        except OSError:
            continue
        for m in re.findall(r"['\"]((?:css|js|img|fonts|uploads)/[^'\"]+)['\"]", txt):
            referenced.add(m)
    # 3. Service worker precache (paths look like "/static/js/core/api.js")
    sw = STATIC_DIR / "sw.js"
    if sw.exists():
        sw_txt = sw.read_text(encoding="utf-8")
        referenced.add("sw.js")
        for m in re.findall(r'"([^"]+)"', sw_txt):
            if m.startswith("/static/"):
                referenced.add(m[len("/static/") :])
        # "/offline" is a route, not a file under app/static — it is not a
        # static reference and must not be recorded as one (recording it as
        # offline.html is what hid the stale copy of that template here).
    # 4. JS module graph (index.js static + dynamic imports)
    for jsf in (STATIC_DIR / "js").rglob("*.js"):
        txt = jsf.read_text(encoding="utf-8")
        for m in re.findall(
            r"from\s+['\"]([^'\"]+)['\"]|import\s*\(?\s*['\"]([^'\"]+)['\"]",
            txt,
        ):
            mod = (m[0] or m[1]).lstrip("./")
            if mod.endswith(".js"):
                referenced.add(f"js/{mod}" if not mod.startswith("js/") else mod)
    # 5. CSS @import partials (plain and url() forms)
    for cssf in CSS_DIR.glob("*.css"):
        for m in re.findall(r"@import\s+(?:url\()?['\"]?([^'\")]+?)['\"]?\)?\s*;", cssf.read_text(encoding="utf-8")):
            referenced.add(f"css/{m.lstrip('./')}")
    # 6. Build sources (source css feeds dist/*.min.css loaded by templates)
    for distf in DIST_DIR.glob("*.min.css"):
        referenced.add(f"css/{distf.name.replace('.min.css', '.css')}")
    # 6b. Bundle inputs. A stylesheet is live if it is inlined into a bundle
    # that a template serves, even when no template names it directly — base.css
    # and polish.css are only ever reached that way now.
    build = _build_module()
    for spec in build.BUNDLES.values():
        for rel in spec["sources"]:
            referenced.add(f"css/{rel}")
    for rel in build.COMPANIONS:
        referenced.add(f"css/{rel}")
    return referenced


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
        # Allow hex inside brand.css only; app.css should reference vars.
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


class TestMotionPolicy:
    """prefers-reduced-motion is honoured once per sheet, not four times.

    The universal reset is all-`!important` and value-identical wherever it
    appears, so extra copies cannot change a computed value — they only add
    bytes to every page. One copy per sheet is the contract.
    """

    _RESET = re.compile(
        r"@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{\s*"
        r"\*,\s*\*::before,\s*\*::after\s*\{"
    )

    def test_universal_reduced_motion_reset_is_declared_at_most_once(self):
        offenders = []
        for path in _css_files():
            content = re.sub(r"/\*[^*]*\*+(?:[^/*][^*]*\*+)*/", "", path.read_text(encoding="utf-8"), flags=re.DOTALL)
            count = len(self._RESET.findall(content))
            if count > 1:
                offenders.append(f"{path.name}: {count} copies")
        assert not offenders, "Duplicate reduce-motion resets: " + ", ".join(offenders)

    def test_offline_page_still_gets_a_reset(self):
        """templates/offline.html links the standalone brand bundle, so the
        reduced-motion contract has to survive in brand.css on its own."""
        brand = (CSS_DIR / "brand.css").read_text(encoding="utf-8")
        assert "prefers-reduced-motion" in brand


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


def _build_module():
    """Load scripts/build_css.py so assertions use the real bundle config."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("build_css", BASE_DIR / "scripts" / "build_css.py")
    assert spec and spec.loader, "Cannot load scripts/build_css.py"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def built_bundles():
    """Rebuild dist/ once, then assert against fresh artifacts (order-independent)."""
    subprocess.run(
        [sys.executable, "scripts/build_css.py"],
        cwd=BASE_DIR,
        capture_output=True,
        text=True,
        check=True,
    )
    return _build_module()


class TestBuildPipeline:
    """Build script produces self-contained bundles and a manifest."""

    def test_build_script_runs(self):
        result = subprocess.run(
            [sys.executable, "scripts/build_css.py"],
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            check=True,
        )
        assert "saved" in result.stdout.lower(), result.stdout + result.stderr

    def test_minified_bundles_are_smaller_than_their_sources(self, built_bundles):
        """A bundle is one page's whole stylesheet set, so the size invariant is
        against the sum of its sources — not the single same-named source."""
        for name, spec in built_bundles.BUNDLES.items():
            dist = DIST_DIR / name.replace(".css", ".min.css")
            assert dist.exists(), f"Missing {dist.name}"
            source_bytes = sum((CSS_DIR / rel).stat().st_size for rel in dict.fromkeys(spec["sources"]))
            assert dist.stat().st_size < source_bytes, f"{dist.name} not smaller than its sources"

    def test_manifest_created(self):
        manifest = DIST_DIR / "manifest.txt"
        assert manifest.exists(), "CSS manifest not generated"
        content = manifest.read_text(encoding="utf-8")
        assert "brand.min.css" in content
        assert "app.min.css" in content
        assert "ai-chat.min.css" in content

    def test_bundles_contain_no_unresolved_imports(self, built_bundles):
        """A relative @import inside dist/ would resolve against dist/ (where no
        such file exists) and silently drop every token it defined."""
        offenders = []
        for dist in DIST_DIR.glob("*.min.css"):
            css = dist.read_text(encoding="utf-8")
            for target in re.findall(r"@import\s+(?:url\(\s*)?['\"]?([^'\")\s;]+)", css):
                if not target.startswith(("http://", "https://", "//", "data:")):
                    offenders.append(f"{dist.name}: @import {target}")
        assert not offenders, "Unresolved local @import in bundles:\n" + "\n".join(offenders)

    def test_bundles_define_every_token_they_use(self, built_bundles):
        """var(--x) with no fallback invalidates the declaration it sits in, so
        every referenced token must be defined inside the same bundle."""
        offenders = []
        for dist in DIST_DIR.glob("*.min.css"):
            css = dist.read_text(encoding="utf-8")
            defined = set(re.findall(r"--([A-Za-z0-9_-]+)\s*:", css))
            for name, fallback in re.findall(r"var\(\s*--([A-Za-z0-9_-]+)\s*(,)?", css):
                if not fallback and name not in defined:
                    offenders.append(f"{dist.name}: var(--{name})")
        assert not offenders, (
            "Bundles reference tokens they do not define (declaration would be "
            "dropped at runtime):\n" + "\n".join(offenders)
        )

    def test_dynamic_class_variants_survive_the_purge(self, built_bundles):
        """Jinja composes these at render time (azad-badge--{{ … }}), so a purge
        that only trusts literal tokens must not delete them."""
        css = (DIST_DIR / "app.min.css").read_text(encoding="utf-8")
        purged = [
            cls
            for cls in (
                "azad-badge--success",
                "azad-badge--info",
                "azad-badge--warning",
                "azad-badge--danger",
                "azad-badge--muted",
                "azad-badge-variant--success",
                "badge-err",
                "u-bg-green-solid",
            )
            if f".{cls}" not in css
        ]
        assert not purged, f"Runtime-reachable classes were purged: {purged}"

    def test_committed_bundles_match_a_fresh_build(self, tmp_path, monkeypatch):
        """The dist artifacts are committed and served, so they can go stale.

        Build into a temporary directory instead of dist/ — running the real
        build here would overwrite the very file being checked, and the check
        would pass forever after the first run.
        """
        module = _build_module()
        monkeypatch.setattr(module, "DIST_DIR", tmp_path)
        module.build()
        stale = []
        for name in ("app.min.css", "landing.min.css", "brand.min.css", "ai-chat.min.css", "manifest.txt"):
            fresh = (tmp_path / name).read_bytes()
            committed = (DIST_DIR / name).read_bytes()
            if fresh != committed:
                stale.append(name)
        assert not stale, (
            "Committed bundles do not match scripts/build_css.py output "
            f"({', '.join(stale)}). Run: python scripts/build_css.py"
        )

    def test_shell_templates_load_the_prebuilt_bundle(self, built_bundles):
        """Every page entry links its own bundle, and only that bundle.

        The pipeline used to build and commit dist/*.min.css while no template
        referenced it, so every page shipped the sources instead: five
        blocking requests and ~35% more bytes. The AI chat screen is checked
        here too because it was the page that never loaded its own stylesheet
        at all (the shell bundle covers the shell, not ai-chat.css).
        """
        expected = {
            "base.html": "css/dist/app.min.css",
            "landing.html": "css/dist/landing.min.css",
            "offline.html": "css/dist/brand.min.css",
            "ai/chat.html": "css/dist/ai-chat.min.css",
        }
        for rel, bundle in expected.items():
            refs = _asset_refs(TEMPLATES_DIR / rel)
            assert bundle in refs, f"{rel} does not load {bundle} (loads {refs})"
            # One bundle per page: a second one would re-declare every token and
            # double the blocking bytes rather than override the shell.
            bundles = [r for r in refs if r.startswith("css/dist/")]
            assert bundles == [bundle], f"{rel} loads more than one bundle: {bundles}"

    def test_every_template_stylesheet_is_bundled_or_a_companion(self, built_bundles):
        """No template may link a stylesheet that no bundle covers (it would
        ship alongside a bundle with no defined tokens)."""
        covered = set()
        for spec in built_bundles.BUNDLES.values():
            covered.update(spec["sources"])
        covered.update(built_bundles.COMPANIONS)
        unlocked = sorted(
            {
                ref[len("css/") :]
                for tp in _all_templates()
                for ref in _asset_refs(tp)
                if ref.startswith("css/") and not ref.startswith("css/dist/")
            }
            - covered
        )
        assert not unlocked, f"Stylesheets loaded by templates but in no bundle: {unlocked}"


class TestStaticAssetExistence:
    """Every static file referenced via url_for('static', ...) must exist."""

    def test_referenced_assets_exist(self):
        missing = []
        for tp in _all_templates():
            for ref in _asset_refs(tp):
                if not (STATIC_DIR / ref).exists():
                    missing.append(f"{tp.relative_to(TEMPLATES_DIR)}: {ref}")
        assert not missing, "Missing static files:\n" + "\n".join(missing)

    def test_no_hardcoded_static_paths(self):
        """Templates must use url_for, never hardcoded /static/ URLs."""
        offenders = []
        for tp in _all_templates():
            src = tp.read_text(encoding="utf-8")
            for m in re.findall(r"(?:src|href)=['\"](/static/[^'\"]+)['\"]", src):
                offenders.append(f"{tp.relative_to(TEMPLATES_DIR)}: {m}")
        assert not offenders, "Hardcoded /static/ paths:\n" + "\n".join(offenders)


class TestNoDuplicateAssetImports:
    """No template may import the same CSS/JS asset more than once."""

    def test_no_duplicate_asset_refs_per_template(self):
        dupes = []
        for tp in _all_templates():
            refs = _asset_refs(tp)
            seen: set[str] = set()
            for r in refs:
                if r in seen:
                    dupes.append(f"{tp.relative_to(TEMPLATES_DIR)}: duplicate {r}")
                seen.add(r)
        assert not dupes, "\n".join(dupes)

    def test_no_source_and_dist_loaded_together(self):
        """A template must not load both a source css and its dist build."""
        offenders = []
        for tp in _all_templates():
            refs = set(_asset_refs(tp))
            for r in refs:
                if r.startswith("css/dist/"):
                    src_counterpart = f"css/{Path(r).name.replace('.min.css', '.css')}"
                    if src_counterpart in refs:
                        offenders.append(f"{tp.relative_to(TEMPLATES_DIR)}: {r} + {src_counterpart}")
        assert not offenders, "\n".join(offenders)


class TestNoOrphanedStaticAssets:
    """Static files not referenced by any template/route/JS module/CSS import
    are reported. Legitimately indirect references are excluded; anything on
    the explicit ALLOWED_ORPHANS allowlist is documented dead weight."""

    def test_no_unexpected_orphans(self):
        referenced = _referenced_static_names()
        orphans = []
        for f in STATIC_DIR.rglob("*"):
            if not f.is_file():
                continue
            rel = f.relative_to(STATIC_DIR).as_posix()
            if rel.startswith(("uploads/", "css/dist/", "fonts/")):
                continue
            if rel in referenced or rel in ALLOWED_ORPHANS:
                continue
            orphans.append(rel)
        assert not orphans, "Unreferenced static files (remove or add to ALLOWED_ORPHANS):\n" + "\n".join(
            sorted(orphans)
        )


class TestJinjaBlockAssetIntegrity:
    """Child templates must parse cleanly and load assets inside blocks."""

    def test_all_templates_parse(self):
        """Strict Jinja parse catches syntax errors before runtime (e.g. nested
        {{ }} expressions, unbalanced parens in macro calls)."""
        from jinja2 import Environment, FileSystemLoader

        env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
        broken = []
        for tp in _all_templates():
            rel = tp.relative_to(TEMPLATES_DIR).as_posix()
            try:
                env.parse(env.loader.get_source(env, rel)[0])
            except Exception as e:  # noqa: BLE001 - report every parse failure
                broken.append(f"{rel}: {type(e).__name__}: {e}")
        assert not broken, "\n".join(broken)

    def test_child_asset_loads_are_inside_blocks(self):
        """In a child template (one that extends), asset <link>/<script> tags
        must appear inside a {% block %} so parent assets are preserved."""
        offenders = []
        for tp in _all_templates():
            src = tp.read_text(encoding="utf-8")
            if not re.search(r"\{%\s*extends\s+[\"'][^\"']+[\"']", src):
                continue  # parent templates may load assets at top level
            first_block = src.find("{% block ")
            for m in re.finditer(r"(?:<link[^>]+rel=['\"]stylesheet['\"]|<script[^>]+src=)", src):
                if first_block == -1 or m.start() < first_block:
                    offenders.append(f"{tp.relative_to(TEMPLATES_DIR)}: asset load before/outside any block")
                    break
        assert not offenders, "\n".join(offenders)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
