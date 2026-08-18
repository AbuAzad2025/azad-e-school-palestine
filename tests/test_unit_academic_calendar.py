"""اختبارات C4 — التقويم الأكاديمي (create_event, list_events, delete_event, current_term)."""

from datetime import date, timedelta

from app.extensions import db
from tests.conftest import make_academic_event, make_school


def test_create_event_success(app):
    """إنشاء حدث أكاديمي بنجاح."""
    from app.services.calendar import create_event

    school_id = make_school(app)
    with app.app_context():
        ev, err = create_event(school_id, "بداية الفصل", "term_start", date(2025, 9, 1))
        assert ev is not None
        assert err is None
        assert ev.title == "بداية الفصل"
        assert ev.event_type == "term_start"


def test_create_event_invalid_type(app):
    """رفض نوع حدث غير صالح."""
    from app.services.calendar import create_event

    school_id = make_school(app)
    with app.app_context():
        ev, err = create_event(school_id, "حدث", "invalid_type", date(2025, 9, 1))
        assert ev is None
        assert "صالح" in err


def test_create_event_end_before_start(app):
    """رفض تاريخ نهاية قبل تاريخ البداية."""
    from app.services.calendar import create_event

    school_id = make_school(app)
    with app.app_context():
        ev, err = create_event(school_id, "حدث", "holiday", date(2025, 12, 31), date(2025, 1, 1))
        assert ev is None
        assert "النهاية" in err


def test_delete_event_soft(app):
    """حذف ناعم للحدث."""
    from app.services.calendar import delete_event

    school_id = make_school(app)
    with app.app_context():
        ev_id = make_academic_event(app, school_id, "اختبار", "holiday", date(2025, 12, 25))
        ok, err = delete_event(ev_id)
        assert ok
        from app.models.calendar import AcademicEvent
        ev = db.session.get(AcademicEvent, ev_id)
        assert ev.is_active is False


def test_current_term(app):
    """جلب الفصل الحالي."""
    from app.services.calendar import current_term

    school_id = make_school(app)
    with app.app_context():
        today = date.today()
        make_academic_event(app, school_id, "فصل خريف", "term_start", today - timedelta(days=30))
        term = current_term(school_id)
        assert term is not None
        assert term.event_type == "term_start"
