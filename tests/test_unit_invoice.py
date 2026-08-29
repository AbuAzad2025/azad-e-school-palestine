"""اختبارات C8 — إنشاء الفواتير (generate_invoice_number, generate_invoice_html)."""

from app.extensions import db
from tests.conftest import (
    make_class,
    make_grade,
    make_school,
    make_subject,
    make_subscription,
    make_subscription_plan,
    make_user,
)


def test_generate_invoice_number(app):
    """رقم الفاتورة بالصيغة INV-{class_id}-{year}-{id}."""
    from app.models.billing import Subscription
    from app.services.invoice import generate_invoice_number

    school_id = make_school(app)
    student_id = make_user(app, role="student", school_id=school_id)
    grade_id = make_grade(app, school_id)
    subject_id = make_subject(app)
    class_id = make_class(app, school_id, grade_id, subject_id)
    with app.app_context():
        plan_id = make_subscription_plan(app, school_id, class_id, price=100.0)
        sub_id = make_subscription(app, student_id, plan_id, class_id, price=100.0)
        sub = db.session.get(Subscription, sub_id)
        num = generate_invoice_number(sub)
        assert num.startswith("INV-")
        assert str(class_id) in num


def test_generate_invoice_html_nonexistent(app):
    """فاتورة لاشتراك غير موجود = None."""
    from app.services.invoice import generate_invoice_html

    with app.app_context():
        result = generate_invoice_html(999999)
        assert result is None


def test_generate_invoice_number_format(app):
    """رقم الفاتورة يحتوي على السنة الحالية."""
    from datetime import datetime

    from app.models.billing import Subscription
    from app.services.invoice import generate_invoice_number

    school_id = make_school(app)
    student_id = make_user(app, role="student", school_id=school_id)
    grade_id = make_grade(app, school_id)
    subject_id = make_subject(app)
    class_id = make_class(app, school_id, grade_id, subject_id)
    with app.app_context():
        plan_id = make_subscription_plan(app, school_id, class_id, price=50.0)
        sub_id = make_subscription(app, student_id, plan_id, class_id, price=50.0)
        sub = db.session.get(Subscription, sub_id)
        num = generate_invoice_number(sub)
        assert str(datetime.now().year) in num
