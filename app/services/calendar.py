"""خدمات التقويم الأكاديمي — إدارة الفترات الدراسية."""

from datetime import date

from app.core.db import tx
from app.core.i18n import _
from app.extensions import db
from app.models.calendar import AcademicEvent


def create_event(
    school_id: int,
    title: str,
    event_type: str,
    start_date: date,
    end_date: date | None = None,
) -> tuple[AcademicEvent | None, str | None]:
    """إنشاء حدث أكاديمي."""
    title = (title or "").strip()
    if not title:
        return None, _("العنوان مطلوب.")
    if event_type not in ("term_start", "term_end", "exam_period", "enrollment", "holiday"):
        return None, _("نوع الحدث غير صالح.")
    if end_date and end_date < start_date:
        return None, _("تاريخ النهاية يجب أن يكون بعد تاريخ البداية.")

    def _create():
        ev = AcademicEvent(
            school_id=school_id,
            title=title,
            event_type=event_type,
            start_date=start_date,
            end_date=end_date,
        )
        db.session.add(ev)
        return ev

    return tx(_create), None


def list_events(school_id: int, event_type: str | None = None) -> list[AcademicEvent]:
    """قائمة أحداث المدرسة."""
    query = AcademicEvent.query.filter_by(school_id=school_id, is_active=True)
    if event_type:
        query = query.filter_by(event_type=event_type)
    return query.order_by(AcademicEvent.start_date).all()


def delete_event(event_id: int) -> tuple[bool, str | None]:
    """حذف حدث (حذف ناعم)."""
    event = db.session.get(AcademicEvent, event_id)
    if not event:
        return False, _("الحدث غير موجود.")

    def _delete():
        event.is_active = False

    tx(_delete)
    return True, None


def current_term(school_id: int) -> AcademicEvent | None:
    """الفصل الحالي (حدث term_start الأقرب الذي لم ينتهي)."""
    today = date.today()
    return (
        AcademicEvent.query.filter(
            AcademicEvent.school_id == school_id,
            AcademicEvent.event_type == "term_start",
            AcademicEvent.is_active == True,  # noqa: E712
            AcademicEvent.start_date <= today,
        )
        .order_by(AcademicEvent.start_date.desc())
        .first()
    )
