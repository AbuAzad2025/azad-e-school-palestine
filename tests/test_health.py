"""اختبارات مراقبة صحة النظام."""

from app.extensions import db
from app.models.system import HealthCheck
from app.services.health import (
    check_database,
    check_disk,
    get_recent_checks,
    get_system_status,
    record_health,
    run_all_checks,
)
from sqlalchemy import text


def _clean_health_table():
    db.session.execute(text("DELETE FROM health_checks"))
    db.session.commit()


def test_check_database_healthy(app):
    with app.app_context():
        result = check_database()
        assert result["component"] == "database"
        assert result["status"] == "healthy"
        assert result["latency_ms"] >= 0
        assert result["message"] is None


def test_check_disk(app):
    with app.app_context():
        result = check_disk()
        assert result["component"] == "disk"
        assert result["status"] in ("healthy", "degraded", "down")
        assert isinstance(result["message"], str)
        assert "GB free" in result["message"]


def test_record_health(app):
    with app.app_context():
        _clean_health_table()
        hc = record_health({"component": "database", "status": "healthy", "latency_ms": 5, "message": None})
        assert hc.id is not None
        assert hc.component == "database"
        assert hc.status == "healthy"
        assert hc.latency_ms == 5


def test_get_recent_checks(app):
    with app.app_context():
        _clean_health_table()
        record_health({"component": "test_comp", "status": "healthy", "latency_ms": 1, "message": "ok"})
        checks = get_recent_checks(hours=1)
        assert len(checks) >= 1
        assert checks[0].component == "test_comp"


def test_get_system_status_no_checks(app):
    with app.app_context():
        _clean_health_table()
        status = get_system_status()
        assert status["overall"] == "unknown"
        assert status["components"] == {}


def test_get_system_status_all_healthy(app):
    with app.app_context():
        _clean_health_table()
        record_health({"component": "database", "status": "healthy", "latency_ms": 2, "message": None})
        record_health({"component": "disk", "status": "healthy", "latency_ms": 0, "message": "10 GB free"})
        status = get_system_status()
        assert status["overall"] == "healthy"
        assert status["components"]["database"] == "healthy"
        assert status["components"]["disk"] == "healthy"


def test_run_all_checks(app):
    with app.app_context():
        _clean_health_table()
        results = run_all_checks()
        assert len(results) == 2
        components = {r["component"] for r in results}
        assert "database" in components
        assert "disk" in components
        saved = HealthCheck.query.all()
        assert len(saved) == 2


def test_health_check_model(app):
    with app.app_context():
        _clean_health_table()
        hc = HealthCheck(component="api", status="degraded", message="slow", latency_ms=500)
        db.session.add(hc)
        db.session.commit()
        assert hc.id is not None
        assert hc.component == "api"
        assert hc.status == "degraded"
        assert hc.message == "slow"
        assert hc.latency_ms == 500
        assert hc.checked_at is not None
        assert hc.created_at is not None
