"""CI/CD pipeline tests — Phase 7"""

from pathlib import Path

import pytest

BASE_DIR = Path.cwd()
WORKFLOWS_DIR = BASE_DIR / ".github" / "workflows"


class TestCICDWorkflows:
    """Ensure CI and deploy workflows are configured."""

    def test_ci_workflow_exists(self):
        path = WORKFLOWS_DIR / "ci.yml"
        assert path.exists() and path.stat().st_size > 0

    def test_deploy_job_exists_in_ci(self):
        content = (WORKFLOWS_DIR / "ci.yml").read_text(encoding="utf-8")
        assert "docker/build-push-action" in content
        assert "deploy:" in content or "name: Deploy" in content

    def test_ci_runs_on_main_push_and_pr(self):
        content = (WORKFLOWS_DIR / "ci.yml").read_text(encoding="utf-8")
        assert "branches: [main]" in content or "branches:\n      - main" in content
        assert "pull_request:" in content

    def test_ci_includes_quality_gates(self):
        content = (WORKFLOWS_DIR / "ci.yml").read_text(encoding="utf-8")
        assert "ruff" in content
        assert "mypy" in content
        assert "bandit" in content
        assert "biome" in content or "eslint" in content
        assert "pytest" in content

    def test_deploy_builds_docker_image(self):
        content = (WORKFLOWS_DIR / "ci.yml").read_text(encoding="utf-8")
        assert "docker/build-push-action" in content
        assert "deploy/Dockerfile" in content

    def test_deploy_runs_ssh_and_smoke_tests(self):
        content = (WORKFLOWS_DIR / "ci.yml").read_text(encoding="utf-8")
        assert "appleboy/ssh-action" in content
        assert "flask db upgrade" in content
        assert "curl" in content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
