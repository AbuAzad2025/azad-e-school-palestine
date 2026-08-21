"""Sprint 3 ERP UI/UX remediation tests — Forms, validation & file upload."""

from __future__ import annotations

from app.models.user import User
from markupsafe import Markup
from tests.conftest import (
    make_class,
    make_grade,
    make_school,
    make_subject,
    make_subscription,
    make_subscription_plan,
    make_user,
)


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


def test_form_row_macro_renders_grid_layout(app):
    with app.test_request_context("/"):
        from flask import render_template_string

        html = render_template_string(
            "{% from 'macros/forms.html' import azad_form_row %}"
            "{% call azad_form_row(cols=3, class='my-row') %}"
            "<div class='azad-form-col'>A</div>"
            "{% endcall %}"
        )
    assert "azad-form-row" in html
    assert "my-row" in html
    assert "grid-template-columns" in html


def test_inline_validation_shows_error_on_blur(app):
    field = DummyField(id_="email", name="email", label="البريد الإلكتروني", type_="email")
    with app.test_request_context("/"):
        from flask import render_template_string

        html = render_template_string(
            "{% from 'macros/forms.html' import azad_input %}{{ azad_input(field) }}",
            field=field,
            icon=lambda _name: "",
        )
    assert 'data-validate="true"' in html
    assert 'type="email"' in html
    assert "azad-field__error" in html
    assert 'aria-live="polite"' in html


def test_file_upload_zone_renders_custom_ui(app):
    field = DummyField(id_="receipt", name="receipt", label="إيصال الدفع", type_="file")
    with app.test_request_context("/"):
        from flask import render_template_string

        html = render_template_string(
            "{% from 'macros/forms.html' import azad_file_upload %}{{ azad_file_upload(field, label='إيصال الدفع') }}",
            field=field,
            icon=lambda _name: "",
        )
    assert "azad-upload" in html
    assert "azad-upload__zone" in html
    assert "azad-upload__input" in html


def test_status_timeline_shows_all_steps(app, client):
    school_id = make_school(app)
    grade_id = make_grade(app, school_id)
    subject_id = make_subject(app)
    class_id = make_class(app, school_id, grade_id, subject_id)
    plan_id = make_subscription_plan(app, school_id, class_id)
    student_id = make_user(app, role="student", school_id=school_id)
    sub_id = make_subscription(app, student_id, plan_id, class_id, status="active")
    admin_id = make_user(app, role="super_admin")
    _login(client, _email(app, admin_id))

    resp = client.get(f"/admin/subscriptions/{sub_id}")
    assert resp.status_code == 200
    text = resp.get_data(as_text=True)
    assert "azad-timeline" in text
    assert "مُرسل" in text
    assert "بانتظار المراجعة" in text
    assert "مُعتمد / نشط" in text
    assert "منتهي الصلاحية" in text


def test_error_styling_uses_azad_field_error_class(app):
    field = DummyField(id_="name", name="name", label="الاسم", errors=["هذا الحقل مطلوب"])
    with app.test_request_context("/"):
        from flask import render_template_string

        html = render_template_string(
            "{% from 'macros/forms.html' import azad_input %}{{ azad_input(field) }}",
            field=field,
            icon=lambda _name: "",
        )
    assert "azad-field--error" in html
    assert "azad-field__error" in html
    assert "form-errors" not in html
