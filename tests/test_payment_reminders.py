"""اختبارات Payment Reminders Cron"""

import pytest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch, MagicMock
import uuid

from app.models.billing import Subscription, ReminderLog


def _unique_domain():
    return f"test-{uuid.uuid4().hex[:8]}.org"


def _unique_email():
    return f"student-{uuid.uuid4().hex[:8]}@test.com"


def _unique_join_code():
    return f"JOIN-{uuid.uuid4().hex[:8]}"


def test_daily_reminders_sends_for_expiring_sub(app):
    """يرسل تذكير للاشتراكات التي تنتهي خلال 7 أيام"""
    from app import create_app
    from app.extensions import db
    from app.models.user import User, UserRole
    from app.models.school import School, Grade, Subject
    from app.models.class_room import ClassRoom
    from app.models.billing import SubscriptionPlan
    from scripts.daily_reminders import run_daily_reminders

    with app.app_context():
        # Create school
        school = School(name_ar="مدرسة اختبار", name_en="Test School", domain=_unique_domain())
        db.session.add(school)
        db.session.commit()

        # Create user
        user = User(email=_unique_email(), name_ar="طالب اختبار", role=UserRole.student,
                    password_hash="hash", approval_status="approved", is_active=True)
        db.session.add(user)
        db.session.commit()

        # Create class
        grade = Grade(school_id=school.id, grade_level=10, name_ar="العاشر")
        subject = Subject(name_ar="رياضيات")
        db.session.add_all([grade, subject])
        db.session.commit()

        class_room = ClassRoom(school_id=school.id, grade_id=grade.id, subject_id=subject.id,
                               join_code=_unique_join_code(), name="صف العاشر")
        db.session.add(class_room)
        db.session.commit()

        # Create plan
        plan = SubscriptionPlan(school_id=school.id, class_id=class_room.id, name="خطة",
                                plan="annual", price=100, currency="ILS", duration_days=30)
        db.session.add(plan)
        db.session.commit()

        # Create subscription ending in 7 days
        end_at = datetime.now(UTC) + timedelta(days=7)
        sub = Subscription(user_id=user.id, plan_id=plan.id, class_id=class_room.id,
                           price=100, currency="ILS", status="active", end_at=end_at)
        db.session.add(sub)
        db.session.commit()

        # Mock email function
        with patch("scripts.daily_reminders.send_payment_reminder_email", return_value=True) as mock_email:
            count = run_daily_reminders(app)
            assert count == 1
            mock_email.assert_called_once()

        # Check reminder log
        log = ReminderLog.query.filter_by(subscription_id=sub.id, reminder_type="7d").first()
        assert log is not None


def test_daily_reminders_skips_already_sent(app):
    """يتجاهل التذكير إذا تم إرساله مسبقاً"""
    from app import create_app
    from app.extensions import db
    from app.models.user import User, UserRole
    from app.models.school import School, Grade, Subject
    from app.models.class_room import ClassRoom
    from app.models.billing import SubscriptionPlan, ReminderLog
    from scripts.daily_reminders import run_daily_reminders

    with app.app_context():
        # Setup similar to above
        school = School(name_ar="مدرسة اختبار 2", name_en="Test School 2", domain=_unique_domain())
        db.session.add(school)
        db.session.commit()

        user = User(email=_unique_email(), name_ar="طالب 2", role=UserRole.student,
                    password_hash="hash", approval_status="approved", is_active=True)
        db.session.add(user)
        db.session.commit()

        grade = Grade(school_id=school.id, grade_level=10, name_ar="العاشر")
        subject = Subject(name_ar="رياضيات")
        db.session.add_all([grade, subject])
        db.session.commit()

        class_room = ClassRoom(school_id=school.id, grade_id=grade.id, subject_id=subject.id,
                               join_code=_unique_join_code(), name="صف العاشر 2")
        db.session.add(class_room)
        db.session.commit()

        plan = SubscriptionPlan(school_id=school.id, class_id=class_room.id, name="خطة",
                                plan="annual", price=100, currency="ILS", duration_days=30)
        db.session.add(plan)
        db.session.commit()

        end_at = datetime.now(UTC) + timedelta(days=7)
        sub = Subscription(user_id=user.id, plan_id=plan.id, class_id=class_room.id,
                           price=100, currency="ILS", status="active", end_at=end_at)
        db.session.add(sub)
        db.session.commit()

        # Add existing reminder log
        existing_log = ReminderLog(subscription_id=sub.id, reminder_type="7d")
        db.session.add(existing_log)
        db.session.commit()

        with patch("scripts.daily_reminders.send_payment_reminder_email", return_value=True) as mock_email:
            count = run_daily_reminders(app)
            assert count == 0
            mock_email.assert_not_called()