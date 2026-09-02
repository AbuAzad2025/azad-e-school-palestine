"""Test Persona 2: The Unauthenticated Attacker.

Verifies that ALL protected endpoints reject unauthenticated requests with
401 Unauthorized or redirect to login. Covers admin, content, grades,
billing, family, progress, messages, export, and school-manage routes.
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Admin endpoints — should all return 401 or redirect (302) when unauthenticated
# ---------------------------------------------------------------------------

class TestUnauthAdmin:
    """Unauthenticated access to admin routes."""

    @pytest.mark.parametrize(
        "method, path",
        [
            ("GET", "/admin/"),
            ("GET", "/admin/users"),
            ("GET", "/admin/schools"),
            ("GET", "/admin/subscriptions"),
            ("GET", "/admin/payments/pending"),
            ("GET", "/admin/ai/usage"),
            ("GET", "/admin/backups"),
            ("GET", "/admin/settings"),
            ("GET", "/admin/registrations/pending"),
            ("GET", "/admin/revenue"),
            ("GET", "/admin/health"),
            ("GET", "/admin/analytics"),
            ("GET", "/admin/moe-export"),
            ("GET", "/admin/certificates"),
            ("GET", "/admin/audit-logs"),
            ("GET", "/admin/contact"),
        ],
    )
    def test_admin_get_rejects_unauth(self, client, method, path):
        resp = client.get(path, follow_redirects=False)
        assert resp.status_code in (401, 302), f"{method} {path} returned {resp.status_code}"

    @pytest.mark.parametrize(
        "method, path",
        [
            ("POST", "/admin/users/999/toggle"),
            ("POST", "/admin/bulk-action"),
            ("POST", "/admin/users/999/impersonate"),
            ("POST", "/admin/impersonate/exit"),
            ("POST", "/admin/subscriptions/999/cancel"),
            ("POST", "/admin/payments/999/approve"),
            ("POST", "/admin/payments/999/reject"),
            ("POST", "/admin/backups/create"),
            ("POST", "/admin/settings"),
            ("POST", "/admin/registrations/999/approve"),
            ("POST", "/admin/registrations/999/reject"),
            ("POST", "/admin/moe-export"),
        ],
    )
    def test_admin_post_rejects_unauth(self, client, method, path):
        resp = client.post(path, follow_redirects=False)
        assert resp.status_code in (401, 302), f"{method} {path} returned {resp.status_code}"


# ---------------------------------------------------------------------------
# Content endpoints
# ---------------------------------------------------------------------------

class TestUnauthContent:
    """Unauthenticated access to content routes."""

    @pytest.mark.parametrize(
        "path",
        [
            "/classes/1/lessons",
            "/classes/1/lessons/new",
            "/classes/shared",
            "/classes/offline",
        ],
    )
    def test_content_rejects_unauth(self, client, path):
        resp = client.get(path, follow_redirects=False)
        assert resp.status_code in (401, 302), f"GET {path} returned {resp.status_code}"

    def test_content_post_rejects_unauth(self, client):
        resp = client.post("/classes/1/lessons", follow_redirects=False)
        assert resp.status_code in (401, 302)


# ---------------------------------------------------------------------------
# Grades endpoints
# ---------------------------------------------------------------------------

class TestUnauthGrades:
    """Unauthenticated access to grades routes."""

    @pytest.mark.parametrize(
        "path",
        [
            "/classes/1/assignments",
            "/classes/1/gradebook",
            "/classes/1/attendance",
        ],
    )
    def test_grades_rejects_unauth(self, client, path):
        resp = client.get(path, follow_redirects=False)
        assert resp.status_code in (401, 302), f"GET {path} returned {resp.status_code}"

    def test_grades_post_rejects_unauth(self, client):
        resp = client.post("/classes/1/assignments", follow_redirects=False)
        assert resp.status_code in (401, 302)


# ---------------------------------------------------------------------------
# Billing endpoints
# ---------------------------------------------------------------------------

class TestUnauthBilling:
    """Unauthenticated access to billing routes."""

    def test_billing_get_rejects_unauth(self, client):
        resp = client.get("/billing/1", follow_redirects=False)
        assert resp.status_code in (401, 302)

    def test_billing_post_subscribe_rejects_unauth(self, client):
        resp = client.post("/billing/1/subscribe", follow_redirects=False)
        assert resp.status_code in (401, 302)

    def test_billing_admin_rejects_unauth(self, client):
        resp = client.get("/billing/admin", follow_redirects=False)
        assert resp.status_code in (401, 302)


# ---------------------------------------------------------------------------
# Family endpoints
# ---------------------------------------------------------------------------

class TestUnauthFamily:
    """Unauthenticated access to family routes."""

    @pytest.mark.parametrize(
        "path",
        [
            "/family/",
            "/family/generate",
            "/family/children/999/progress",
            "/family/children/999/grades",
        ],
    )
    def test_family_rejects_unauth(self, client, path):
        resp = client.get(path, follow_redirects=False)
        assert resp.status_code in (401, 302), f"GET {path} returned {resp.status_code}"


# ---------------------------------------------------------------------------
# Progress endpoints
# ---------------------------------------------------------------------------

class TestUnauthProgress:
    """Unauthenticated access to progress routes."""

    def test_progress_my_rejects_unauth(self, client):
        resp = client.get("/progress/my", follow_redirects=False)
        assert resp.status_code in (401, 302)

    def test_progress_class_rejects_unauth(self, client):
        resp = client.get("/progress/class/1", follow_redirects=False)
        assert resp.status_code in (401, 302)


# ---------------------------------------------------------------------------
# Export endpoints
# ---------------------------------------------------------------------------

class TestUnauthExport:
    """Unauthenticated access to export routes."""

    def test_export_rejects_unauth(self, client):
        resp = client.get("/export/1/grades", follow_redirects=False)
        assert resp.status_code in (401, 302)


# ---------------------------------------------------------------------------
# Messages endpoints
# ---------------------------------------------------------------------------

class TestUnauthMessages:
    """Unauthenticated access to messages routes."""

    def test_messages_inbox_rejects_unauth(self, client):
        resp = client.get("/messages/inbox", follow_redirects=False)
        assert resp.status_code in (401, 302)


# ---------------------------------------------------------------------------
# Media endpoints
# ---------------------------------------------------------------------------

class TestUnauthMedia:
    """Unauthenticated access to media streaming."""

    def test_stream_rejects_unauth(self, client):
        resp = client.get("/media/stream/1/master.m3u8", follow_redirects=False)
        assert resp.status_code in (401, 302)
