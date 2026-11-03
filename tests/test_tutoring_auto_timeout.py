from datetime import UTC, datetime, timedelta

from app.extensions import db
from app.models.tutoring import TutorCommission, TutoringSession
from app.models.user import User, UserRole
from app.services import tutoring


def _make_user(app, role=UserRole.student):
    with app.app_context():
        u = User(
            email=f"u{db.session.query(User).count()}@test.com",
            name_ar="مستخدم",
            role=role,
            password_hash="x",
            approval_status="approved",
            is_active=True,
        )
        db.session.add(u)
        db.session.commit()
        return u.id


def test_auto_timeout_unconfirmed_session(app):
    tutor_id = _make_user(app, UserRole.teacher)
    student_id = _make_user(app, UserRole.student)
    with app.app_context():
        s = TutoringSession(
            tutor_id=tutor_id,
            student_id=student_id,
            subject="رياضيات",
            status="requested",
            payment_status="pending",
            student_confirmed_payment=False,
            tutor_confirmed_payment=False,
            price=100,
        )
        s.created_at = datetime.now(UTC) - timedelta(hours=72)
        db.session.add(s)
        db.session.commit()
        sid = s.id

    with app.app_context():
        res = tutoring.auto_timeout_unconfirmed_sessions(grace_hours=48)
        assert res["finalized"] >= 1
        s2 = db.session.get(TutoringSession, sid)
        assert s2.payment_status == "paid"
        assert s2.student_confirmed_payment is True
        assert s2.tutor_confirmed_payment is True
        # Commission should be created/trigged
        comm = TutorCommission.query.filter_by(session_id=sid).first()
        assert comm is not None
