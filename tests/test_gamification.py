"""اختبارات الشارات والتحفيز — Gamification."""

from datetime import UTC, datetime, timedelta

from app.extensions import db
from app.models.gamification import Badge, StudentBadge
from app.services.gamification import (
    award_badge,
    check_and_award_badges,
    get_student_badges,
    has_badge,
)
from tests.conftest import make_user


def _clear_badges(app):
    with app.app_context():
        StudentBadge.query.delete()
        Badge.query.delete()
        db.session.commit()


def _create_badge(app, criteria_type):
    with app.app_context():
        b = Badge(name=f"شارة {criteria_type}", icon_name="star", criteria_type=criteria_type, is_active=True)
        db.session.add(b)
        db.session.commit()
        return b.id


def test_badge_model(app):
    _clear_badges(app)
    with app.app_context():
        b = Badge(name="أول اختبار", icon_name="trophy", criteria_type="first_quiz", criteria_value=1, is_active=True)
        db.session.add(b)
        db.session.commit()
        assert b.id is not None
        loaded = db.session.get(Badge, b.id)
        assert loaded.name == "أول اختبار"
        assert loaded.criteria_type == "first_quiz"


def test_student_badge_unique_constraint(app):
    _clear_badges(app)
    with app.app_context():
        sid = make_user(app, role="student")
        bid = _create_badge(app, "first_quiz")
        db.session.add(StudentBadge(student_id=sid, badge_id=bid))
        db.session.commit()
        db.session.add(StudentBadge(student_id=sid, badge_id=bid))
        try:
            db.session.commit()
            assert False, "يجب أن يمنع القيد الفريد"
        except Exception:
            db.session.rollback()


def test_has_badge(app):
    _clear_badges(app)
    with app.app_context():
        sid = make_user(app, role="student")
        bid = _create_badge(app, "first_quiz")
        assert has_badge(sid, bid) is False
        db.session.add(StudentBadge(student_id=sid, badge_id=bid))
        db.session.commit()
        assert has_badge(sid, bid) is True


def test_award_badge_no_duplicate(app):
    _clear_badges(app)
    with app.app_context():
        sid = make_user(app, role="student")
        bid = _create_badge(app, "first_quiz")
    with app.app_context():
        r1 = award_badge(sid, bid)
        assert r1 is not None
    with app.app_context():
        r2 = award_badge(sid, bid)
        assert r2 is None


def test_first_quiz_badge(app):
    _clear_badges(app)
    _create_badge(app, "first_quiz")
    with app.app_context():
        sid = make_user(app, role="student")
    with app.app_context():
        new_badges = check_and_award_badges(sid, "quiz_submitted", {})
        fb = [b for b in new_badges if b.badge.criteria_type == "first_quiz"]
        assert len(fb) == 1


def test_perfect_score_badge(app):
    _clear_badges(app)
    _create_badge(app, "perfect_score")
    with app.app_context():
        sid = make_user(app, role="student")
    with app.app_context():
        new_badges = check_and_award_badges(sid, "quiz_submitted", {"score": 100, "max_score": 100})
        pb = [b for b in new_badges if b.badge.criteria_type == "perfect_score"]
        assert len(pb) == 1


def test_no_duplicate_awards(app):
    _clear_badges(app)
    _create_badge(app, "first_quiz")
    with app.app_context():
        sid = make_user(app, role="student")
    with app.app_context():
        check_and_award_badges(sid, "quiz_submitted", {})
    with app.app_context():
        new2 = check_and_award_badges(sid, "quiz_submitted", {})
        assert len(new2) == 0


def test_get_student_badges(app):
    _clear_badges(app)
    with app.app_context():
        sid = make_user(app, role="student")
        bid = _create_badge(app, "first_quiz")
        db.session.add(StudentBadge(student_id=sid, badge_id=bid))
        db.session.commit()
    with app.app_context():
        badges = get_student_badges(sid)
        assert len(badges) == 1
        assert badges[0].badge.criteria_type == "first_quiz"


def test_early_bird_no_crash(app):
    _clear_badges(app)
    _create_badge(app, "early_bird")
    with app.app_context():
        sid = make_user(app, role="student")
    deadline = (datetime.now(UTC) + timedelta(hours=48)).isoformat()
    submitted = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
    with app.app_context():
        check_and_award_badges(sid, "assignment_submitted", {"deadline": deadline, "submitted_at": submitted})


def test_lesson_completed_no_crash(app):
    _clear_badges(app)
    _create_badge(app, "course_complete")
    with app.app_context():
        sid = make_user(app, role="student")
    with app.app_context():
        check_and_award_badges(sid, "lesson_completed", {"class_id": 9999})
