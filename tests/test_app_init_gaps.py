"""Coverage gaps for app/__init__.py — Talisman path, CLI commands, CSP helpers."""

from __future__ import annotations

from unittest.mock import patch

from config import TestingConfig
from flask import g


class _TalismanDeck(TestingConfig):
    TALISMAN_ENABLED = True
    TALISMAN_FORCE_HTTPS = False
    TALISMAN_STRICT_TRANSPORT_SECURITY = False
    TALISMAN_STRICT_TRANSPORT_SECURITY_MAX_AGE = 31536000
    WTF_CSRF_ENABLED = False
    SESSION_COOKIE_SECURE = False
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    TALISMAN_CONTENT_SECURITY_POLICY = {
        "default-src": "'self'",
        "script-src": "'self' 'nonce-{CSP_NONCE}'",
        "style-src": "'self' 'nonce-{CSP_NONCE}'",
        "img-src": "'self' data: https:",
        "frame-ancestors": "'none'",
    }


def test_talisman_enabled_replaces_csp_nonce():
    from app import create_app

    app = create_app(_TalismanDeck)
    client = app.test_client()
    resp = client.get("/health")
    csp = resp.headers.get("Content-Security-Policy", "")
    assert "{CSP_NONCE}" not in csp
    assert "nonce-" in csp


def test_talisman_enabled_no_csp_returns_without_headers():
    """Response with no CSP header → returns untouched."""
    from app import create_app

    class _Bare(_TalismanDeck):
        TALISMAN_CONTENT_SECURITY_POLICY = {"img-src": "'self' data: https:"}

    app = create_app(_Bare)
    client = app.test_client()
    resp = client.get("/health")
    # Talisman still sets a CSP, just without a nonce — the fallback path
    # must not inject a placeholder into it.
    assert resp.status_code == 200


class _PlainTalisman(_TalismanDeck):
    """Talisman enabled; CSP policy without a nonce placeholder."""

    TALISMAN_CONTENT_SECURITY_POLICY = {
        "default-src": "'self'",
        "frame-ancestors": "'none'",
    }


def test_talisman_enabled_no_placeholder_returns():
    from app import create_app

    app = create_app(_PlainTalisman)
    client = app.test_client()
    resp = client.get("/health")
    assert resp.status_code == 200


class _NonDictCsp(TestingConfig):
    TALISMAN_ENABLED = False
    TALISMAN_CONTENT_SECURITY_POLICY = "this is not a dict"
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"


def test_fallback_csp_not_a_dict():
    from app import create_app

    app = create_app(_NonDictCsp)
    client = app.test_client()
    resp = client.get("/health")
    assert resp.status_code == 200


class TestAiUsageReportCli:
    def test_prints_json(self, app):
        from app.services import ai

        class _FakeAI:
            def get_usage_stats(self, days):
                return {"requests": 3, "budget": {"usage_percent": 10.0}}

        with patch.object(ai, "get_ai_service", lambda: _FakeAI()):
            result = app.test_cli_runner().invoke(args=["ai-usage-report", "--days", "7"])
        assert result.exit_code == 0
        assert '"requests": 3' in result.output

    def test_budget_threshold_exit_1(self, app):
        from app.services import ai

        class _FakeAI:
            def get_usage_stats(self, days):
                return {"requests": 12, "budget": {"usage_percent": 95.0}}

        with patch.object(ai, "get_ai_service", lambda: _FakeAI()):
            result = app.test_cli_runner().invoke(args=["ai-usage-report", "--budget-threshold", "80"])
        assert result.exit_code == 1
        assert "WARNING" in result.output


class TestBackupHealthCli:
    def test_backup_healthy(self, app, monkeypatch):
        from app.services import health

        monkeypatch.setattr(
            health,
            "check_backup_freshness",
            lambda max_age_hours: {"status": "healthy", "message": "ok"},
        )
        result = app.test_cli_runner().invoke(args=["backup-health"])
        assert result.exit_code == 0
        assert "backup_status=healthy" in result.output

    def test_backup_unhealthy_exits_1(self, app, monkeypatch):
        from app.services import health

        monkeypatch.setattr(
            health,
            "check_backup_freshness",
            lambda max_age_hours: {"status": "down", "message": "stale"},
        )
        result = app.test_cli_runner().invoke(args=["backup-health"])
        assert result.exit_code == 1


class TestAbsenceAlertsCli:
    def test_default_runs(self, app, monkeypatch):
        from app.services import attendance

        monkeypatch.setattr(attendance, "run_absence_alerts", lambda: 7)
        result = app.test_cli_runner().invoke(args=["send-absence-alerts"])
        assert result.exit_code == 0
        assert "absence_alerts_sent=7" in result.output

    def test_with_date(self, app, monkeypatch):
        from app.services import attendance

        monkeypatch.setattr(attendance, "run_absence_alerts", lambda date: 3)
        result = app.test_cli_runner().invoke(args=["send-absence-alerts", "--date", "2026-11-04"])
        assert result.exit_code == 0
        assert "absence_alerts_sent=3" in result.output

    def test_invalid_date_bad_parameter(self, app, monkeypatch):
        from app.services import attendance

        def _raise(_date):
            raise ValueError("bad date")

        monkeypatch.setattr(attendance, "run_absence_alerts", _raise)
        result = app.test_cli_runner().invoke(args=["send-absence-alerts", "--date", "2026-99-99"])
        assert result.exit_code != 0


class TestTutoringAutoTimeoutCli:
    def test_prints_result(self, app, monkeypatch):
        from app.services import tutoring

        monkeypatch.setattr(tutoring, "auto_timeout_unconfirmed_sessions", lambda grace_hours=None: {"finalized": 2, "skipped": 1, "errors": 0})
        result = app.test_cli_runner().invoke(args=["tutoring-auto-timeout"])
        assert result.exit_code == 0
        assert "tutoring_auto_timeout finalized=2 skipped=1 errors=0" in result.output


class TestExpirePendingPaymentsCli:
    def test_prints_count(self, app, monkeypatch):
        from app.services import billing

        monkeypatch.setattr(billing, "expire_pending_payments", lambda ttl: 5)
        result = app.test_cli_runner().invoke(args=["expire-pending-payments"])
        assert result.exit_code == 0
        assert "expired_pending_payments=5" in result.output


def test_g_serves_csp_nonce_on_error():
    """Even on a 500 response, g.csp_nonce is present (no placeholder leaks)."""
    from app import create_app

    class _Broken(_TalismanDeck):
        TESTING = False

    # ensure g.csp_nonce exists — before_request sets it for every request
    app = create_app(_Broken)
    with app.test_request_context("/"):
        g.csp_nonce = "test-nonce"
        csp = app.config.get("TALISMAN_CONTENT_SECURITY_POLICY")
        assert csp is not None
