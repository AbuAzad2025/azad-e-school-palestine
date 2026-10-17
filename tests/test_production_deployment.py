"""Production deployment artifacts tests — Phase 6

AZ-P1-10: لم تكن هناك جدولة تشغيلية حقيقية — compose بلا خدمة cron/worker،
ولا مسار واحد يستدعي مهمة مجدولة، والأوامر المكتوبة كانت كتل Python داخل
الـ crontab (تتعفّن بلا اختبار)، وpg_cron مُحمَّل بلا أي مهمة مسجّلة. فئة
``TestSchedulingIsReal`` تتحقق من: وجود المجدول، وأن كل مهمة مجدولة معرّفة
في مصدر واحد تستدعيه كل مسارات الجدولة، وأن أوامرها أوامر CLI مسجّلة أو
سكربتات موجودة فعلاً، وأن الأمر المجدول يعمل عند تشغيله يدوياً.
"""

import os
import re
import subprocess
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


class TestSchedulingIsReal:
    """AZ-P1-10 — الجدولة قائمة فعلاً ومن مصدر واحد، والأوامر تُنفَّذ فعلاً."""

    CRONTABS = ("deploy/crontab", "scripts/cron_jobs.sh")
    CONTAINER_CRON = "deploy/crontab"

    def _service_block(self, name: str) -> str:
        """يعيد كتلة خدمة من compose بالتحقق من الإزاحة (لا اعتماد على PyYAML)."""
        lines = (BASE_DIR / "deploy" / "docker-compose.production.yml").read_text(encoding="utf-8").splitlines()
        start = next(
            (i for i, line in enumerate(lines) if line.startswith("  ") and line.strip() == f"{name}:"),
            None,
        )
        assert start is not None, f"service {name} is not defined in the production compose"
        block = [lines[start]]
        for line in lines[start + 1 :]:
            if line.strip() and not line.startswith("    "):
                break
            block.append(line)
        return "\n".join(block)

    def _wrapper(self) -> str:
        return (BASE_DIR / "scripts" / "scheduled_jobs.sh").read_text(encoding="utf-8")

    def _defined_jobs(self) -> set[str]:
        """أسماء المهام المعرّفة في الغلاف الواحد (case)."""
        return set(re.findall(r"^  ([a-z][a-z-]+)\)$", self._wrapper(), re.M))

    def test_compose_runs_a_scheduler_service_on_the_shared_crontab(self):
        block = self._service_block("scheduler")
        assert "cron" in block.split("command:", 1)[1].splitlines()[0], "scheduler must run cron"
        assert "/etc/cron.d/azad" in block, "scheduler must read the repository crontab"
        assert "../.env" in block, "scheduled jobs must get their secrets from .env"
        assert "db" in block and "redis" in block
        assert (BASE_DIR / self.CONTAINER_CRON).exists()

    def test_every_scheduled_job_is_defined_in_the_single_source(self):
        defined = self._defined_jobs()
        assert defined, "the job wrapper must define at least one job"
        for crontab in self.CRONTABS:
            content = (BASE_DIR / crontab).read_text(encoding="utf-8")
            scheduled = re.findall(r'\$\{JOBS\}"?\s+([a-z][a-z-]+)', content)
            assert scheduled, f"{crontab} schedules nothing"
            unknown = [job for job in scheduled if job not in defined]
            assert not unknown, f"{crontab} schedules jobs the wrapper does not define: {unknown}"
        # المهمة المالية الحرجة مجدولة فعلاً في المسارين (كل 5 دقائق).
        for crontab in self.CRONTABS:
            content = (BASE_DIR / crontab).read_text(encoding="utf-8")
            assert re.search(r"^\*/5 .*pending-payments", content, re.M), f"{crontab} misses the 5-minute job"

    def test_scheduled_commands_resolve_to_registered_entry_points(self, app):
        wrapper = self._wrapper()
        cli_jobs = re.findall(r'exec "\$\{FLASK\[@\]\}" ([a-z-]+)', wrapper)
        assert cli_jobs, "the wrapper must call the app CLI"
        for command in cli_jobs:
            assert command in app.cli.commands, f"flask {command} is not registered"
        scripts = re.findall(r'exec "\$\{PYTHON\[@\]\}" "\$\{APP_DIR\}/([^"]+)"', wrapper)
        for relative in scripts:
            assert (BASE_DIR / relative).exists(), f"scheduled script is missing: {relative}"

    def test_no_placeholder_paths_or_superuser_database_role(self):
        deployment_files = [
            *self.CRONTABS,
            "scripts/scheduled_jobs.sh",
            "scripts/cron_backup.sh",
            "deploy/Dockerfile",
            "deploy/docker-compose.production.yml",
            "deploy/azad-e-school.service",
            "deploy/deploy.sh",
            "deploy/nginx.conf",
        ]
        for relative in deployment_files:
            content = (BASE_DIR / relative).read_text(encoding="utf-8")
            assert "/path/to" not in content, f"{relative} still contains placeholder paths"
            assert "://postgres:" not in content and "postgres:password" not in content, (
                f"{relative} must not use the postgres superuser"
            )

    def test_pg_cron_dead_config_is_removed(self):
        """لا يُحمَّل الإمتداد فعلاً — ذكر السبب في تعليق توضيحي مقبول."""
        content = (BASE_DIR / "deploy" / "postgresql.conf.production").read_text(encoding="utf-8")
        active_lines = [line for line in content.splitlines() if line.strip() and not line.lstrip().startswith("#")]
        assert not [line for line in active_lines if "pg_cron" in line], (
            "pg_cron was loaded with no registered job — dead config that fakes scheduling"
        )
        assert any(line.startswith("shared_preload_libraries") for line in active_lines)

    def test_the_scheduled_command_runs_manually(self):
        """نفس الأمر الذي سيشغّله المجدول يُنفَّذ هنا كما هو (رمز خروج 0 + عدّاد)."""
        env = {**os.environ, "APP_DIR": str(BASE_DIR), "VENV_DIR": str(BASE_DIR / ".venv")}
        result = subprocess.run(
            ["bash", "scripts/scheduled_jobs.sh", "pending-payments"],
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            env=env,
            timeout=180,
        )
        assert result.returncode == 0, result.stderr
        assert "expired_pending_payments=" in result.stdout

    def test_unknown_job_is_refused(self):
        env = {**os.environ, "APP_DIR": str(BASE_DIR), "VENV_DIR": str(BASE_DIR / ".venv")}
        result = subprocess.run(
            ["bash", "scripts/scheduled_jobs.sh", "not-a-job"],
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        )
        assert result.returncode == 2
        assert "usage:" in result.stderr


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
