"""اختبارات نظام عمولة المعلمين"""

import pytest
from datetime import UTC, datetime, timedelta
import uuid

from app.services.tutoring import get_tutor_earnings, create_commission_record, request_payout
from app.models.tutoring import TutoringSession, TutorCommission, TutorPayout, TutorProfile
from app.models.user import User, UserRole


def _unique_email():
    return f"user-{uuid.uuid4().hex[:8]}@test.com"


def test_create_commission_on_session_complete(app):
    """يتم إنشاء عمولة عند اكتمال الجلسة"""
    with app.app_context():
        from app.extensions import db

        # Create tutor and student
        tutor = User(email=_unique_email(), name_ar="معلم", role=UserRole.teacher,
                     password_hash="hash", approval_status="approved", is_active=True)
        student = User(email=_unique_email(), name_ar="طالب", role=UserRole.student,
                       password_hash="hash", approval_status="approved", is_active=True)
        db.session.add_all([tutor, student])
        db.session.commit()

        # Create session
        session = TutoringSession(
            tutor_id=tutor.id,
            student_id=student.id,
            subject="رياضيات",
            scheduled_at=datetime.now(UTC) - timedelta(days=1),
            duration_min=60,
            price=100.0,
            currency="ILS",
            status="completed",
            payment_status="paid",
        )
        db.session.add(session)
        db.session.commit()

        # Create commission
        commission = create_commission_record(session)
        assert commission is not None
        assert commission.session_id == session.id
        assert commission.tutor_id == tutor.id
        assert commission.commission_amount == 20.0
        assert commission.tutor_net == 80.0


def test_commission_calculation_20_percent(app):
    """حساب 20% بشكل صحيح"""
    with app.app_context():
        from app.extensions import db

        tutor = User(email=_unique_email(), name_ar="معلم 2", role=UserRole.teacher,
                     password_hash="hash", approval_status="approved", is_active=True)
        student = User(email=_unique_email(), name_ar="طالب 2", role=UserRole.student,
                       password_hash="hash", approval_status="approved", is_active=True)
        db.session.add_all([tutor, student])
        db.session.commit()

        # Test with different prices
        for price, expected_commission, expected_net in [
            (100, 20, 80),
            (250, 50, 200),
            (150, 30, 120),
        ]:
            session = TutoringSession(
                tutor_id=tutor.id,
                student_id=student.id,
                subject="رياضيات",
                scheduled_at=datetime.now(UTC) - timedelta(days=1),
                duration_min=60,
                price=price,
                currency="ILS",
                status="completed",
                payment_status="paid",
            )
            db.session.add(session)
            db.session.commit()

            commission = create_commission_record(session)
            assert commission is not None
            assert commission.commission_amount == expected_commission
            assert commission.tutor_net == expected_net


def test_no_duplicate_commission(app):
    """لا يتم إنشاء عمولة مكررة"""
    with app.app_context():
        from app.extensions import db

        tutor = User(email=_unique_email(), name_ar="معلم 3", role=UserRole.teacher,
                     password_hash="hash", approval_status="approved", is_active=True)
        student = User(email=_unique_email(), name_ar="طالب 3", role=UserRole.student,
                       password_hash="hash", approval_status="approved", is_active=True)
        db.session.add_all([tutor, student])
        db.session.commit()

        session = TutoringSession(
            tutor_id=tutor.id,
            student_id=student.id,
            subject="رياضيات",
            scheduled_at=datetime.now(UTC) - timedelta(days=1),
            duration_min=60,
            price=100.0,
            currency="ILS",
            status="completed",
            payment_status="paid",
        )
        db.session.add(session)
        db.session.commit()

        # First creation
        c1 = create_commission_record(session)
        assert c1 is not None

        # Second creation should return None (duplicate)
        c2 = create_commission_record(session)
        assert c2 is None


def test_request_payout_success(app):
    """طلب سحب ناجح"""
    with app.app_context():
        from app.extensions import db

        tutor = User(email=_unique_email(), name_ar="معلم 4", role=UserRole.teacher,
                     password_hash="hash", approval_status="approved", is_active=True)
        student = User(email=_unique_email(), name_ar="طالب 4", role=UserRole.student,
                       password_hash="hash", approval_status="approved", is_active=True)
        db.session.add_all([tutor, student])
        db.session.commit()

        # Create completed session with commission
        session = TutoringSession(
            tutor_id=tutor.id,
            student_id=student.id,
            subject="رياضيات",
            scheduled_at=datetime.now(UTC) - timedelta(days=1),
            duration_min=60,
            price=500.0,
            currency="ILS",
            status="completed",
            payment_status="paid",
        )
        db.session.add(session)
        db.session.commit()

        create_commission_record(session)

        # Request payout
        payout, error = request_payout(tutor.id, 200)
        assert error is None
        assert payout is not None
        assert payout.amount == 200
        assert payout.status == "pending"


def test_request_payout_below_minimum(app):
    """رفض طلب أقل من 200₪"""
    with app.app_context():
        from app.extensions import db

        tutor = User(email=_unique_email(), name_ar="معلم 5", role=UserRole.teacher,
                     password_hash="hash", approval_status="approved", is_active=True)
        db.session.add(tutor)
        db.session.commit()

        payout, error = request_payout(tutor.id, 100)
        assert error is not None
        assert "200" in error
        assert payout is None


def test_request_payout_exceeds_balance(app):
    """رفض طلب يتجاوز الرصيد المتاح"""
    with app.app_context():
        from app.extensions import db

        tutor = User(email=_unique_email(), name_ar="معلم 6", role=UserRole.teacher,
                     password_hash="hash", approval_status="approved", is_active=True)
        student = User(email=_unique_email(), name_ar="طالب 6", role=UserRole.student,
                       password_hash="hash", approval_status="approved", is_active=True)
        db.session.add_all([tutor, student])
        db.session.commit()

        # Create small session
        session = TutoringSession(
            tutor_id=tutor.id,
            student_id=student.id,
            subject="رياضيات",
            scheduled_at=datetime.now(UTC) - timedelta(days=1),
            duration_min=60,
            price=100.0,
            currency="ILS",
            status="completed",
            payment_status="paid",
        )
        db.session.add(session)
        db.session.commit()

        create_commission_record(session)  # commission = 20, net = 80

        # Request more than available
        payout, error = request_payout(tutor.id, 500)
        assert error is not None
        assert "يتجاوز" in error
        assert payout is None