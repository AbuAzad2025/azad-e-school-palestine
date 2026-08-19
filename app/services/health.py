"""خدمات مراقبة صحة النظام."""

import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from app.core.db import tx
from app.extensions import db
from app.models.system import HealthCheck


def check_database() -> dict:
    start = time.monotonic()
    try:
        db.session.execute(text("SELECT 1"))
        latency = int((time.monotonic() - start) * 1000)
        return {"component": "database", "status": "healthy", "latency_ms": latency, "message": None}
    except Exception as e:
        latency = int((time.monotonic() - start) * 1000)
        return {"component": "database", "status": "down", "latency_ms": latency, "message": str(e)}


def check_disk() -> dict:
    try:
        import shutil

        usage = shutil.disk_usage(".")
        free_gb = usage.free / (1024**3)
        status = "healthy" if free_gb > 1.0 else ("degraded" if free_gb > 0.1 else "down")
        return {"component": "disk", "status": status, "latency_ms": 0, "message": f"{free_gb:.1f} GB free"}
    except Exception as e:
        return {"component": "disk", "status": "down", "latency_ms": 0, "message": str(e)}


def record_health(result: dict) -> HealthCheck:
    def _record():
        hc = HealthCheck(
            component=result["component"],
            status=result["status"],
            message=result.get("message"),
            latency_ms=result.get("latency_ms"),
        )
        db.session.add(hc)
        return hc

    return tx(_record)


def run_all_checks() -> list[dict]:
    checks = [check_database(), check_disk()]
    for c in checks:
        record_health(c)
    return checks


def get_recent_checks(hours: int = 24) -> list[HealthCheck]:
    since = datetime.now(UTC) - timedelta(hours=hours)
    return HealthCheck.query.filter(HealthCheck.checked_at >= since).order_by(HealthCheck.checked_at.desc()).all()


def get_system_status() -> dict:
    recent = HealthCheck.query.order_by(HealthCheck.checked_at.desc()).limit(20).all()
    if not recent:
        return {"overall": "unknown", "components": {}}
    components: dict[str, str] = {}
    for hc in recent:
        if hc.component not in components:
            components[hc.component] = hc.status
    statuses = list(components.values())
    if all(s == "healthy" for s in statuses):
        overall = "healthy"
    elif any(s == "down" for s in statuses):
        overall = "down"
    else:
        overall = "degraded"
    return {"overall": overall, "components": components}
