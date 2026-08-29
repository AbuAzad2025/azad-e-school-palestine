"""اختبارات تكامل — السجل المالي + الفواتير (C7, C9, finance services)."""

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


def test_subscription_balance_partial_payment(app):
    """رصيد الاشتراك بعد دفع جزئي."""
    from app.services.billing import subscription_balance

    school_id = make_school(app)
    student_id = make_user(app, role="student", school_id=school_id)
    grade_id = make_grade(app, school_id)
    subject_id = make_subject(app)
    class_id = make_class(app, school_id, grade_id, subject_id)
    with app.app_context():
        plan_id = make_subscription_plan(app, school_id, class_id, price=200.0)
        sub_id = make_subscription(app, student_id, plan_id, class_id, price=200.0, status="pending")
        make_payment(app, sub_id, amount=80.0, status="approved")
        balance = subscription_balance(sub_id)
        assert balance == 120.0


def test_subscription_balance_full_payment(app):
    """رصيد الاشتراك بعد الدفع الكامل = صفر."""
    from app.services.billing import subscription_balance

    school_id = make_school(app)
    student_id = make_user(app, role="student", school_id=school_id)
    grade_id = make_grade(app, school_id)
    subject_id = make_subject(app)
    class_id = make_class(app, school_id, grade_id, subject_id)
    with app.app_context():
        plan_id = make_subscription_plan(app, school_id, class_id, price=100.0)
        sub_id = make_subscription(app, student_id, plan_id, class_id, price=100.0, status="active")
        make_payment(app, sub_id, amount=100.0, status="approved")
        assert subscription_balance(sub_id) == 0


def test_can_record_payment_valid(app):
    """يمكن تسجيل دفع ضمن الرصيد المتبقي."""
    from app.services.billing import can_record_payment

    school_id = make_school(app)
    student_id = make_user(app, role="student", school_id=school_id)
    grade_id = make_grade(app, school_id)
    subject_id = make_subject(app)
    class_id = make_class(app, school_id, grade_id, subject_id)
    with app.app_context():
        plan_id = make_subscription_plan(app, school_id, class_id, price=100.0)
        sub_id = make_subscription(app, student_id, plan_id, class_id, price=100.0, status="pending")
        ok, msg = can_record_payment(sub_id, 50)
        assert ok is True


def test_can_record_payment_exceeds_balance(app):
    """رفض دفع يتجاوز الرصيد المتبقي."""
    from app.services.billing import can_record_payment

    school_id = make_school(app)
    student_id = make_user(app, role="student", school_id=school_id)
    grade_id = make_grade(app, school_id)
    subject_id = make_subject(app)
    class_id = make_class(app, school_id, grade_id, subject_id)
    with app.app_context():
        plan_id = make_subscription_plan(app, school_id, class_id, price=100.0)
        sub_id = make_subscription(app, student_id, plan_id, class_id, price=100.0, status="pending")
        ok, msg = can_record_payment(sub_id, 150)
        assert ok is False
        assert "يتجاوز" in msg


def test_school_revenue_summary(app):
    """ملخص إيرادات المدرسة مع دفعات معتمدة."""
    from app.services.finance import school_revenue_summary

    school_id = make_school(app)
    student_id = make_user(app, role="student", school_id=school_id)
    grade_id = make_grade(app, school_id)
    subject_id = make_subject(app)
    class_id = make_class(app, school_id, grade_id, subject_id)
    with app.app_context():
        plan_id = make_subscription_plan(app, school_id, class_id, price=200.0)
        sub_id = make_subscription(app, student_id, plan_id, class_id, price=200.0, status="active")
        make_payment(app, sub_id, amount=150.0, status="approved")
        summary = school_revenue_summary(school_id)
        assert summary["total_revenue"] == 150.0
        assert summary["active_count"] >= 1


def test_student_balance_in_class(app):
    """رصيد الطالب في صف معين."""
    from app.services.finance import student_balance

    school_id = make_school(app)
    student_id = make_user(app, role="student", school_id=school_id)
    grade_id = make_grade(app, school_id)
    subject_id = make_subject(app)
    class_id = make_class(app, school_id, grade_id, subject_id)
    with app.app_context():
        plan_id = make_subscription_plan(app, school_id, class_id, price=300.0)
        sub_id = make_subscription(app, student_id, plan_id, class_id, price=300.0, status="active")
        make_payment(app, sub_id, amount=100.0, status="approved")
        bal = student_balance(student_id, class_id)
        assert bal["has_subscription"] is True
        assert bal["total_price"] == 300.0
        assert bal["total_paid"] == 100.0
        assert bal["balance"] == 200.0


def test_subscription_payment_summary(app):
    """ملخص الدفعات للاشتراك."""
    from app.services.billing import subscription_payment_summary

    school_id = make_school(app)
    student_id = make_user(app, role="student", school_id=school_id)
    grade_id = make_grade(app, school_id)
    subject_id = make_subject(app)
    class_id = make_class(app, school_id, grade_id, subject_id)
    with app.app_context():
        plan_id = make_subscription_plan(app, school_id, class_id, price=250.0)
        sub_id = make_subscription(app, student_id, plan_id, class_id, price=250.0)
        make_payment(app, sub_id, amount=100.0, status="approved")
        make_payment(app, sub_id, amount=50.0, status="pending")
        summary = subscription_payment_summary(sub_id)
        assert summary["total_paid"] == 100.0
        assert summary["balance"] == 150.0
        assert summary["approved_count"] == 1
        assert summary["pending_count"] == 1
