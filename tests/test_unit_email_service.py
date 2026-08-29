"""اختبارات C10 — خدمة البريد الإلكتروني ( EMAIL_ENABLED=False → False مع log)."""

from unittest.mock import MagicMock

from app.extensions import db
from tests.conftest import (
    make_class,
    make_grade,
    make_payment,
    make_school,
    make_subject,
    make_subscription,
    make_subscription_plan,
    make_user,
)


def test_send_welcome_email_disabled(app):
    """إرسال بريد ترحيب مع تعطيل البريد = False."""
    from app.models.user import User
    from app.services.email import send_welcome_email

    school_id = make_school(app)
    user_id = make_user(app, role="student", school_id=school_id)
    with app.app_context():
        u = db.session.get(User, user_id)
        result = send_welcome_email(u)
        assert result is False


def test_send_payment_approved_email_disabled(app):
    """إرسال بريد اعتماد دفع مع تعطيل = False."""
    from app.models.billing import ManualPayment
    from app.services.email import send_payment_approved_email

    school_id = make_school(app)
    student_id = make_user(app, role="student", school_id=school_id)
    grade_id = make_grade(app, school_id)
    subject_id = make_subject(app)
    class_id = make_class(app, school_id, grade_id, subject_id)
    with app.app_context():
        plan_id = make_subscription_plan(app, school_id, class_id, price=100.0)
        sub_id = make_subscription(app, student_id, plan_id, class_id, price=100.0, status="pending")
        pay_id = make_payment(app, sub_id, amount=100.0, status="approved")
        p = db.session.get(ManualPayment, pay_id)
        result = send_payment_approved_email(p)
        assert result is False


def test_send_grade_published_email_disabled(app):
    """إرسال بريد نشر درجة مع تعطيل = False."""
    from app.models.user import User
    from app.services.email import send_grade_published_email

    school_id = make_school(app)
    student_id = make_user(app, role="student", school_id=school_id)
    with app.app_context():
        u = db.session.get(User, student_id)
        fake_assignment = MagicMock(title="اختبار رياضيات", max_mark=20)
        result = send_grade_published_email(u, fake_assignment, 18)
        assert result is False


def test_send_absence_alert_email_disabled(app):
    """إرسال بريد تنبيه غياب مع تعطيل = False."""
    from app.models.user import User
    from app.services.email import send_absence_alert_email

    school_id = make_school(app)
    parent_id = make_user(app, role="parent", school_id=school_id)
    student_id = make_user(app, role="student", school_id=school_id)
    with app.app_context():
        parent = db.session.get(User, parent_id)
        student = db.session.get(User, student_id)
        result = send_absence_alert_email(parent, student, 7)
        assert result is False
