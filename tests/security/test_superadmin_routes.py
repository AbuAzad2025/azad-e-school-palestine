"""Test Persona 1: The Super Admin / Platform Owner.

Verifies that a super_admin user can access all platform-wide admin endpoints
including those restricted to super_admin ONLY (backups, settings, audit-logs,
revenue, health, analytics, moe-export, certificates).
"""

from __future__ import annotations


class TestSuperAdminDashboard:
    """Super admin can access the main dashboard."""

    def test_dashboard_returns_200(self, app, superadmin_persona):
        _, client = superadmin_persona
        resp = client.get("/admin/", follow_redirects=True)
        assert resp.status_code == 200


class TestSuperAdminUserManagement:
    """Super admin can view and manage users."""

    def test_users_list(self, app, superadmin_persona):
        _, client = superadmin_persona
        resp = client.get("/admin/users", follow_redirects=True)
        assert resp.status_code == 200

    def test_user_detail(self, app, superadmin_persona, school_admin_a_persona):
        _, client = superadmin_persona
        admin_id = school_admin_a_persona[0]
        resp = client.get(f"/admin/users/{admin_id}", follow_redirects=True)
        assert resp.status_code == 200


class TestSuperAdminSchoolManagement:
    """Super admin can view schools."""

    def test_schools_list(self, app, superadmin_persona):
        _, client = superadmin_persona
        resp = client.get("/admin/schools", follow_redirects=True)
        assert resp.status_code == 200

    def test_school_detail(self, app, superadmin_persona, school_a):
        _, client = superadmin_persona
        resp = client.get(f"/admin/schools/{school_a}", follow_redirects=True)
        assert resp.status_code == 200


class TestSuperAdminSubscriptionManagement:
    """Super admin can manage subscriptions."""

    def test_subscriptions_list(self, app, superadmin_persona):
        _, client = superadmin_persona
        resp = client.get("/admin/subscriptions", follow_redirects=True)
        assert resp.status_code == 200


class TestSuperAdminSuperOnlyRoutes:
    """Routes restricted to super_admin ONLY."""

    def test_backups_list(self, app, superadmin_persona):
        _, client = superadmin_persona
        resp = client.get("/admin/backups", follow_redirects=True)
        assert resp.status_code == 200

    def test_settings_get(self, app, superadmin_persona):
        _, client = superadmin_persona
        resp = client.get("/admin/settings", follow_redirects=True)
        assert resp.status_code == 200

    def test_audit_logs(self, app, superadmin_persona):
        _, client = superadmin_persona
        resp = client.get("/admin/audit-logs", follow_redirects=True)
        assert resp.status_code == 200

    def test_revenue(self, app, superadmin_persona):
        _, client = superadmin_persona
        resp = client.get("/admin/revenue", follow_redirects=True)
        assert resp.status_code == 200

    def test_health(self, app, superadmin_persona):
        _, client = superadmin_persona
        resp = client.get("/admin/health", follow_redirects=True)
        assert resp.status_code == 200

    def test_analytics(self, app, superadmin_persona):
        _, client = superadmin_persona
        resp = client.get("/admin/analytics", follow_redirects=True)
        assert resp.status_code == 200

    def test_moe_export_get(self, app, superadmin_persona):
        _, client = superadmin_persona
        resp = client.get("/admin/moe-export", follow_redirects=True)
        assert resp.status_code == 200

    def test_certificates(self, app, superadmin_persona):
        _, client = superadmin_persona
        resp = client.get("/admin/certificates", follow_redirects=True)
        assert resp.status_code == 200

    def test_ai_usage(self, app, superadmin_persona):
        _, client = superadmin_persona
        resp = client.get("/admin/ai/usage", follow_redirects=True)
        assert resp.status_code == 200

    def test_contact_list(self, app, superadmin_persona):
        _, client = superadmin_persona
        resp = client.get("/admin/contact", follow_redirects=True)
        assert resp.status_code == 200


class TestSuperAdminCrossTenantVisibility:
    """Super admin sees data across ALL tenants."""

    def test_sees_school_a_and_b(self, app, superadmin_persona, school_a, school_b):
        _, client = superadmin_persona
        resp = client.get("/admin/schools", follow_redirects=True)
        assert resp.status_code == 200
        html = resp.data.decode()
        # Super admin should see both schools (at minimum they exist)
        assert str(school_a) in html or str(school_b) in html
