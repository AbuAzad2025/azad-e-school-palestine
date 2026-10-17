"""خدمات الحضور — تنبيهات الغياب لوليّ الأمر (AZ-P2-12)."""

from __future__ import annotations

from datetime import UTC, date, datetime

from app.core.db import tx
from app.core.logging import get_logger
from app.extensions import db

logger = get_logger(__name__)


def _as_date(value: str | date) -> date:
    """يوحّد مدخل اليوم: نص YYYY-MM-DD أو كائن date."""
    if isinstance(value, str):
        return date.fromisoformat(value.strip())
    return value


def run_absence_alerts(target_date: str | date | None = None) -> int:
    """يرسل تنبيه غياب لكل وليّ أمر مرتبط بكل طالب غائب في اليوم المحدد.

    الاستدعاء اليومي المكرر آمن: سجل AbsenceAlertLog فريد لكل
    (طالب، يوم) يقطع الإرسال الثاني حتى لو تغيّر الربط بين التشغيلين —
    والأطياف (طالب بلا وليّ أمر، غياب صباح قبل التشغيل) لا تُفشل المهمة
    بل تُتخطى. يعيد عدد الطلاب الذين أُرسل لهم تنبيه.
    """
    from app.models.attendance import AbsenceAlertLog, Attendance
    from app.models.family import FamilyLink
    from app.models.user import User
    from app.services.email import send_absence_alert_email

    day = _as_date(target_date) if target_date is not None else datetime.now(UTC).date()

    absent_rows = Attendance.query.filter(Attendance.date == day, Attendance.status == "absent").all()
    sent = 0
    for row in absent_rows:
        already = AbsenceAlertLog.query.filter_by(student_id=row.student_id, date=day).first()
        if already is not None:
            continue

        links = FamilyLink.query.filter_by(student_id=row.student_id, status="active").all()
        if not links:
            # طالب بلا وليّ أمر مرتبط — حفرية مشروعة، لا يفشل تقدّم المهمة.
            continue

        student = db.session.get(User, row.student_id)
        if student is None:
            continue

        delivered = False
        for link in links:
            parent = db.session.get(User, link.parent_id) if link.parent_id else None
            if parent is None:
                continue
            try:
                if send_absence_alert_email(parent, student, days=1):
                    delivered = True
            except Exception as e:  # بريد فاشل لوليّ واحد لا يعطّل الباقين
                logger.warning(
                    "absence_alert_send_failed",
                    student_id=row.student_id,
                    parent_id=parent.id,
                    error=str(e)[:200],
                    error_type=type(e).__name__,
                )

        if not delivered:
            continue

        # ربط القيم بمدخلات الدالة (B023) — الإغلاق لا يقرأ متغيرات الحلقة بعد تغيّرها.
        def _log(student_id=row.student_id, linked_parent_id=links[0].parent_id):
            rec = AbsenceAlertLog(
                student_id=student_id,
                parent_id=linked_parent_id,
                date=day,
                sent_at=datetime.now(UTC),
            )
            db.session.add(rec)
            return rec

        tx(_log)
        sent += 1

    logger.info("absence_alerts_completed", date=str(day), students_notified=sent)
    return sent
