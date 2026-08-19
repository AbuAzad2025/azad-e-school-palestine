"""اختبارات معالج الإعداد الأولي."""
from datetime import datetime, timezone

from app.extensions import db
from app.services.onboarding import (
    WIZARD_STEPS,
    complete_step,
    get_onboarding,
    get_onboarding_status,
    get_wizard_steps,
    start_onboarding,
)


def test_start_onboarding(app):
    with app.app_context():
        from tests.conftest import make_school
        school_id = make_school(app)
        progress = start_onboarding(school_id)
        assert progress.id is not None
        assert progress.school_id == school_id
        assert progress.current_step == 1
        assert progress.total_steps == 5
        assert progress.is_complete is False
        assert progress.completed_steps == {}


def test_start_onboarding_idempotent(app):
    with app.app_context():
        from tests.conftest import make_school
        school_id = make_school(app)
        p1 = start_onboarding(school_id)
        p2 = start_onboarding(school_id)
        assert p1.id == p2.id


def test_complete_step(app):
    with app.app_context():
        from tests.conftest import make_school
        school_id = make_school(app)
        start_onboarding(school_id)
        result = complete_step(school_id, 1, {"name": "مدرسة النور"})
        assert result is not None
        assert result.current_step == 2
        assert "1" in result.completed_steps
        assert result.completed_steps["1"]["name"] == "مدرسة النور"
        assert result.is_complete is False


def test_complete_multiple_steps(app):
    with app.app_context():
        from tests.conftest import make_school
        school_id = make_school(app)
        start_onboarding(school_id)
        for i in range(1, 6):
            complete_step(school_id, i)
        progress = get_onboarding(school_id)
        assert len(progress.completed_steps) == 5


def test_wizard_completion(app):
    with app.app_context():
        from tests.conftest import make_school
        school_id = make_school(app)
        start_onboarding(school_id)
        for i in range(1, 6):
            complete_step(school_id, i)
        progress = get_onboarding(school_id)
        assert progress.is_complete is True
        assert progress.completed_at is not None
        assert isinstance(progress.completed_at, datetime)


def test_invalid_step_rejected(app):
    with app.app_context():
        from tests.conftest import make_school
        school_id = make_school(app)
        start_onboarding(school_id)
        assert complete_step(school_id, 0) is None
        assert complete_step(school_id, 6) is None


def test_get_onboarding_status_not_started(app):
    with app.app_context():
        from tests.conftest import make_school
        school_id = make_school(app)
        status = get_onboarding_status(school_id)
        assert status["started"] is False
        assert status["current_step"] == 0
        assert status["is_complete"] is False


def test_get_onboarding_status_in_progress(app):
    with app.app_context():
        from tests.conftest import make_school
        school_id = make_school(app)
        start_onboarding(school_id)
        complete_step(school_id, 1)
        complete_step(school_id, 3)
        status = get_onboarding_status(school_id)
        assert status["started"] is True
        assert status["current_step"] == 4
        assert status["is_complete"] is False
        assert "1" in status["completed_steps"]
        assert "3" in status["completed_steps"]
        assert "2" not in status["completed_steps"]
