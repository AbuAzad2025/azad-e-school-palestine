"""CSS build pipeline — bundle, purge, and minify the production stylesheets.

Usage:
    python scripts/build_css.py

Outputs:
    app/static/css/dist/brand.min.css
    app/static/css/dist/app.min.css
    app/static/css/dist/landing.min.css
    app/static/css/dist/ai-chat.min.css
    app/static/css/dist/manifest.txt

Bundles are declared in ``BUNDLES`` and are **self-contained**:

* every ``@import`` is inlined recursively (a bare relative ``@import`` inside a
  bundle would resolve against ``css/dist/`` — where no such file exists — and
  silently drop every token it defined);
* each bundle is one page entry's *complete* stylesheet set, in the exact order
  the template loads them, so the bundled cascade is identical to the source
  one and no bundle depends on another being loaded first (a page links exactly
  one bundle — never two bundles, and never a bundle plus a source file);
* the build fails if a bundle references a custom property it does not define,
  so a missing token can never ship.

Class rules are purged against the classes actually referenced by the templates
and JS. Because Jinja composes some class names at render time (for example
``azad-badge--{{ {'new': 'danger'}.get(status) }}``), the purge also honours
``SAFELIST_PATTERNS`` plus the string fragments that appear in templates, and
only ever drops a rule when it is sure the class is unreachable.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = BASE_DIR / "app" / "static" / "css"
DIST_DIR = SRC_DIR / "dist"
TEMPLATES_DIR = BASE_DIR / "app" / "templates"
JS_DIR = BASE_DIR / "app" / "static" / "js"

# ═══ Bundles ════════════════════════════════════════════════════════════════
# output name -> sources (relative to app/static/css, in cascade order).
# Each bundle is one page entry's complete stylesheet set: a page links
# exactly one bundle (never two, and never a bundle plus a source file).
_SHELL_SOURCES = [
    "brand.css",
    "theme.css",
    "base.css",
    "components/_ui.css",
    "components/_tables.css",
    "app.css",
    "polish.css",
]
BUNDLES: dict[str, dict[str, object]] = {
    # Every app page — matches base.html: brand, theme, base, app, polish.
    # app.css itself @imports theme.css / components/_ui.css / _tables.css;
    # inlining dedupes those back to a single copy each.
    "app.css": {"sources": list(_SHELL_SOURCES)},
    # Public landing page — matches landing.html (no app.css there).
    "landing.css": {
        "sources": [
            "brand.css",
            "theme.css",
            "base.css",
            "landing.css",
            "polish.css",
        ]
    },
    # Standalone fallback page — matches templates/offline.html, which loads
    # brand.css alone and therefore needs brand.css to be self-sufficient.
    "brand.css": {"sources": ["brand.css"]},
    # AI chat screen — the app shell plus its own extension stylesheet, which
    # only themes/overrides (ai-chat.css defines no tokens of its own).
    "ai-chat.css": {"sources": [*_SHELL_SOURCES, "ai-chat.css"]},
}

# Stylesheets a page loads *in addition to* a bundle (its own <link> inside a
# child template block). They are not bundled — but they are loaded on top of
# the app bundle, so they must not reference a token the bundle fails to
# define. Verified below.
COMPANIONS = [
    "admin.css",
    "components/_gradebook.css",
    "pages/pure-pages.css",
]

# ═══ Purge safelist ═════════════════════════════════════════════════════════
# Class families that Jinja assembles at render time. _collect_class_usage()
# can only see literal tokens, so these must be protected explicitly.
SAFELIST_PATTERNS: tuple[str, ...] = (
    r"^azad-badge--",
    r"^azad-badge-variant--",
    r"^azad-btn--",
    r"^azad-stat-card--",
    r"^azad-action-card--",
    r"^badge-",
    r"^alert-",
    r"^btn-",
    r"^bg-",
    r"^text-",
    r"^border-",
    r"^u-bg-",
    r"^u-text-",
    r"^mf-",  # meter fill widths, chosen by computed percentage
    r"^step-",
    r"^tab--",
    r"^is-",
)
_SAFELIST_RE = tuple(re.compile(p) for p in SAFELIST_PATTERNS)

_IMPORT_RE = re.compile(r"""@import\s+(?:url\(\s*)?['"]?(?P<target>[^'")\s;]+)['"]?\s*\)?\s*(?P<conditions>[^;]*);""")
_COMMENT_RE = re.compile(r"/\*[^*]*\*+(?:[^/*][^*]*\*+)*/", re.DOTALL)
_CLASS_ATTR_RE = re.compile(r"""class=["']([^"']+)["']""")
_CLASS_LIST_JS_RE = re.compile(
    r"""classList\.(?:add|remove|toggle)\(\s*["']([^"']+)["']|\.className\s*=\s*["']([^"']+)["']"""
)
_STRING_LITERAL_RE = re.compile(r"""["']([A-Za-z][A-Za-z0-9_-]{0,24})["']""")
_FRAGMENT_RE = re.compile(r"^[a-z][a-z0-9_-]{0,24}$")
_VAR_DEF_RE = re.compile(r"--([A-Za-z0-9_-]+)\s*:")
_VAR_USE_RE = re.compile(r"var\(\s*--([A-Za-z0-9_-]+)\s*(,)?")


def _strip_comments(css: str) -> str:
    """Drop ``/* … */`` before parsing.

    Comments can contain braces and ``@import``-looking prose, both of which
    would confuse rule splitting and import inlining. The minifier removes them
    from the output anyway.
    """
    return _COMMENT_RE.sub("", css)


def _inline_imports(css: str, origin: Path, emitted: set[Path]) -> str:
    """Recursively replace local ``@import`` rules with the imported content.

    ``emitted`` carries the files already bundled (across the whole bundle, not
    just this file) so shared partials such as theme.css are included once and
    import cycles terminate.
    """

    def replace(match: re.Match[str]) -> str:
        target = match.group("target")
        if target.startswith(("http://", "https://", "//", "data:")):
            return match.group(0)  # remote import: leave the browser to fetch it
        path = (origin.parent / target).resolve()
        if path in emitted:
            return ""
        if not path.is_file():
            raise FileNotFoundError(f"{origin.name}: @import target not found: {target}")
        emitted.add(path)
        inner = _inline_imports(_strip_comments(path.read_text(encoding="utf-8")), path, emitted)
        conditions = match.group("conditions").strip()
        if conditions:
            inner = f"@media {conditions} {{\n{inner}\n}}"
        return f"/* inlined {target} */\n{inner}\n"

    return _IMPORT_RE.sub(replace, css)


def _bundle_text(sources: list[str]) -> tuple[str, list[Path]]:
    """Concatenate a bundle's sources with every @import inlined."""
    emitted: set[Path] = set()
    parts: list[str] = []
    for rel in sources:
        path = (SRC_DIR / rel).resolve()
        if path in emitted:
            continue
        if not path.is_file():
            raise FileNotFoundError(f"Bundle source not found: {rel}")
        emitted.add(path)
        parts.append(_inline_imports(_strip_comments(path.read_text(encoding="utf-8")), path, emitted))
    return "\n".join(parts), sorted(emitted)


def _collect_class_usage() -> set[str]:
    """Scan templates and JS for CSS class names used at runtime."""
    classes = set()
    for root, _, files in os.walk(TEMPLATES_DIR):
        for name in files:
            if not name.endswith(".html"):
                continue
            content = (Path(root) / name).read_text(encoding="utf-8")
            for match in _CLASS_ATTR_RE.finditer(content):
                classes.update(match.group(1).split())
    # Include classes added by JS
    for root, _, files in os.walk(JS_DIR):
        for name in files:
            if not name.endswith(".js"):
                continue
            content = (Path(root) / name).read_text(encoding="utf-8")
            for match in _CLASS_LIST_JS_RE.finditer(content):
                classes.update(tok for group in match.groups() if group for tok in group.split())
    return classes


def _collect_dynamic_fragments() -> set[str]:
    """Quoted string literals in templates/JS that may complete a class name.

    Jinja builds names such as ``azad-badge--{{ mapping.get(x, 'muted') }}``, so
    the literal ``muted`` is the only evidence that ``azad-badge--muted`` is
    reachable. Keeping candidates by suffix is deliberately conservative: an
    extra rule costs bytes, a missing one costs a broken state.
    """
    fragments: set[str] = set()
    for root in (TEMPLATES_DIR, JS_DIR):
        for path in Path(root).rglob("*"):
            if path.suffix not in {".html", ".js"}:
                continue
            for match in _STRING_LITERAL_RE.finditer(path.read_text(encoding="utf-8")):
                token = match.group(1)
                if _FRAGMENT_RE.match(token):
                    fragments.add(token)
    return fragments


def _is_reachable(class_name: str, used: set[str], fragments: set[str]) -> bool:
    if class_name in used:
        return True
    if any(pattern.match(class_name) for pattern in _SAFELIST_RE):
        return True
    if class_name in fragments:
        return True
    for fragment in fragments:
        if class_name.endswith(f"--{fragment}") or class_name.endswith(f"-{fragment}"):
            return True
    return False


def _purge_unused(css: str, used_classes: set[str], fragments: set[str]) -> str:
    """Remove simple class rules that are definitely unreachable.

    Complex selectors and element selectors are always kept; a rule is dropped
    only when its selector is nothing but classes and none of them is reachable.
    """
    result = []
    depth = 0
    buffer = ""
    for char in css:
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                buffer += char
                selector = buffer.split("{", 1)[0].strip()
                keep = True
                simple_classes = re.findall(r"\.([a-zA-Z0-9_-]+)", selector)
                if simple_classes and not any(_is_reachable(c, used_classes, fragments) for c in simple_classes):
                    # Only drop if the entire selector is a list of simple classes
                    stripped = re.sub(r"\.[a-zA-Z0-9_-]+", "", selector)
                    stripped = re.sub(r"[,:>+~\s]", "", stripped)
                    if not stripped:
                        keep = False
                if keep:
                    result.append(buffer)
                buffer = ""
                continue
        buffer += char
    if buffer.strip():
        result.append(buffer)
    return "".join(result)


def _minify(css: str) -> str:
    """Lightweight CSS minifier."""
    # Remove comments
    css = _COMMENT_RE.sub("", css)
    # Collapse whitespace
    css = re.sub(r"\s+", " ", css)
    # Remove space around punctuation
    css = re.sub(r"\s*([{}:;,])\s*", r"\1", css)
    css = css.replace(";}", "}")
    return css.strip()


def _undefined_vars(css: str, defined: set[str]) -> list[str]:
    """Custom properties referenced without a value available in the bundle.

    ``var(--x, fallback)`` is safe by construction; ``var(--x)`` is not, and
    silently invalidates the whole declaration it appears in.
    """
    missing = {name for name, fallback in _VAR_USE_RE.findall(css) if not fallback and name not in defined}
    return sorted(missing)


def _build_manifest(files: dict[str, str]) -> None:
    lines = ["# Auto-generated CSS manifest — do not edit manually", ""]
    for name, content in files.items():
        digest = hashlib.sha256(content.encode()).hexdigest()[:12]
        lines.append(f"{name}: {digest}")
    (DIST_DIR / "manifest.txt").write_text("\n".join(lines), encoding="utf-8")


def _verify_companions(bundle_tokens: set[str]) -> None:
    """Companion stylesheets must only consume tokens the bundle defines."""
    for rel in COMPANIONS:
        path = SRC_DIR / rel
        if not path.is_file():
            raise FileNotFoundError(f"Companion stylesheet not found: {rel}")
        css = _minify(_strip_comments(path.read_text(encoding="utf-8")))
        # The companion may define its own local custom properties (e.g. scoped
        # vars on a component root). Exclude those from the undefined-check.
        companion_defs = set(_VAR_DEF_RE.findall(css))
        missing = _undefined_vars(css, bundle_tokens | companion_defs)
        if missing:
            raise RuntimeError(
                f"{rel}: references custom properties no bundle defines "
                f"({', '.join('--' + m for m in missing)}). It is loaded after a "
                f"bundle, so those declarations would be dropped at runtime."
            )


def build() -> dict[str, dict[str, int]]:
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    used_classes = _collect_class_usage()
    fragments = _collect_dynamic_fragments()
    stats: dict[str, dict[str, int]] = {}
    outputs: dict[str, str] = {}
    shell_tokens: set[str] = set()
    for src_name, spec in BUNDLES.items():
        sources = list(spec["sources"])  # type: ignore[arg-type]
        css, inlined = _bundle_text(sources)
        original_size = sum((SRC_DIR / rel).stat().st_size for rel in dict.fromkeys(sources))
        purged = _purge_unused(css, used_classes, fragments)
        minified = _minify(purged)
        # Verify the emitted artifact, not the intermediate: a bundle that
        # names a token it never defines would drop that whole declaration at
        # runtime, so refuse to write one.
        defined = set(_VAR_DEF_RE.findall(minified))
        if src_name == "app.css":
            shell_tokens = defined
        missing = _undefined_vars(minified, defined)
        if missing:
            raise RuntimeError(
                f"{src_name}: bundle references undefined custom properties "
                f"({', '.join('--' + m for m in missing)}). Add the defining "
                f"stylesheet to BUNDLES['{src_name}']['sources']."
            )
        dist_name = src_name.replace(".css", ".min.css")
        (DIST_DIR / dist_name).write_text(minified, encoding="utf-8")
        outputs[dist_name] = minified
        minified_bytes = len(minified.encode("utf-8"))
        stats[src_name] = {
            "files": len(inlined),
            "original": original_size,
            "minified": minified_bytes,
            "saved_percent": round((1 - minified_bytes / original_size) * 100, 1),
        }
    if not shell_tokens:
        raise RuntimeError("BUNDLES must define an app.css bundle to verify companions against")
    _verify_companions(shell_tokens)
    _build_manifest(outputs)
    return stats


if __name__ == "__main__":
    for src, info in build().items():
        print(
            f"{src}: {info['files']} files bundled, {info['original']} -> "
            f"{info['minified']} bytes ({info['saved_percent']}% saved)"
        )
