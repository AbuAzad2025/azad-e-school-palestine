"""Sprint 2 ERP UI/UX remediation tests — Dashboards, tables, charts, bulk actions."""

from __future__ import annotations

from pathlib import Path

from app.models.user import User
from tests.conftest import (
    make_class,
    make_class_member,
    make_grade,
    make_grade_category,
    make_school,
    make_subject,
    make_user,
)

TEMPLATES_DIR = Path(__file__).parent.parent / "app" / "templates"


def _email(app, user_id):
    with app.app_context():
        return User.query.get(user_id).email


def _login(client, email: str, password: str = "TestPass123!"):
    return client.post(
        "/auth/login",
        data={"email": email, "password": password, "remember": "y"},
        follow_redirects=True,
    )


def test_azad_table_macro_renders_table_with_modifiers(app):
    with app.test_request_context("/"):
        from flask import render_template_string

        html = render_template_string(
            "{% from 'macros/ui.html' import azad_table %}"
            "{{ azad_table(headers, rows, "
            "modifiers='azad-table--striped azad-table--hover', bulk='users', actions=True) }}",
            headers=[{"key": "name", "label": "الاسم"}, {"key": "role", "label": "الدور"}],
            rows=[
                {
                    "id": 1,
                    "cells": {"name": "أحمد", "role": "معلم"},
                    "actions": '<a href="/u/1">فتح</a>',
                }
            ],
        )
    assert "azad-table" in html
    assert "azad-table--striped" in html
    assert "azad-table--hover" in html
    assert 'data-bulk-entity="users"' in html
    assert 'data-label="الاسم"' in html
    assert "data-bulk-bar" in html


def test_admin_dashboard_has_charts(app, client):
    user_id = make_user(app, role="super_admin")
    _login(client, _email(app, user_id))
    resp = client.get("/admin/")
    assert resp.status_code == 200
    text = resp.get_data(as_text=True)
    assert 'data-chart="bar"' in text
    assert 'data-chart="doughnut"' in text
    assert "chart-card--wide" in text


def test_school_admin_dashboard_has_charts(app, client):
    school_id = make_school(app)
    user_id = make_user(app, role="school_admin", school_id=school_id)
    _login(client, _email(app, user_id))
    resp = client.get("/admin/school-admin")
    assert resp.status_code == 200
    text = resp.get_data(as_text=True)
    assert 'data-chart="bar"' in text
    assert 'data-chart="doughnut"' in text


def test_teacher_dashboard_has_actions_dropdown(app, client):
    school_id = make_school(app)
    grade_id = make_grade(app, school_id)
    subject_id = make_subject(app)
    teacher_id = make_user(app, role="teacher", school_id=school_id)
    make_class(app, school_id, grade_id, subject_id, teacher_id=teacher_id)
    _login(client, _email(app, teacher_id))
    resp = client.get("/auth/dashboard")
    assert resp.status_code == 200
    text = resp.get_data(as_text=True)
    assert "azad-actions-dropdown" in text
    assert "data-actions-toggle" in text
    assert "data-actions-menu" in text


def test_bulk_action_endpoint(app, client):
    admin_id = make_user(app, role="super_admin")
    target_id = make_user(app, role="student")
    _login(client, _email(app, admin_id))
    resp = client.post(
        "/admin/bulk-action",
        json={"entity": "users", "action": "deactivate", "ids": [target_id]},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    with app.app_context():
        assert User.query.get(target_id).is_active is False


def test_admin_users_table_has_bulk_and_actions_dropdown(app, client):
    user_id = make_user(app, role="super_admin")
    _login(client, _email(app, user_id))
    resp = client.get("/admin/users")
    assert resp.status_code == 200
    text = resp.get_data(as_text=True)
    assert "azad-table" in text
    assert 'data-bulk-entity="users"' in text
    assert "data-bulk-bar" in text


def test_gradebook_has_mobile_card_view(app, client):
    school_id = make_school(app)
    grade_id = make_grade(app, school_id)
    subject_id = make_subject(app)
    class_id = make_class(app, school_id, grade_id, subject_id)
    make_grade_category(app, class_id, "اختبارات", 1.0)
    student_id = make_user(app, role="student", school_id=school_id)
    make_class_member(app, class_id, student_id)
    teacher_id = make_user(app, role="teacher", school_id=school_id)
    _login(client, _email(app, teacher_id))
    resp = client.get(f"/classes/{class_id}/gradebook")
    assert resp.status_code == 200
    text = resp.get_data(as_text=True)
    assert "_gradebook.css" in text
    assert "gradebook-table" in text
    assert "data-label" in text


def test_table_component_css_has_modifiers():
    css = (TEMPLATES_DIR.parent / "static" / "css" / "components" / "_tables.css").read_text(encoding="utf-8")
    assert ".azad-table--compact" in css
    assert ".azad-table--striped" in css
    assert ".azad-table--hover" in css
    assert ".azad-table--card-view-mobile" in css
    assert "@media (max-width: 767px)" in css
