"""Test Persona 3: The School Admin (Tenant-Bound).

The admin blueprint has a ``before_request`` hook that restricts school_admin
to ONLY two routes: ``/admin/school-admin`` (their own dashboard) and
``/admin/impersonate/exit``.  All other ``/admin/*`` routes require
``super_admin``.

Verifies that:
1. School admins CAN access their own school_admin_dashboard
2. School admins CANNOT access any super_admin-only routes
3. School admins CANNOT impersonate users
"""

from __future__ import annotations


class TestSchoolAdminAllowedRoutes:
    """School admin can access school_admin_dashboard (scoped to own school)."""

    def test_school_admin_dashboard(self, app, school_admin_a_persona):
        _, client = school_admin_a_persona
        resp = client.get("/admin/school-admin", follow_redirects=True)
        assert resp.status_code == 200


class TestSchoolAdminDeniedSuperAdminRoutes:
    """School admin CANNOT access super_admin-only routes (before_request hook)."""

    def test_main_dashboard_forbidden(self, app, school_admin_a_persona):
        _, client = school_admin_a_persona
        resp = client.get("/admin/", follow_redirects=False)
        assert resp.status_code == 403

    def test_users_list_forbidden(self, app, school_admin_a_persona):
        _, client = school_admin_a_persona
        resp = client.get("/admin/users", follow_redirects=False)
        assert resp.status_code == 403

    def test_schools_list_forbidden(self, app, school_admin_a_persona):
        _, client = school_admin_a_persona
        resp = client.get("/admin/schools", follow_redirects=False)
        assert resp.status_code == 403

    def test_subscriptions_forbidden(self, app, school_admin_a_persona):
        _, client = school_admin_a_persona
        resp = client.get("/admin/subscriptions", follow_redirects=False)
        assert resp.status_code == 403

    def test_payments_pending_forbidden(self, app, school_admin_a_persona):
        _, client = school_admin_a_persona
        resp = client.get("/admin/payments/pending", follow_redirects=False)
        assert resp.status_code == 403

    def test_registrations_pending_forbidden(self, app, school_admin_a_persona):
        _, client = school_admin_a_persona
        resp = client.get("/admin/registrations/pending", follow_redirects=False)
        assert resp.status_code == 403

    def test_backups_forbidden(self, app, school_admin_a_persona):
        _, client = school_admin_a_persona
        resp = client.get("/admin/backups", follow_redirects=False)
        assert resp.status_code == 403

    def test_settings_forbidden(self, app, school_admin_a_persona):
        _, client = school_admin_a_persona
        resp = client.get("/admin/settings", follow_redirects=False)
        assert resp.status_code == 403

    def test_audit_logs_forbidden(self, app, school_admin_a_persona):
        _, client = school_admin_a_persona
        resp = client.get("/admin/audit-logs", follow_redirects=False)
        assert resp.status_code == 403

    def test_revenue_forbidden(self, app, school_admin_a_persona):
        _, client = school_admin_a_persona
        resp = client.get("/admin/revenue", follow_redirects=False)
        assert resp.status_code == 403

    def test_health_forbidden(self, app, school_admin_a_persona):
        _, client = school_admin_a_persona
        resp = client.get("/admin/health", follow_redirects=False)
        assert resp.status_code == 403

    def test_moe_export_forbidden(self, app, school_admin_a_persona):
        _, client = school_admin_a_persona
        resp = client.get("/admin/moe-export", follow_redirects=False)
        assert resp.status_code == 403

    def test_certificates_forbidden(self, app, school_admin_a_persona):
        _, client = school_admin_a_persona
        resp = client.get("/admin/certificates", follow_redirects=False)
        assert resp.status_code == 403

    def test_backups_create_post_forbidden(self, app, school_admin_a_persona):
        _, client = school_admin_a_persona
        resp = client.post("/admin/backups/create", follow_redirects=False)
        assert resp.status_code == 403

    def test_settings_post_forbidden(self, app, school_admin_a_persona):
        _, client = school_admin_a_persona
        resp = client.post("/admin/settings", follow_redirects=False)
        assert resp.status_code == 403


class TestSchoolAdminTenantIsolation:
    """School admin cannot access super_admin-only cross-tenant routes."""

    def test_school_b_admin_blocked_from_admin_routes(self, app, school_admin_b_persona):
        """School B admin cannot access any super_admin-only admin routes."""
        _, client = school_admin_b_persona
        resp = client.get("/admin/users", follow_redirects=False)
        assert resp.status_code == 403
        resp = client.get("/admin/schools", follow_redirects=False)
        assert resp.status_code == 403
        resp = client.get("/admin/payments/pending", follow_redirects=False)
        assert resp.status_code == 403

    def test_student_a_cannot_be_accessed_by_school_b_admin(self, app, school_admin_b_persona, student_a_persona):
        """School B admin cannot access School A student details via admin panel."""
        _, client = school_admin_b_persona
        student_id = student_a_persona[0]
        resp = client.get(f"/admin/users/{student_id}", follow_redirects=False)
        assert resp.status_code == 403


class TestSchoolAdminCannotImpersonate:
    """School admin cannot impersonate users (super_admin only)."""

    def test_impersonate_forbidden(self, app, school_admin_a_persona, student_a_persona):
        _, client = school_admin_a_persona
        student_id = student_a_persona[0]
        resp = client.post(
            f"/admin/users/{student_id}/impersonate",
            follow_redirects=False,
        )
        assert resp.status_code == 403
