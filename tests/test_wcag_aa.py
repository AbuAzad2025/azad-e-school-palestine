"""WCAG 2.1 AA compliance tests — Phase 2

These tests scan Jinja2 templates for the most common accessibility issues.
Because templates contain Jinja2 expressions, some checks are heuristic and
intentionally lenient where dynamic IDs or print-only pages are involved.
"""

import os
import re

import pytest
from bs4 import BeautifulSoup

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "app", "templates")


def _template_files():
    """Return all Jinja2 template files."""
    files = []
    for root, _, filenames in os.walk(TEMPLATES_DIR):
        for name in filenames:
            if name.endswith(".html"):
                files.append(os.path.join(root, name))
    return files


class TestTextAlternatives:
    """1.1.1 Non-text Content: Images must have alt text."""

    def test_all_images_have_alt(self):
        failures = []
        for path in _template_files():
            with open(path, encoding="utf-8") as f:
                content = f.read()
            soup = BeautifulSoup(content, "html.parser")
            for img in soup.find_all("img"):
                if not img.has_attr("alt"):
                    failures.append(f"{os.path.relpath(path)}: <img> missing alt")
        assert not failures, "\n".join(failures)

    def test_landing_logo_has_meaningful_alt(self):
        path = os.path.join(TEMPLATES_DIR, "landing.html")
        with open(path, encoding="utf-8") as f:
            content = f.read()
        soup = BeautifulSoup(content, "html.parser")
        logo = soup.find("img", src=lambda x: x and "azad-mark.svg" in x)
        assert logo, "Landing logo not found"
        assert logo.get("alt"), "Landing logo alt must not be empty"


class TestKeyboardAccessible:
    """2.1.1 Keyboard: Clickable non-button elements should be focusable."""

    def test_clickable_divs_have_tabindex_and_role(self):
        failures = []
        for path in _template_files():
            with open(path, encoding="utf-8") as f:
                content = f.read()
            soup = BeautifulSoup(content, "html.parser")
            for tag in soup.find_all(["div", "span"]):
                if tag.has_attr("onclick") and not tag.has_attr("tabindex"):
                    failures.append(f"{os.path.relpath(path)}: clickable {tag.name} lacks tabindex")
        assert not failures, "\n".join(failures)


class TestFocusVisible:
    """2.4.7 Focus Visible: Focus indicator CSS must exist."""

    def test_focus_visible_in_css(self):
        css_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "app", "static", "css")
        found = False
        for root, _, filenames in os.walk(css_dir):
            for name in filenames:
                if not name.endswith(".css"):
                    continue
                with open(os.path.join(root, name), encoding="utf-8") as f:
                    content = f.read()
                if ":focus-visible" in content or ":focus" in content:
                    found = True
        assert found, "No :focus-visible or :focus rules found in CSS"


class TestContrast:
    """1.4.3 Contrast (Minimum): Avoid inline low-contrast colors."""

    def test_no_inline_low_contrast_grey(self):
        failures = []
        low_contrast_colors = ["#ccc", "#bbb", "#aaa", "#999", "#888", "#666"]
        for path in _template_files():
            if os.path.basename(path) in ("invoice.html", "report_card.html"):
                # print-only templates use their own stylesheet
                continue
            with open(path, encoding="utf-8") as f:
                content = f.read()
            for color in low_contrast_colors:
                if color in content:
                    failures.append(f"{os.path.relpath(path)}: low-contrast color {color}")
        assert not failures, "\n".join(failures)


class TestResizeText:
    """1.4.4 Resize Text: Body text should use relative units."""

    def test_body_font_size_not_fixed_px(self):
        """Flag font-size: Npx in templates (except large decorative >=24px or print templates)."""
        failures = []
        for path in _template_files():
            if "errors/" in path or os.path.basename(path) in ("invoice.html", "report_card.html"):
                continue
            with open(path, encoding="utf-8") as f:
                content = f.read()
            for m in re.finditer(r"font-size:\s*(\d+)px", content):
                size = int(m.group(1))
                if size < 24:
                    failures.append(f"{os.path.relpath(path)}: font-size:{size}px (body text)")
        assert not failures, "\n".join(failures)


