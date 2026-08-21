"""Sprint 1 ERP UI/UX remediation tests."""

from __future__ import annotations

import re
from pathlib import Path

from app.extensions import db
from app.models.user import User
from tests.conftest import (
    make_class,
    make_class_member,
    make_grade,
    make_school,
    make_subject,
    make_user,
)

TEMPLATES_DIR = Path(__file__).parent.parent / "app" / "templates"
SELECTED_TEMPLATES = [
    "billing/class_billing.html",
    "grades/gradebook.html",
    "assessment/attempt.html",
    "landing.html",
    "base.html",
    "billing/invoice.html",
    "grades/report_card.html",
]


def _login(client, email: str, password: str = "TestPass123!"):
    return client.post(
        "/auth/login",
        data={"email": email, "password": password, "remember": "y"},
        follow_redirects=True,
    )


def _email(app, user_id):
    with app.app_context():
        return User.query.get(user_id).email


def test_search_api_requires_auth(client):
    resp = client.get("/api/v1/search?q=test")
    assert resp.status_code == 401


def test_search_api_validates_query(app, client):
    user_id = make_user(app, role="super_admin")
    _login(client, _email(app, user_id))
    resp = client.get("/api/v1/search?q=a")
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["error"]["code"] == "QUERY_TOO_SHORT"


def test_search_api_returns_grouped_results(app, client):
    user_id = make_user(app, role="super_admin")
    _login(client, _email(app, user_id))
    resp = client.get("/api/v1/search?q=مدرسة&limit=5")
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    for key in ("schools", "users", "classes", "subscriptions"):
        assert key in data
        assert isinstance(data[key], list)


def test_base_html_contains_search_script_and_modal_skeleton(app, client):
    user_id = make_user(app, role="super_admin")
    _login(client, _email(app, user_id))
    resp = client.get("/auth/dashboard")
    assert resp.status_code == 200
    text = resp.get_data(as_text=True)
    assert "AzadSearchLabels" in text
    assert "data-search-open" in text


def test_navbar_has_user_dropdown_and_search_trigger(app, client):
    user_id = make_user(app, role="super_admin")
    _login(client, _email(app, user_id))
    resp = client.get("/auth/dashboard")
    text = resp.get_data(as_text=True)
    assert "data-user-toggle" in text
    assert "data-user-menu" in text
    assert "data-theme-toggle" in text
    assert "data-search-open" in text


def test_admin_sidebar_has_theme_toggle_footer(app, client):
    user_id = make_user(app, role="super_admin")
    _login(client, _email(app, user_id))
    resp = client.get("/admin/")
    assert resp.status_code == 200
    text = resp.get_data(as_text=True)
    assert "admin-sidebar__footer" in text
    assert "data-theme-toggle" in text


def test_no_inline_style_attributes_in_selected_templates():
    style_re = re.compile(r'<[^>]+\sstyle\s*=\s*"[^"]*"', re.IGNORECASE)
    for rel in SELECTED_TEMPLATES:
        path = TEMPLATES_DIR / rel
        assert path.exists(), f"Template missing: {rel}"
        text = path.read_text(encoding="utf-8")
        matches = style_re.findall(text)
        assert not matches, f"{rel} contains inline style attribute(s): {matches[:3]}"


def test_no_js_confirm_calls_in_templates():
    confirm_re = re.compile(r"(?<!\w)confirm\s*\(", re.IGNORECASE)
    for path in TEMPLATES_DIR.rglob("*.html"):
        text = path.read_text(encoding="utf-8")
        # Skip WTForms confirm() field helper calls
        cleaned = re.sub(r"\{\{\s*form\.confirm\([^\)]*\)\s*\}\}", "", text)
        matches = confirm_re.findall(cleaned)
        assert not matches, f"{path.relative_to(TEMPLATES_DIR)} still uses JS confirm(): {matches}"


def test_data_confirm_attributes_replace_inline_confirm():
    """Key delete/approve forms should now use data-confirm."""
    paths = [
        TEMPLATES_DIR / "admin" / "backups.html",
        TEMPLATES_DIR / "admin" / "pending_payments.html",
        TEMPLATES_DIR / "calendar" / "index.html",
        TEMPLATES_DIR / "content" / "shared_library.html",
    ]
    for path in paths:
        text = path.read_text(encoding="utf-8")
        assert "data-confirm" in text, f"{path} missing data-confirm"
        assert "return confirm(" not in text, f"{path} still has return confirm("


def test_quiz_attempt_page_has_progress_timer_flag(app, client):
    school_id = make_school(app)
    grade_id = make_grade(app, school_id)
    subject_id = make_subject(app)
    class_id = make_class(app, school_id, grade_id, subject_id)
    student_id = make_user(app, role="student", school_id=school_id)
    student_email = _email(app, student_id)
    make_class_member(app, class_id, student_id)

    with app.app_context():
        from app.models.assessment import Question, Quiz

        quiz = Quiz(class_id=class_id, title="اختبار Sprint 1", duration_min=30)
        db.session.add(quiz)
        db.session.flush()
        quiz.questions.append(
            Question(
                quiz_id=quiz.id,
                type="true_false",
                prompt="س 1",
                mark=1,
                correct_answer={"value": True},
                sort_order=1,
            )
        )
        db.session.commit()
        from app.models.assessment import QuizAttempt

        attempt = QuizAttempt(quiz_id=quiz.id, student_id=student_id, attempt_no=1)
        db.session.add(attempt)
        db.session.commit()
        attempt_id = attempt.id

    _login(client, student_email)
    resp = client.get(f"/classes/attempt/{attempt_id}")
    assert resp.status_code == 200
    text = resp.get_data(as_text=True)
    assert "quiz-progress-bar" in text
    assert "quiz-timer" in text
    assert "data-flag-question" in text
    assert "data-confirm" in text
    assert "quiz.js" in text


def test_quiz_timer_respects_duration_min():
    """Ensure timer markup carries the quiz duration."""
    path = TEMPLATES_DIR / "assessment" / "attempt.html"
    text = path.read_text(encoding="utf-8")
    assert "data-duration-min" in text
    assert "{{ quiz.duration_min or 0 }}" in text
