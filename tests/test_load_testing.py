"""Load-test infrastructure tests — Phase 5"""
import os
import subprocess
import sys
from pathlib import Path
import pytest


BASE_DIR = Path.cwd()
LOCUSTFILE = BASE_DIR / "tests" / "load" / "locustfile.py"


def _read(path):
    return path.read_text(encoding="utf-8")


class TestLocustfile:
    """Validate the Locust load-test scenario."""

    def test_locustfile_exists(self):
        assert LOCUSTFILE.exists(), "Missing tests/load/locustfile.py"

    def test_locustfile_imports_cleanly(self):
        content = _read(LOCUSTFILE)
        assert "from locust import" in content
        assert "HttpUser" in content
        assert "@task" in content

    def test_locustfile_has_public_and_authenticated_users(self):
        content = _read(LOCUSTFILE)
        assert "class PublicUser" in content
        assert "class AuthenticatedUser" in content
        assert "class SpikeUser" in content

    def test_locustfile_can_be_imported(self):
        """Verify the locustfile is valid Python syntax without importing locust."""
        import ast
        content = _read(LOCUSTFILE)
        tree = ast.parse(content)
        classes = [node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
        assert "PublicUser" in classes
        assert "AuthenticatedUser" in classes
        assert "SpikeUser" in classes


class TestLoadReportTemplate:
    """Report template exists for capturing results."""

    def test_report_template_exists(self):
        report = BASE_DIR / "tests" / "load" / "report_template.md"
        assert report.exists(), "Missing load-test report template"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])