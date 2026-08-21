"""Production deployment artifacts tests — Phase 6"""
from pathlib import Path
import pytest


BASE_DIR = Path.cwd()


class TestProductionArtifacts:
    """Ensure production deployment files exist and are non-empty."""

    def test_production_checklist_exists(self):
        path = BASE_DIR / "docs" / "production_checklist.md"
        assert path.exists() and path.stat().st_size > 0

    def test_docker_compose_production_exists(self):
        path = BASE_DIR / "deploy" / "docker-compose.production.yml"
        assert path.exists()
        content = path.read_text(encoding="utf-8")
        assert "postgres:15" in content
        assert "redis:7" in content
        assert "nginx" in content

    def test_dockerfile_exists(self):
        path = BASE_DIR / "deploy" / "Dockerfile"
        assert path.exists()
        content = path.read_text(encoding="utf-8")
        assert "gunicorn" in content

    def test_nginx_config_exists(self):
        path = BASE_DIR / "deploy" / "nginx.conf"
        assert path.exists()
        content = path.read_text(encoding="utf-8")
        assert "ssl_certificate" in content
        assert "X-Frame-Options" in content
        assert "proxy_pass" in content

    def test_systemd_service_exists(self):
        path = BASE_DIR / "deploy" / "azad-e-school.service"
        assert path.exists()
        content = path.read_text(encoding="utf-8")
        assert "gunicorn" in content
        assert "[Unit]" in content

    def test_deploy_script_exists(self):
        path = BASE_DIR / "deploy" / "deploy.sh"
        assert path.exists()
        content = path.read_text(encoding="utf-8")
        assert "git pull" in content
        assert "flask db upgrade" in content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])