class TestLabelsOrInstructions:
    """3.3.2 Labels or Instructions: Form inputs must have labels."""

    EXEMPT_NAMES = {"csrf_token", "_method", "remember"}

    def test_form_inputs_have_labels(self):
        failures = []
        for path in _template_files():
            with open(path, encoding="utf-8") as f:
                content = f.read()
            soup = BeautifulSoup(content, "html.parser")
            for inp in soup.find_all(["input", "select", "textarea"]):
                input_type = inp.get("type", "text")
                if input_type in ("hidden", "submit", "button", "image", "reset"):
                    continue
                if inp.has_attr("aria-label") or inp.has_attr("aria-labelledby") or inp.has_attr("title"):
                    continue
                if inp.find_parent("label"):
                    continue
                input_id = inp.get("id") or ""
                input_name = inp.get("name", "")
                # ignore dynamic assessment answers and rubric criteria
                if "q_{{" in input_name or "criteria[0]" in input_name or "score_{{" in input_name:
                    continue
                if input_name in self.EXEMPT_NAMES:
                    continue
                if input_id and soup.find("label", attrs={"for": input_id}):
                    continue
                # check for a visible label as a preceding sibling inside .form-group or .azad-field
                parent = inp.find_parent(["div", "label"])
                if parent:
                    prev = inp.find_previous_sibling()
                    if prev and prev.name == "label":
                        continue
                    # look for a label anywhere in the parent (covers some Jinja-rendered siblings)
                    if parent.find("label"):
                        continue
                failures.append(f"{os.path.relpath(path)}: input name={input_name!r} id={input_id!r} lacks label")
        assert not failures, "\n".join(failures)


class TestErrorIdentification:
    """3.3.1 Error Identification: Error messages should be announced."""

    def test_error_classes_have_role(self):
        failures = []
        for path in _template_files():
            with open(path, encoding="utf-8") as f:
                content = f.read()
            soup = BeautifulSoup(content, "html.parser")
            for cls in ["error", "invalid-feedback", "azad-error"]:
                for el in soup.find_all(class_=cls):
                    if not el.has_attr("role"):
                        failures.append(f"{os.path.relpath(path)}: .{cls} element lacks role")
        assert not failures, "\n".join(failures)


class TestConsistentNavigation:
    """2.4.1 Bypass Blocks + 3.2.3 Consistent Navigation."""

    def test_base_template_has_skip_link(self):
        path = os.path.join(TEMPLATES_DIR, "base.html")
        with open(path, encoding="utf-8") as f:
            content = f.read()
        assert "skip-link" in content.lower(), "base.html should contain a skip link"
        assert "#main" in content or "main-content" in content, "base.html should link to main content"

    def test_content_pages_extend_base(self):
        """Full pages should extend base.html; partials and standalone print pages are exempt."""
        failures = []
        exempt = {
            "base.html",
            "landing.html",
            "offline.html",
            "billing/invoice.html",
            "grades/report_card.html",
        }
        partial_dirs = {"partials", "macros", "errors"}
        for path in _template_files():
            rel = os.path.relpath(path, TEMPLATES_DIR).replace("\\", "/")
            if rel in exempt:
                continue
            if any(part in partial_dirs for part in rel.split("/")):
                continue
            if os.path.basename(rel).startswith("_"):
                continue
            with open(path, encoding="utf-8") as f:
                first_lines = "\n".join([f.readline() for _ in range(5)])
            if "{% extends" not in first_lines:
                failures.append(f"{rel}: does not extend a base template")
        assert not failures, "\n".join(failures)


class TestLanguageOfPage:
    """3.1.1 Language of Page."""

    def test_base_template_has_lang_and_dir(self):
        path = os.path.join(TEMPLATES_DIR, "base.html")
        with open(path, encoding="utf-8") as f:
            content = f.read()
        assert "<html" in content, "base.html missing <html> tag"
        assert "lang=" in content, "base.html missing lang attribute"
        assert "dir=" in content, "base.html missing dir attribute"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
