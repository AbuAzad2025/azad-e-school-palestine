from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.extensions import db
from app.models.billing import Subscription, SubscriptionPlan
from app.models.class_room import ClassRoom
from app.models.school import Grade, School, Subject
from app.models.user import User, UserRole
from app.services import access, billing


def _setup(app):
    with app.app_context():
        school = School(name_ar="مدرسة", domain="x.test.org")
        db.session.add(school)
        db.session.flush()
        grade = Grade(school_id=school.id, grade_level=1, name_ar="أول")
        db.session.add(grade)
        subject = Subject(name_ar="عربى")
        db.session.add(subject)
        teacher = User(
            email="t@t.com",
            name_ar="معلم",
            role=UserRole.teacher,
            password_hash="x",
            approval_status="approved",
            is_active=True,
        )
        db.session.add(teacher)
        db.session.flush()
        import secrets
        cls = ClassRoom(
            school_id=school.id,
            grade_id=grade.id,
            subject_id=subject.id,
            teacher_id=teacher.id,
            is_public=True,
            price=Decimal("100"),
            join_code=secrets.token_urlsafe(6),
            name="صف",
        )
        db.session.add(cls)
        plan = SubscriptionPlan(
            school_id=school.id,
            class_id=cls.id,
            name="خطة",
            plan="annual",
            price=Decimal("100"),
        )
        db.session.add(plan)
        student = User(
            email="s@s.com",
            name_ar="طالب",
            role=UserRole.student,
            password_hash="x",
            approval_status="approved",
            is_active=True,
        )
        db.session.add(student)
        db.session.commit()
        return {
            "school": school.id,
            "class": cls.id,
            "plan": plan.id,
            "student": student.id,
        }


def test_lazy_expire_pending_subscription_on_query(app):
    data = _setup(app)
    with app.app_context():
        plan = db.session.get(SubscriptionPlan, data["plan"])
        sub, err = billing.subscribe(data["student"], plan, data["class"])
        assert err is None
        assert sub.status == "pending"
        sub_id = sub.id
        # Make it old
        sub.created_at = datetime.now(UTC) - timedelta(hours=96)
        db.session.commit()

    # Access check should lazily expire
    with app.app_context():
        cls = db.session.get(ClassRoom, data["class"])
        user = db.session.get(User, data["student"])
        # can_pay_class triggers lazy expiration
        access.can_pay_class(cls, user)
        # After lazy expiration, pending is expired
        sub2 = db.session.get(Subscription, sub_id)
        assert sub2.status == "expired"
