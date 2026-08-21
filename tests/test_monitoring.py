"""Monitoring & alerting tests — Phase 8"""
from pathlib import Path
import pytest


BASE_DIR = Path.cwd()


class TestSentryModule:
    """Sentry wrapper module exists and exposes expected helpers."""

    def test_sentry_module_exists(self):
        path = BASE_DIR / "app" / "core" / "sentry.py"
        assert path.exists() and path.stat().st_size > 0

    def test_sentry_exports_init_and_helpers(self):
        from app.core.sentry import init_sentry, set_sentry_user, capture_exception, capture_message

        assert callable(init_sentry)
        assert callable(set_sentry_user)
        assert callable(capture_exception)
        assert callable(capture_message)

    def test_sentry_imported_in_app_factory(self):
        app_init = (BASE_DIR / "app" / "__init__.py").read_text(encoding="utf-8")
        assert "from app.core.sentry import init_sentry" in app_init

    def test_sentry_config_keys_in_config(self):
        config = (BASE_DIR / "config.py").read_text(encoding="utf-8")
        assert "SENTRY_DSN" in config


class TestHealthEndpoints:
    """Health endpoints exist for uptime monitoring."""

    def test_health_routes_registered(self):
        app_init = (BASE_DIR / "app" / "__init__.py").read_text(encoding="utf-8")
        assert '"/health"' in app_init
        assert '"/health/deep"' in app_init


class TestRunbook:
    """Incident runbook is documented."""

    def test_runbook_exists(self):
        path = BASE_DIR / "docs" / "runbook.md"
        assert path.exists() and path.stat().st_size > 0

    def test_runbook_covers_key_scenarios(self):
        content = (BASE_DIR / "docs" / "runbook.md").read_text(encoding="utf-8")
        assert "SEV-1" in content
        assert "rollback" in content.lower()
        assert "health" in content.lower()
        assert "journalctl" in content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])