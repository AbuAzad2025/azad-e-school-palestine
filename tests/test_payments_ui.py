"""اختبارات واجهة المستخدم للمدفوعات (payments_ui)."""

from tests.conftest import make_class, make_grade, make_school, make_subject, make_user


def test_payment_methods_page_renders(app, client):
    """صفحة طرق الدفع تظهر للمستخدمين المسجلين."""
    school_id = make_school(app)
    student_email = f"student{school_id}@test.com"
    user_id = make_user(app, role="student", school_id=school_id, email=student_email)

    with client:
        client.post("/auth/login", data={"email": student_email, "password": "TestPass123!"})
        resp = client.get("/payments/")
        assert resp.status_code == 200
        assert "طرق الدفع المتاحة" in resp.get_data(as_text=True)
        assert "Stripe" in resp.get_data(as_text=True)
        assert "PayTabs" in resp.get_data(as_text=True)


def test_payment_methods_page_anonymous_redirects(app, client):
    """الصفحة تعيد توجيه المستخدمين غير المسجلين."""
    resp = client.get("/payments/")
    assert resp.status_code == 302
    assert "/auth/login" in resp.location


def test_payment_methods_api(app, client):
    """API طرق الدفع يعيد JSON صحيح."""
    school_id = make_school(app)
    student_email = f"student{school_id}@test.com"
    user_id = make_user(app, role="student", school_id=school_id, email=student_email)

    with client:
        client.post("/auth/login", data={"email": student_email, "password": "TestPass123!"})
        resp = client.get("/payments/methods")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "methods" in data
        assert len(data["methods"]) == 5
        method_ids = [m["id"] for m in data["methods"]]
        assert "stripe" in method_ids
        assert "paytabs" in method_ids
        assert "cashu" in method_ids
        assert "whatsapp" in method_ids
        assert "manual" in method_ids


def test_payment_methods_api_anonymous_returns_401(app, client):
    """API طرق الدفع يعيد 302 redirect للمستخدمين غير المسجلين (لصفحة تسجيل الدخول)."""
    resp = client.get("/payments/methods")
    assert resp.status_code == 302
    assert "/auth/login" in resp.location


def test_create_payment_intent_valid(app, client):
    """إنشاء نية دفع ببيانات صحيحة."""
    school_id = make_school(app)
    student_email = f"student{school_id}@test.com"
    user_id = make_user(app, role="student", school_id=school_id, email=f"student{school_id}@test.com")
    grade_id = make_grade(app, school_id)
    subject_id = make_subject(app)
    teacher_id = make_user(app, role="teacher", school_id=school_id)
    class_id = make_class(app, school_id, grade_id, subject_id, teacher_id=teacher_id)

    with app.app_context():
        from app.extensions import db
        from app.models.billing import Subscription, SubscriptionPlan

        plan = SubscriptionPlan(
            school_id=school_id,
            class_id=class_id,
            name="خطة اختبار",
            plan="annual",
            price=100.0,
        )
        db.session.add(plan)
        db.session.commit()
        plan_id = plan.id

        sub = Subscription(
            user_id=user_id,
            plan_id=plan_id,
            class_id=class_id,
            price=100.0,
            status="pending",
        )
        db.session.add(sub)
        db.session.commit()
        sub_id = sub.id

    with client:
        client.post("/auth/login", data={"email": f"student{school_id}@test.com", "password": "TestPass123!"})
        resp = client.post(
            "/payments/create-intent",
            json={"gateway": "manual", "amount": "100", "currency": "ILS", "subscription_id": sub_id},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert "payment_id" in data
        assert data["gateway"] == "manual"
        assert data["amount"] == "100"
        assert data["currency"] == "ILS"


def test_create_payment_intent_invalid_amount(app, client):
    """إنشاء نية دفع بمبلغ غير صحيح يفشل."""
    school_id = make_school(app)
    student_email = f"student{school_id}@test.com"
    user_id = make_user(app, role="student", school_id=school_id, email=student_email)

    with client:
        client.post("/auth/login", data={"email": student_email, "password": "TestPass123!"})
        resp = client.post(
            "/payments/create-intent",
            json={"gateway": "manual", "amount": "0", "currency": "ILS"},
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert "error" in data


def test_create_payment_intent_wrong_user(app, client):
    """إنشاء نية دفع لمستخدم آخر يفشل."""
    school_id = make_school(app)
    student1_email = f"student1{school_id}@test.com"
    student2_email = f"student2{school_id}@test.com"
    user_id_1 = make_user(app, role="student", school_id=school_id, email=student1_email)
    user_id_2 = make_user(app, role="student", school_id=school_id, email=student2_email)
    grade_id = make_grade(app, school_id)
    subject_id = make_subject(app)
    teacher_id = make_user(app, role="teacher", school_id=school_id)
    class_id = make_class(app, school_id, grade_id, subject_id, teacher_id=teacher_id)

    with app.app_context():
        from app.extensions import db
        from app.models.billing import Subscription, SubscriptionPlan

        plan = SubscriptionPlan(
            school_id=school_id,
            class_id=class_id,
            name="خطة اختبار",
            plan="annual",
            price=100.0,
        )
        db.session.add(plan)
        db.session.commit()
        plan_id = plan.id

        sub = Subscription(
            user_id=user_id_2,  # الاشتراك لمستخدم آخر
            plan_id=plan_id,
            class_id=class_id,
            price=100.0,
            status="pending",
        )
        db.session.add(sub)
        db.session.commit()
        sub_id = sub.id

    with client:
        client.post("/auth/login", data={"email": student1_email, "password": "TestPass123!"})
        resp = client.post(
            "/payments/create-intent",
            json={"gateway": "manual", "amount": "100", "currency": "ILS", "subscription_id": sub_id},
        )
        assert resp.status_code == 403
        data = resp.get_json()
        assert "error" in data


def test_create_payment_intent_invalid_gateway(app, client):
    """إنشاء نية دفع ببوابة غير مدعومة يفشل."""
    school_id = make_school(app)
    student_email = f"student{school_id}@test.com"
    user_id = make_user(app, role="student", school_id=school_id, email=student_email)

    with client:
        client.post("/auth/login", data={"email": student_email, "password": "TestPass123!"})
        resp = client.post(
            "/payments/create-intent",
            json={"gateway": "invalid_gateway", "amount": "100", "currency": "ILS"},
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert "error" in data
