"""Mobile app preparation tests — Phase 9"""

from pathlib import Path

import pytest

BASE_DIR = Path.cwd()


class TestOpenAPI:
    """OpenAPI/Swagger endpoints and docs are available."""

    def test_openapi_config_module_exists(self):
        path = BASE_DIR / "app" / "core" / "openapi.py"
        assert path.exists() and path.stat().st_size > 0

    def test_openapi_routes_registered(self):
        app_init = (BASE_DIR / "app" / "__init__.py").read_text(encoding="utf-8")
        assert "init_swagger" in app_init
        openapi = (BASE_DIR / "app" / "core" / "openapi.py").read_text(encoding="utf-8")
        assert "openapi.json" in openapi
        assert "apispec_v1" in openapi


class TestCORS:
    """CORS is configured for API v1 routes."""

    def test_flask_cors_in_requirements(self):
        req = (BASE_DIR / "requirements.txt").read_text(encoding="utf-8")
        assert "flask-cors" in req

    def test_cors_initialized_in_app_factory(self):
        app_init = (BASE_DIR / "app" / "__init__.py").read_text(encoding="utf-8")
        assert "from flask_cors import CORS" in app_init
        assert "CORS(" in app_init
        assert '"/api/v1/*"' in app_init

    def test_cors_config_keys_in_config(self):
        config = (BASE_DIR / "config.py").read_text(encoding="utf-8")
        assert "CORS_ORIGINS" in config
        assert "CORS_SUPPORTS_CREDENTIALS" in config
        assert "CORS_ALLOW_HEADERS" in config


class TestMobileDocs:
    """Mobile integration documentation exists."""

    def test_mobile_api_integration_doc_exists(self):
        path = BASE_DIR / "docs" / "mobile_api_integration.md"
        assert path.exists() and path.stat().st_size > 0

    def test_mobile_doc_covers_key_topics(self):
        content = (BASE_DIR / "docs" / "mobile_api_integration.md").read_text(encoding="utf-8")
        assert "/api/v1/" in content
        assert "CORS" in content
        assert "OpenAPI" in content or "Swagger" in content
        assert "X-CSRFToken" in content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
