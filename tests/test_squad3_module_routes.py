"""SQUAD 3 EXTRA: Module route tests — every HTML blueprint."""

import pytest
from app.extensions import db
from app.models.user import User, UserRole, UserApprovalStatus
from app.core.security import hash_password
from tests.conftest import make_school, make_user


def _login(client, email, password="TestPass123!"):
    return client.post("/auth/login", data={"email": email, "password": password}, follow_redirects=True)


def _create_and_login(client, app, role="student"):
    with app.app_context():
        sid = make_school(app)
        uid = make_user(app, role, school_id=sid)
        email = db.session.get(User, uid).email
    _login(client, email)
    return email


# ── Main routes ──
class TestMainRoutes:
    def test_index(self, client):
        resp = client.get("/")
        assert resp.status_code == 200

    def test_pricing(self, client):
        resp = client.get("/pricing")
        assert resp.status_code == 200

    def test_contact(self, client):
        resp = client.get("/contact/")
        assert resp.status_code == 200


# ── Auth routes ──
class TestAuthRoutes:
    def test_login_page(self, client):
        resp = client.get("/auth/login")
        assert resp.status_code == 200

    def test_register_page(self, client):
        resp = client.get("/auth/register")
        assert resp.status_code == 200

    def test_forgot_password(self, client):
        resp = client.get("/auth/forgot")
        assert resp.status_code == 200

    def test_register_individual_page(self, client):
        resp = client.get("/auth/register-individual")
        assert resp.status_code == 200

    def test_dashboard_unauthenticated(self, client):
        resp = client.get("/auth/dashboard", follow_redirects=False)
        assert resp.status_code != 200

    def test_login_success(self, client, app):
        _create_and_login(client, app, "student")
        resp = client.get("/auth/dashboard")
        assert resp.status_code == 200

    def test_logout(self, client, app):
        _create_and_login(client, app, "student")
        resp = client.post("/auth/logout", follow_redirects=False)
        assert resp.status_code in (302, 303, 307, 308)


# ── Admin routes ──
class TestAdminRoutes:
    def test_admin_unauthenticated(self, client):
        resp = client.get("/admin/", follow_redirects=False)
        assert resp.status_code != 200

    def test_admin_student_forbidden(self, client, app):
        _create_and_login(client, app, "student")
        resp = client.get("/admin/", follow_redirects=False)
        assert resp.status_code != 200

    def test_admin_super_admin(self, client, app):
        _create_and_login(client, app, "super_admin")
        resp = client.get("/admin/")
        assert resp.status_code == 200


# ── Schools routes ──
class TestSchoolRoutes:
    def test_schools_unauthenticated(self, client):
        resp = client.get("/schools/", follow_redirects=False)
        assert resp.status_code != 200


# ── Messages routes ──
class TestMessageRoutes:
    def test_inbox_unauthenticated(self, client):
        resp = client.get("/messages/inbox", follow_redirects=False)
        assert resp.status_code != 200


# ── Notifications routes ──
class TestNotificationRoutes:
    def test_notifications_unauthenticated(self, client):
        resp = client.get("/notifications/", follow_redirects=False)
        assert resp.status_code != 200


# ── Family routes ──
class TestFamilyRoutes:
    def test_family_unauthenticated(self, client):
        resp = client.get("/family/", follow_redirects=False)
        assert resp.status_code != 200


# ── Progress routes ──
class TestProgressRoutes:
    def test_progress_unauthenticated(self, client):
        resp = client.get("/progress/my", follow_redirects=False)
        assert resp.status_code != 200


# ── Billing routes ──
class TestBillingRoutes:
    def test_billing_unauthenticated(self, client):
        resp = client.get("/billing/admin", follow_redirects=False)
        assert resp.status_code != 200


# ── AI routes ──
class TestAIRoutes:
    def test_ai_unauthenticated(self, client):
        resp = client.get("/ai/chat", follow_redirects=False)
        assert resp.status_code != 200


# ── Tutoring routes ──
class TestTutoringRoutes:
    def test_tutoring_unauthenticated(self, client):
        resp = client.get("/tutoring/my", follow_redirects=False)
        assert resp.status_code != 200


# ── My courses ──
class TestMyCourses:
    def test_my_courses_unauthenticated(self, client):
        resp = client.get("/my/courses", follow_redirects=False)
        assert resp.status_code != 200


# ── Grades routes ──
class TestGradeRoutes:
    def test_grades_redirect(self, client):
        resp = client.get("/grades", follow_redirects=False)
        assert resp.status_code in (301, 302, 308)

    def test_content_redirect(self, client):
        resp = client.get("/content", follow_redirects=False)
        assert resp.status_code in (301, 302, 308)

    def test_assessment_redirect(self, client):
        resp = client.get("/assessment", follow_redirects=False)
        assert resp.status_code in (301, 302, 308)


# ── API legacy redirect ──
class TestAPILegacy:
    def test_api_health_legacy(self, client):
        resp = client.get("/api/health", follow_redirects=False)
        assert resp.status_code in (307, 200)


# ── Error handlers ──
class TestErrorHandlers:
    def test_404_handler(self, client):
        resp = client.get("/this-page-does-not-exist-12345")
        assert resp.status_code == 404

    def test_404_no_traceback(self, client):
        resp = client.get("/nonexistent-12345")
        body = resp.data.decode(errors="ignore")
        assert "Traceback" not in body

    def test_404_no_sql_leak(self, client):
        resp = client.get("/nonexistent-xyz")
        body = resp.data.decode(errors="ignore").lower()
        assert "sqlalchemy" not in body
        assert "postgresql" not in body
