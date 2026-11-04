"""Coverage gaps for app/services/health.py — check_backup_freshness."""

import os
import time


def test_no_backups_returns_down(app, tmp_path, monkeypatch):
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path))
    with app.app_context():
        from app.services.health import check_backup_freshness

        result = check_backup_freshness()
    assert result["status"] == "down"
    assert result["component"] == "backup"


def test_fresh_backup_healthy(app, tmp_path, monkeypatch):
    backup = tmp_path / "backup_2026_11_04.sql"
    backup.write_bytes(b"x" * (2 * 1024 * 1024))
    os.utime(backup, None)  # now
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path))
    with app.app_context():
        from app.services.health import check_backup_freshness

        result = check_backup_freshness()
    assert result["status"] == "healthy"
    assert result["component"] == "backup"


def test_stale_backup_returns_down(app, tmp_path, monkeypatch):
    backup = tmp_path / "backup_2026_01_01.sql"
    backup.write_bytes(b"x" * (2 * 1024 * 1024))
    old = time.time() - 40 * 3600  # 40 hours old
    os.utime(backup, (old, old))
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path))
    with app.app_context():
        from app.services.health import check_backup_freshness

        result = check_backup_freshness()
    assert result["status"] == "down"


def test_small_backup_returns_degraded(app, tmp_path, monkeypatch):
    backup = tmp_path / "backup_tiny.sql"
    backup.write_bytes(b"tiny")
    os.utime(backup, None)
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path))
    with app.app_context():
        from app.services.health import check_backup_freshness

        result = check_backup_freshness()
    assert result["status"] == "degraded"


def test_sentinel_file_not_counted(app, tmp_path, monkeypatch):
    (tmp_path / "notes.txt").write_text("not a backup")
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path))
    with app.app_context():
        from app.services.health import check_backup_freshness

        result = check_backup_freshness()
    assert result["status"] == "down"


def test_get_system_status_unknown_when_empty(app, monkeypatch):
    from app.extensions import db
    from app.models.system import HealthCheck

    class _NoRows:
        def order_by(self, *a, **k):
            return self

        def limit(self, *a, **k):
            return self

        def all(self):
            return []

    class _FakeQuery:
        def order_by(self, *a, **k):
            return _NoRows()

    with app.app_context():
        monkeypatch.setattr(HealthCheck, "query", _FakeQuery())
        from app.services.health import get_system_status

        assert get_system_status()["overall"] == "unknown"
