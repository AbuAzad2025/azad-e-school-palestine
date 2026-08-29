"""اختبارات نظام الخصم/الكوبونات"""

import uuid
from datetime import date, timedelta

from app.models.billing import DiscountCode, SubscriptionPlan
from app.services.billing import apply_discount_code, create_discount_code, validate_discount_code


def _unique_domain():
    return f"test-{uuid.uuid4().hex[:8]}.org"


def _unique_code():
    return f"CODE-{uuid.uuid4().hex[:8]}"


def _unique_join_code():
    return f"JOIN-{uuid.uuid4().hex[:8]}"


def _unique_email():
    return f"student-{uuid.uuid4().hex[:8]}@test.com"


def test_create_discount_code(app):
    """إنشاء كود خصم ناجح"""
    with app.app_context():
        from app.extensions import db
        from app.models.school import School

        school = School(name_ar="مدرسة", name_en="School", domain=_unique_domain())
        db.session.add(school)
        db.session.commit()

        code = _unique_code()
        dc, error = create_discount_code(
            school_id=school.id,
            code=code,
            name="خصم ترحيبي",
            type_="percentage",
            value=20,
            max_uses=100,
            expiry_date=date.today() + timedelta(days=30),
        )
        assert error is None
        assert dc is not None
        # Code is converted to uppercase in service
        assert dc.code == code.upper()
        assert dc.type == "percentage"
        assert dc.value == 20


def test_validate_discount_valid(app):
    """تحقق من كود صالح"""
    with app.app_context():
        from app.extensions import db
        from app.models.school import School

        school = School(name_ar="مدرسة 2", name_en="School 2", domain=_unique_domain())
        db.session.add(school)
        db.session.commit()

        plan = SubscriptionPlan(school_id=school.id, name="خطة", plan="annual", price=100, currency="ILS")
        db.session.add(plan)
        db.session.commit()

        code = _unique_code()
        dc, _ = create_discount_code(
            school_id=school.id,
            code=code,
            name="صالح",
            type_="percentage",
            value=20,
            max_uses=10,
            expiry_date=date.today() + timedelta(days=30),
        )
        db.session.commit()

        discount, error = validate_discount_code(code, plan.id)
        assert error is None
        assert discount == 20.0  # 20% of 100


def test_validate_discount_expired(app):
    """كود منتهي الصلاحية"""
    with app.app_context():
        from app.extensions import db
        from app.models.school import School

        school = School(name_ar="مدرسة 3", name_en="School 3", domain=_unique_domain())
        db.session.add(school)
        db.session.commit()

        plan = SubscriptionPlan(school_id=school.id, name="خطة", plan="annual", price=100, currency="ILS")
        db.session.add(plan)
        db.session.commit()

        code = _unique_code()
        dc, _ = create_discount_code(
            school_id=school.id,
            code=code,
            name="منتهي",
            type_="percentage",
            value=20,
            max_uses=10,
            expiry_date=date.today() - timedelta(days=1),  # Past date
        )
        db.session.commit()

        discount, error = validate_discount_code(code, plan.id)
        assert error is not None
        # Error message should indicate expired or invalid
        assert "صلاح" in error or "expired" in error.lower() or "صالح" in error


def test_validate_discount_max_uses(app):
    """كود استُنفد استخداماته"""
    with app.app_context():
        from app.extensions import db
        from app.models.billing import DiscountCode
        from app.models.school import School

        school = School(name_ar="مدرسة 4", name_en="School 4", domain=_unique_domain())
        db.session.add(school)
        db.session.commit()

        plan = SubscriptionPlan(school_id=school.id, name="خطة", plan="annual", price=100, currency="ILS")
        db.session.add(plan)
        db.session.commit()

        code = _unique_code()
        dc, _ = create_discount_code(
            school_id=school.id,
            code=code,
            name="مستنفد",
            type_="percentage",
            value=20,
            max_uses=1,
            expiry_date=date.today() + timedelta(days=30),
        )
        db.session.commit()

        # Update used_count directly in DB (code is stored uppercase)
        dc_db = DiscountCode.query.filter_by(code=code.upper()).first()
        dc_db.used_count = 1
        db.session.commit()

        discount, error = validate_discount_code(code, plan.id)
        assert error is not None
        assert "استنفاد" in error or "max" in error.lower() or "uses" in error.lower()


def test_apply_discount_to_subscription(app):
    """تطبيق كود خصم على اشتراك"""
    with app.app_context():
        from app.extensions import db
        from app.models.billing import Subscription, SubscriptionPlan
        from app.models.class_room import ClassRoom
        from app.models.school import Grade, School, Subject
        from app.models.user import User, UserRole

        school = School(name_ar="مدرسة 5", name_en="School 5", domain=_unique_domain())
        db.session.add(school)
        db.session.commit()

        grade = Grade(school_id=school.id, grade_level=10, name_ar="العاشر")
        subject = Subject(name_ar="رياضيات")
        db.session.add_all([grade, subject])
        db.session.commit()

        class_room = ClassRoom(
            school_id=school.id, grade_id=grade.id, subject_id=subject.id, join_code=_unique_join_code(), name="صف"
        )
        db.session.add(class_room)
        db.session.commit()

        user = User(
            email=_unique_email(),
            name_ar="طالب",
            role=UserRole.student,
            password_hash="hash",
            approval_status="approved",
            is_active=True,
        )
        db.session.add(user)
        db.session.commit()

        plan = SubscriptionPlan(
            school_id=school.id,
            class_id=class_room.id,
            name="خطة",
            plan="annual",
            price=100,
            currency="ILS",
            duration_days=30,
        )
        db.session.add(plan)
        db.session.commit()

        sub = Subscription(
            user_id=user.id, plan_id=plan.id, class_id=class_room.id, price=100, currency="ILS", status="pending"
        )
        db.session.add(sub)
        db.session.commit()

        unique_code = f"APPLY-{uuid.uuid4().hex[:8]}"
        dc, _ = create_discount_code(
            school_id=school.id,
            code=unique_code,
            name="تطبيق",
            type_="percentage",
            value=20,
            max_uses=10,
            expiry_date=date.today() + timedelta(days=30),
        )
        db.session.commit()

        discount, error = apply_discount_code(sub.id, unique_code)
        assert error is None
        assert discount == 20.0

        # Check subscription price reduced
        db.session.refresh(sub)
        assert sub.price == 80.0  # 100 - 20

        # Check used_count incremented
        dc_db = DiscountCode.query.filter_by(code=unique_code.upper()).first()
        assert dc_db is not None
        assert dc_db.used_count == 1
