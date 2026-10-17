"""خدمات مراقبة صحة النظام."""

import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from app.core.db import tx
from app.core.errors import safe_message
from app.core.i18n import _
from app.core.logging import get_logger
from app.extensions import db
from app.models.system import HealthCheck

logger = get_logger(__name__)


def check_database() -> dict:
    start = time.monotonic()
    try:
        db.session.execute(text("SELECT 1"))
        latency = int((time.monotonic() - start) * 1000)
        return {"component": "database", "status": "healthy", "latency_ms": latency, "message": None}
    except Exception as e:
        # D5: رسالة الصحة تُعرض في الواجهة وتُحفظ في الجدول — لا نص مزوّد
        # قاعدة بيانات فيها؛ التفصيل يبقى في سجل الخادم وحده.
        latency = int((time.monotonic() - start) * 1000)
        logger.warning("health_check_database_failed", error=str(e)[:200], error_type=type(e).__name__)
        return {"component": "database", "status": "down", "latency_ms": latency, "message": safe_message(503)}


def check_disk() -> dict:
    try:
        import shutil

        usage = shutil.disk_usage(".")
        free_gb = usage.free / (1024**3)
        status = "healthy" if free_gb > 1.0 else ("degraded" if free_gb > 0.1 else "down")
        return {"component": "disk", "status": status, "latency_ms": 0, "message": f"{free_gb:.1f} GB free"}
    except Exception as e:
        logger.warning("health_check_disk_failed", error=str(e)[:200], error_type=type(e).__name__)
        return {"component": "disk", "status": "down", "latency_ms": 0, "message": _("تعذّر قراءة مساحة القرص.")}


def check_backup_freshness(max_age_hours: int = 25, min_size_mb: float = 1.0) -> dict:
    """أحدث نسخة احتياطية: عمرها وحجمها (AZ-P1-10).

    مهمة النسخ قد تتوقف بلا ضجة (مسار خاطئ، صلاحية، مساحة ممتلئة)، وتظهر المشكلة
    فقط يوم الحاجة للاستعادة. لذلك تُفحص الحداثة والحجم من مهمة مجدولة: نسخة
    منقضية = ``down``، ونسخة أصغر من الحد = ``degraded`` (ملف مقطوع).
    """
    import os
    from pathlib import Path

    backup_dir = Path(os.getenv("BACKUP_DIR", "backups"))
    candidates = sorted(
        (p for p in backup_dir.glob("backup_*.sql*") if p.is_file()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        return {
            "component": "backup",
            "status": "down",
            "latency_ms": 0,
            "message": _("لا توجد نسخة احتياطية في مجلد النسخ."),
        }

    latest = candidates[0]
    age = datetime.now(UTC) - datetime.fromtimestamp(latest.stat().st_mtime, tz=UTC)
    size_mb = latest.stat().st_size / (1024 * 1024)
    if age > timedelta(hours=max_age_hours):
        status = "down"
    elif size_mb < min_size_mb:
        status = "degraded"
    else:
        status = "healthy"
    return {
        "component": "backup",
        "status": status,
        "latency_ms": 0,
        "message": f"{latest.name} ({size_mb:.1f} MB, {age.total_seconds() / 3600:.1f}h)",
    }


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
