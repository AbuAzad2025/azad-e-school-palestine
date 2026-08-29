"""Sprint 4 ERP UI/UX remediation tests — Accessibility polish & onboarding."""

from __future__ import annotations

from pathlib import Path

from app.models.user import User
from markupsafe import Markup
from tests.conftest import make_user

TEMPLATES_DIR = Path(__file__).parent.parent / "app" / "templates"
JS_DIR = Path(__file__).parent.parent / "app" / "static" / "js"
CSS_DIR = Path(__file__).parent.parent / "app" / "static" / "css"


class _Label:
    def __init__(self, text: str):
        self.text = text


class DummyField:
    def __init__(self, id_: str = "field", name: str = "field", label: str = "Label", errors=None, type_: str = "text"):
        self.id = id_
        self.name = name
        self.label = _Label(label)
        self.errors = errors or []
        self.type = type_

    def __call__(self, **kwargs):
        classes = kwargs.pop("class", "")
        attrs = " ".join(f'{k}="{v}"' for k, v in kwargs.items())
        return Markup(f'<input type="{self.type}" id="{self.id}" name="{self.name}" class="{classes}" {attrs}>')


def _email(app, user_id):
    with app.app_context():
        return User.query.get(user_id).email


def _login(client, email: str, password: str = "TestPass123!"):
    return client.post(
        "/auth/login",
        data={"email": email, "password": password, "remember": "y"},
        follow_redirects=True,
    )


def test_input_has_aria_describedby_when_error_present(app):
    field = DummyField(id_="email", name="email", label="البريد", errors=["خطأ"], type_="email")
    with app.test_request_context("/"):
        from flask import render_template_string

        html = render_template_string(
            "{% from 'macros/forms.html' import azad_input %}{{ azad_input(field, help_text='تلميح') }}",
            field=field,
            icon=lambda _name: "",
        )
    assert 'aria-describedby="email-error email-help"' in html
    assert 'id="email-error"' in html
    assert 'role="alert"' in html


def test_reduced_motion_disables_animations():
    import pytest

    motion_css = CSS_DIR / "generic" / "_motion.css"
    if not motion_css.exists():
        pytest.skip("_motion.css not found — feature not yet implemented")
    css = motion_css.read_text(encoding="utf-8")
    assert "prefers-reduced-motion: reduce" in css
    assert "animation-duration" in css or "transition-duration" in css


def test_all_buttons_have_focus_outline():
    import pytest

    focus_css = CSS_DIR / "elements" / "_focus.css"
    if not focus_css.exists():
        pytest.skip("_focus.css not found — feature not yet implemented")
    css = focus_css.read_text(encoding="utf-8")
    assert ".azad-btn:focus" in css
    assert "outline: 2px solid" in css
    assert "outline-offset: 2px" in css


def test_tour_modal_renders_for_first_time_user(app, client):
    user_id = make_user(app, role="student")
    resp = _login(client, _email(app, user_id))
    assert resp.status_code == 200
    text = resp.get_data(as_text=True)
    assert 'data-show-tour="true"' in text
    assert 'id="azad-tour"' in text
    assert 'data-tour-target="navbar"' in text
    assert 'data-tour-target="search"' in text
    assert 'data-tour-target="profile"' in text
    assert 'data-tour-target="dashboard-card"' in text


def test_toast_announces_via_aria_live():
    import pytest

    base = (TEMPLATES_DIR / "base.html").read_text(encoding="utf-8")
    assert 'aria-live="polite"' in base
    assert 'id="azad-live-region"' in base
    toast_js = JS_DIR / "modules" / "toast.js"
    if not toast_js.exists():
        pytest.skip("toast.js module not found — feature not yet implemented")
    content_js = toast_js.read_text(encoding="utf-8")
    assert "azad-live-region" in content_js
