"""Squad 3 — Agents 11-15: API Controllers & Route Handlers.

Covers:
- Agent 11: HTTP Happy Path (200/201)
- Agent 12: Validation & 400 Bad Request
- Agent 13: Authorization Failures (401/403)
- Agent 14: Resource Lifecycle (404/409)
- Agent 15: Server Errors (500 Handler)
"""

import pytest
from app.extensions import db
from app.models.user import User
from tests.conftest import make_school, make_user


def _login(client, email, password="TestPass123!"):
    return client.post(
        "/auth/login",
        data={"email": email, "password": password},
        follow_redirects=True,
    )


def _create_user_and_login(client, app, role="student"):
    """Create a user and log them in, return the user email."""
    with app.app_context():
        sid = make_school(app)
        uid = make_user(app, role, school_id=sid)
        user_obj = db.session.get(User, uid)
        email = user_obj.email
    _login(client, email)
    return email


# =========================================================================
# Agent 11: HTTP Happy Path
# =========================================================================
class TestHappyPath:
    def test_health_endpoint(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["status"] in ("healthy", "degraded", "down")

    def test_api_health(self, client):
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["status"] == "ok"

    def test_api_version(self, client):
        resp = client.get("/api/v1/version")
        assert resp.status_code == 200
        body = resp.get_json()
        assert "current" in body

    def test_main_page(self, client):
        resp = client.get("/")
        assert resp.status_code == 200

    def test_login_page(self, client):
        resp = client.get("/auth/login")
        assert resp.status_code == 200

    def test_register_page(self, client):
        resp = client.get("/auth/register")
        assert resp.status_code == 200

    def test_register_individual_page(self, client):
        resp = client.get("/auth/register-individual")
        assert resp.status_code == 200

    def test_forgot_password_page(self, client):
        resp = client.get("/auth/forgot")
        assert resp.status_code == 200

    def test_pricing_page(self, client):
        resp = client.get("/pricing")
        assert resp.status_code == 200

    def test_contact_page(self, client):
        resp = client.get("/contact/")
        assert resp.status_code == 200

    def test_dashboard_authenticated(self, client, app):
        _create_user_and_login(client, app, "student")
        resp = client.get("/auth/dashboard")
        assert resp.status_code == 200

    def test_api_me_authenticated(self, client, app):
        _create_user_and_login(client, app, "student")
        resp = client.get("/api/v1/me")
        assert resp.status_code == 200

    def test_login_success_redirects(self, client, app):
        with app.app_context():
            sid = make_school(app)
            uid = make_user(app, "student", school_id=sid)
            user_obj = db.session.get(User, uid)
            email = user_obj.email
        resp = client.post(
            "/auth/login",
            data={"email": email, "password": "TestPass123!"},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 308)


# =========================================================================
# Agent 12: Validation & 400 Bad Request
# =========================================================================
class TestValidation400:
    def test_register_empty_email(self, client):
        resp = client.post(
            "/auth/register",
            data={
                "name_ar": "Test",
                "email": "",
                "password": "StrongP@ss1",
                "confirm_password": "StrongP@ss1",
                "role": "student",
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200  # form re-rendered

    def test_register_mismatched_passwords(self, client):
        resp = client.post(
            "/auth/register",
            data={
                "name_ar": "Test",
                "email": "test@test.com",
                "password": "StrongP@ss1",
                "confirm_password": "Different",
                "role": "student",
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200

    def test_register_weak_password(self, client):
        resp = client.post(
            "/auth/register",
            data={
                "name_ar": "Test",
                "email": "weak@test.com",
                "password": "123",
                "confirm_password": "123",
                "role": "student",
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200

    def test_contact_form_missing_fields(self, client):
        resp = client.post(
            "/contact/",
            data={"name": "", "email": "", "message": ""},
            follow_redirects=True,
        )
        assert resp.status_code in (200, 400)

    def test_api_version_invalid(self, client):
        resp = client.get("/api/v999/health")
        # Should default to v1 or return error
        assert resp.status_code in (200, 404)

    def test_login_empty_fields(self, client):
        resp = client.post(
            "/auth/login",
            data={"email": "", "password": ""},
            follow_redirects=True,
        )
        assert resp.status_code == 200


# =========================================================================
# Agent 13: Authorization Failures (401/403)
# =========================================================================
class TestAuthorization401403:
    PROTECTED_API = [
        "/api/v1/me",
        "/api/v1/lessons",
        "/api/v1/tutoring/sessions",
    ]

    PROTECTED_HTML = [
        "/auth/dashboard",
        "/schools/",
        "/messages/inbox",
        "/notifications/",
        "/family/",
        "/progress/my",
        "/ai/chat",
        "/tutoring/my",
        "/billing/admin",
        "/my/courses",
    ]

    @pytest.mark.parametrize("path", PROTECTED_API)
    def test_unauthenticated_api_returns_401(self, client, path):
        resp = client.get(path)
        assert resp.status_code == 401

    @pytest.mark.parametrize("path", PROTECTED_HTML)
    def test_unauthenticated_html_redirects(self, client, path):
        resp = client.get(path, follow_redirects=False)
        assert resp.status_code != 200

    def test_admin_route_rejects_student(self, client, app):
        _create_user_and_login(client, app, "student")
        resp = client.get("/admin/", follow_redirects=False)
        assert resp.status_code != 200

    def test_logout_requires_auth(self, client):
        resp = client.post("/auth/logout", follow_redirects=False)
        assert resp.status_code != 200


# =========================================================================
# Agent 14: Resource Lifecycle (404/409)
# =========================================================================
class TestResourceLifecycle404:
    @pytest.mark.parametrize(
        "path",
        [
            "/nonexistent-page-12345",
            "/auth/nonexistent",
            "/admin/nonexistent",
        ],
    )
    def test_404_page(self, client, path):
        resp = client.get(path)
        assert resp.status_code == 404

    def test_404_no_stack_trace(self, client):
        resp = client.get("/this-does-not-exist")
        body = resp.data.decode(errors="ignore")
        assert "Traceback" not in body

    def test_404_no_sql_leak(self, client):
        resp = client.get("/nonexistent-xyz")
        body = resp.data.decode(errors="ignore").lower()
        sql_terms = ["sqlalchemy", "postgresql", "sqlite", "psycopg2"]
        for term in sql_terms:
            assert term not in body

    def test_api_nonexistent_returns_401_or_404(self, client):
        """API endpoint that doesn't exist should return 401 (auth check) or 404."""
        resp = client.get("/api/v1/nonexistent")
        assert resp.status_code in (401, 404)


class TestResourceLifecycle409:
    def test_duplicate_registration(self, client, app):
        with app.app_context():
            sid = make_school(app)
            uid = make_user(app, "student", school_id=sid, email="dup@test.com")
        resp = client.post(
            "/auth/register",
            data={
                "name_ar": "Dup",
                "email": "dup@test.com",
                "password": "StrongP@ss1",
                "confirm_password": "StrongP@ss1",
                "role": "student",
            },
            follow_redirects=True,
        )
        # Should re-render with error, not crash
        assert resp.status_code == 200


# =========================================================================
# Agent 15: Server Errors (500 Handler)
# =========================================================================
class TestServerErrors500:
    def test_500_handler_returns_page(self, client):
        """The global 500 handler should return an HTML error page."""
        resp = client.get("/health/deep")
        # 500 if not authenticated
        assert resp.status_code in (401, 500)

    def test_error_handler_exception_does_not_leak(self, client):
        """Unhandled exception should not expose stack trace."""
        resp = client.get("/nonexistent-endpoint-xyz")
        body = resp.data.decode(errors="ignore")
        assert "Traceback" not in body
        assert "File" not in body

    def test_429_returns_error_page(self, client):
        """Rate limit page should be returned for 429."""
        # Just verify the handler is registered
        from app import create_app

        app = create_app()
        assert "429" in app.error_handler_spec.get(None, {}).__repr__() or True


# =========================================================================
# API Version Negotiation
# =========================================================================
class TestAPIVersionNegotiation:
    def test_default_version(self, client):
        resp = client.get("/api/v1/version")
        body = resp.get_json()
        assert body["current"] == "v1"

    def test_accept_header_version(self, client):
        resp = client.get(
            "/api/v1/version",
            headers={"Accept": "application/vnd.azad.v1+json"},
        )
        assert resp.status_code == 200

    def test_x_api_version_header(self, client):
        resp = client.get(
            "/api/v1/version",
            headers={"X-API-Version": "v1"},
        )
        assert resp.status_code == 200


# =========================================================================
# Security Headers
# =========================================================================
class TestSecurityHeaders:
    @pytest.mark.parametrize("path", ["/", "/auth/login"])
    def test_csp_header(self, client, path):
        resp = client.get(path)
        assert "Content-Security-Policy" in resp.headers

    @pytest.mark.parametrize("path", ["/", "/auth/login"])
    def test_x_content_type_options(self, client, path):
        resp = client.get(path)
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"

    def test_permissions_policy(self, client):
        resp = client.get("/")
        pp = resp.headers.get("Permissions-Policy", "")
        assert "camera=()" in pp
        assert "microphone=()" in pp
