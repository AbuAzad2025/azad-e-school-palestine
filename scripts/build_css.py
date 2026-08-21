"""CSS build pipeline — concatenate, purge, and minify stylesheets.

Usage:
    python scripts/build_css.py

Outputs:
    app/static/css/dist/brand.min.css
    app/static/css/dist/app.min.css
    app/static/css/dist/ai-chat.min.css
"""
import os
import re
import hashlib
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = BASE_DIR / "app" / "static" / "css"
DIST_DIR = SRC_DIR / "dist"
TEMPLATES_DIR = BASE_DIR / "app" / "templates"
JS_DIR = BASE_DIR / "app" / "static" / "js"


def _collect_class_usage() -> set[str]:
    """Scan templates and JS for CSS class names used at runtime."""
    classes = set()
    pattern = re.compile(r'class=["\']([^"\']+)["\']')
    for root, _, files in os.walk(TEMPLATES_DIR):
        for name in files:
            if not name.endswith(".html"):
                continue
            path = Path(root) / name
            content = path.read_text(encoding="utf-8")
            for match in pattern.finditer(content):
                for token in match.group(1).split():
                    classes.add(token)
    # Include classes added by JS
    for root, _, files in os.walk(JS_DIR):
        for name in files:
            if not name.endswith(".js"):
                continue
            content = (Path(root) / name).read_text(encoding="utf-8")
            for match in re.finditer(r'classList\.(?:add|remove|toggle)\(["\']([^"\']+)["\']\)', content):
                classes.update(match.group(1).split())
            for match in re.finditer(r'\.className\s*=\s*["\']([^"\']+)["\']', content):
                classes.update(match.group(1).split())
    return classes


def _purge_unused(css: str, used_classes: set[str]) -> str:
    """Remove simple class rules whose selector is not referenced anywhere.

    This is a best-effort purge; it only removes standalone class selectors
    that are definitely unused. Complex selectors and element selectors are kept.
    """
    # Tokenize rules roughly
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
                # Keep keyframes, font-face, media queries, complex selectors
                keep = True
                simple_classes = re.findall(r"\.([a-zA-Z0-9_-]+)", selector)
                if simple_classes and not any(c in used_classes for c in simple_classes):
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
    css = re.sub(r"/\*[^*]*\*+(?:[^/*][^*]*\*+)*/", "", css, flags=re.DOTALL)
    # Collapse whitespace
    css = re.sub(r"\s+", " ", css)
    # Remove space around punctuation
    css = re.sub(r"\s*([{}:;,])\s*", r"\1", css)
    css = css.replace(";}", "}")
    return css.strip()


def _build_manifest(files: dict[str, str]) -> None:
    manifest = {}
    for name, content in files.items():
        digest = hashlib.sha256(content.encode()).hexdigest()[:12]
        manifest[name] = {"file": name, "hash": digest}
    lines = ["# Auto-generated CSS manifest — do not edit manually", ""]
    for name, info in manifest.items():
        lines.append(f"{name}: {info['hash']}")
    (DIST_DIR / "manifest.txt").write_text("\n".join(lines), encoding="utf-8")


def build() -> dict[str, int]:
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    used_classes = _collect_class_usage()
    stats = {}
    outputs = {}
    for src_name in ("brand.css", "app.css", "ai-chat.css"):
        src_path = SRC_DIR / src_name
        if not src_path.exists():
            raise FileNotFoundError(src_path)
        css = src_path.read_text(encoding="utf-8")
        original_size = len(css)
        purged = _purge_unused(css, used_classes)
        minified = _minify(purged)
        dist_name = src_name.replace(".css", ".min.css")
        dist_path = DIST_DIR / dist_name
        dist_path.write_text(minified, encoding="utf-8")
        outputs[dist_name] = minified
        stats[src_name] = {
            "original": original_size,
            "minified": len(minified),
            "saved_percent": round((1 - len(minified) / original_size) * 100, 1),
        }
    _build_manifest(outputs)
    return stats


if __name__ == "__main__":
    stats = build()
    for src, info in stats.items():
        print(
            f"{src}: {info['original']} -> {info['minified']} bytes "
            f"({info['saved_percent']}% saved)"
        )