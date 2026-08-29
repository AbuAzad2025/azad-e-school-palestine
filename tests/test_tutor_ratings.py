"""اختبارات تقييمات المعلمين الخصوصيين وأرباحهم."""

from datetime import UTC, datetime, timedelta

from app.services.tutoring import get_tutor_earnings, rate_session
from tests.conftest import make_user


def test_rate_session_success(app):
    """تقييم جلسة مكتملة ينشئ مراجعة."""
    tutor_id = make_user(app, role="teacher")
    student_id = make_user(app, role="student")

    with app.app_context():
        from app.extensions import db
        from app.models.tutoring import TutoringSession

        # جلسة انتهت مؤخراً (داخل نافذة 24 ساعة)
        session_ = TutoringSession(
            tutor_id=tutor_id,
            student_id=student_id,
            subject="رياضيات",
            scheduled_at=datetime.now(UTC) - timedelta(hours=2),
            duration_min=60,
            price=100.0,
            status="completed",
            payment_status="paid",
            end_time=datetime.now(UTC) - timedelta(hours=1),
        )
        db.session.add(session_)
        db.session.commit()
        session_id = session_.id

    with app.app_context():
        review, error = rate_session(session_id, student_id, 5, "ممتاز!")

    assert error is None
    assert review is not None
    # Query the review fresh to avoid DetachedInstanceError
    with app.app_context():
        from app.models.tutoring import TutorReview

        review = TutorReview.query.filter_by(session_id=session_id, student_id=student_id).first()
    assert review.rating == 5
    assert review.comment == "ممتاز!"
    assert review.student_id == student_id
    assert review.session_id == session_id


def test_rate_session_wrong_student_fails(app):
    """طالب آخر لا يمكنه تقييم الجلسة."""
    tutor_id = make_user(app, role="teacher")
    student1_id = make_user(app, role="student")
    student2_id = make_user(app, role="student")

    with app.app_context():
        from app.extensions import db
        from app.models.tutoring import TutoringSession

        session_ = TutoringSession(
            tutor_id=tutor_id,
            student_id=student1_id,
            subject="رياضيات",
            scheduled_at=datetime.now(UTC) - timedelta(days=1),
            duration_min=60,
            price=100.0,
            status="completed",
            payment_status="paid",
        )
        db.session.add(session_)
        db.session.commit()
        session_id = session_.id

    with app.app_context():
        review, error = rate_session(session_id, student2_id, 5)

    assert error is not None
    assert "ليس لديك صلاحية" in error
    assert review is None


def test_rate_session_not_completed_fails(app):
    """جلسة لم تنتهِ لا يمكن تقييمها."""
    tutor_id = make_user(app, role="teacher")
    student_id = make_user(app, role="student")

    with app.app_context():
        from app.extensions import db
        from app.models.tutoring import TutoringSession

        session_ = TutoringSession(
            tutor_id=tutor_id,
            student_id=student_id,
            subject="رياضيات",
            scheduled_at=datetime.now(UTC) + timedelta(days=1),
            duration_min=60,
            price=100.0,
            status="requested",
            payment_status="pending",
        )
        db.session.add(session_)
        db.session.commit()
        session_id = session_.id

    with app.app_context():
        review, error = rate_session(session_id, student_id, 5)

    assert error is not None
    assert "لم تنتهِ" in error
    assert review is None


def test_rate_session_24h_window_enforced(app):
    """نافذة 24 ساعة مطبقة."""
    tutor_id = make_user(app, role="teacher")
    student_id = make_user(app, role="student")

    with app.app_context():
        from app.extensions import db
        from app.models.tutoring import TutoringSession

        # جلسة انتهت منذ أكثر من 24 ساعة
        old_time = datetime.now(UTC) - timedelta(hours=25)
        session_ = TutoringSession(
            tutor_id=tutor_id,
            student_id=student_id,
            subject="رياضيات",
            scheduled_at=old_time,
            duration_min=60,
            price=100.0,
            status="completed",
            payment_status="paid",
            end_time=old_time + timedelta(hours=1),
        )
        db.session.add(session_)
        db.session.commit()
        session_id = session_.id

    with app.app_context():
        review, error = rate_session(session_id, student_id, 5)

    assert error is not None
    assert "انتهى وقت التقييم" in error
    assert review is None


def test_rate_session_duplicate_prevented(app):
    """يمنع التقييم المكرر لنفس الجلسة."""
    tutor_id = make_user(app, role="teacher")
    student_id = make_user(app, role="student")

    with app.app_context():
        from app.extensions import db
        from app.models.tutoring import TutoringSession

        session_ = TutoringSession(
            tutor_id=tutor_id,
            student_id=student_id,
            subject="رياضيات",
            scheduled_at=datetime.now(UTC) - timedelta(days=1),
            duration_min=60,
            price=100.0,
            status="completed",
            payment_status="paid",
        )
        db.session.add(session_)
        db.session.commit()
        session_id = session_.id

        review1, error1 = rate_session(session_id, student_id, 4)
        review2, error2 = rate_session(session_id, student_id, 5)

    assert error1 is None
    assert review1 is not None
    assert error2 is not None
    assert "مسبقاً" in error2
    assert review2 is None


def test_rate_session_invalid_rating_fails(app):
    """تقييم خارج النطاق 1-5 يفشل."""
    tutor_id = make_user(app, role="teacher")
    student_id = make_user(app, role="student")

    with app.app_context():
        from app.extensions import db
        from app.models.tutoring import TutoringSession

        session_ = TutoringSession(
            tutor_id=tutor_id,
            student_id=student_id,
            subject="رياضيات",
            scheduled_at=datetime.now(UTC) - timedelta(days=1),
            duration_min=60,
            price=100.0,
            status="completed",
            payment_status="paid",
        )
        db.session.add(session_)
        db.session.commit()
        session_id = session_.id

    with app.app_context():
        review, error = rate_session(session_id, student_id, 6)

    assert error is not None
    assert "بين 1 و 5" in error
    assert review is None


def test_get_tutor_earnings(app):
    """ملخص أرباح المعلم يحسب بشكل صحيح."""
    tutor_id = make_user(app, role="teacher")
    student1_id = make_user(app, role="student")
    student2_id = make_user(app, role="student")

    with app.app_context():
        from app.extensions import db
        from app.models.tutoring import TutoringSession, TutorReview

        s1 = TutoringSession(
            tutor_id=tutor_id,
            student_id=student1_id,
            subject="رياضيات",
            scheduled_at=datetime.now(UTC) - timedelta(days=5),
            duration_min=60,
            price=150.0,
            status="completed",
            payment_status="paid",
        )
        s2 = TutoringSession(
            tutor_id=tutor_id,
            student_id=student2_id,
            subject="فيزياء",
            scheduled_at=datetime.now(UTC) - timedelta(days=3),
            duration_min=90,
            price=200.0,
            status="completed",
            payment_status="pending",
        )
        s3 = TutoringSession(
            tutor_id=tutor_id,
            student_id=student1_id,
            subject="كيمياء",
            scheduled_at=datetime.now(UTC) - timedelta(days=1),
            duration_min=60,
            price=100.0,
            status="requested",
            payment_status="pending",
        )
        db.session.add_all([s1, s2, s3])
        db.session.commit()

        # إضافة تقييمات
        r1 = TutorReview(session_id=s1.id, student_id=student1_id, rating=5, comment="ممتاز")
        r2 = TutorReview(session_id=s2.id, student_id=student2_id, rating=4, comment="جيد")
        db.session.add_all([r1, r2])
        db.session.commit()

        earnings = get_tutor_earnings(tutor_id)

    assert earnings["total_earnings"] == 350.0  # 150 + 200
    assert earnings["pending_payouts"] == 300.0  # 200 + 100
    assert earnings["avg_rating"] == 4.5
    assert earnings["review_count"] == 2
    assert earnings["completed_sessions"] == 2
    assert earnings["total_sessions"] == 3


def test_get_tutor_earnings_no_sessions(app):
    """معلم بلا جلسات يرجع أصفاراً."""
    tutor_id = make_user(app, role="teacher")

    with app.app_context():
        earnings = get_tutor_earnings(tutor_id)

    assert earnings["total_earnings"] == 0.0
    assert earnings["pending_payouts"] == 0.0
    assert earnings["avg_rating"] == 0.0
    assert earnings["review_count"] == 0


# Route tests - use unique emails
def test_rate_session_route_student_success(app, client):
    """الطالب يمكنه تقييم جلسته المكتملة."""
    student_email = f"student_rate_success_{id(app)}@test.com"
    tutor_id = make_user(app, role="teacher")
    student_id = make_user(app, role="student", email=student_email)

    with app.app_context():
        from app.extensions import db
        from app.models.tutoring import TutoringSession

        # جلسة انتهت مؤخراً (داخل نافذة 24 ساعة)
        session_ = TutoringSession(
            tutor_id=tutor_id,
            student_id=student_id,
            subject="رياضيات",
            scheduled_at=datetime.now(UTC) - timedelta(hours=2),
            duration_min=60,
            price=100.0,
            status="completed",
            payment_status="paid",
            end_time=datetime.now(UTC) - timedelta(hours=1),
        )
        db.session.add(session_)
        db.session.commit()
        session_id = session_.id

    with client:
        client.post("/auth/login", data={"email": student_email, "password": "TestPass123!"})
        resp = client.get(f"/tutoring/rate/{session_id}")
        assert resp.status_code == 200
        assert "تقييم الجلسة" in resp.get_data(as_text=True)

        resp = client.post(
            f"/tutoring/rate/{session_id}", data={"rating": "5", "comment": "ممتاز"}, follow_redirects=True
        )
        assert resp.status_code == 200
        data = resp.get_data(as_text=True)
        assert "شكراً لتقيميكم" in data


def test_rate_session_route_tutor_forbidden(app, client):
    """المعلم لا يمكنه تقييم جلسته الخاصة."""
    tutor_email = f"tutor_forbidden_{id(app)}@test.com"
    student_id = make_user(app, role="student")
    tutor_id = make_user(app, role="teacher", email=tutor_email)

    with app.app_context():
        from app.extensions import db
        from app.models.tutoring import TutoringSession

        session_ = TutoringSession(
            tutor_id=tutor_id,
            student_id=student_id,
            subject="رياضيات",
            scheduled_at=datetime.now(UTC) - timedelta(days=1),
            duration_min=60,
            price=100.0,
            status="completed",
            payment_status="paid",
        )
        db.session.add(session_)
        db.session.commit()
        session_id = session_.id

    with client:
        client.post("/auth/login", data={"email": tutor_email, "password": "TestPass123!"})
        resp = client.get(f"/tutoring/rate/{session_id}")
        assert resp.status_code == 403


def test_rate_session_route_other_student_forbidden(app, client):
    """طالب آخر لا يمكنه تقييم الجلسة."""
    student1_email = f"student1_other_{id(app)}@test.com"
    student2_email = f"student2_other_{id(app)}@test.com"
    tutor_id = make_user(app, role="teacher")
    student1_id = make_user(app, role="student", email=student1_email)
    make_user(app, role="student", email=student2_email)

    with app.app_context():
        from app.extensions import db
        from app.models.tutoring import TutoringSession

        session_ = TutoringSession(
            tutor_id=tutor_id,
            student_id=student1_id,
            subject="رياضيات",
            scheduled_at=datetime.now(UTC) - timedelta(days=1),
            duration_min=60,
            price=100.0,
            status="completed",
            payment_status="paid",
        )
        db.session.add(session_)
        db.session.commit()
        session_id = session_.id

    with client:
        client.post("/auth/login", data={"email": student2_email, "password": "TestPass123!"})
        resp = client.get(f"/tutoring/rate/{session_id}")
        assert resp.status_code == 403


def test_rate_session_route_24h_expired(app, client):
    """تقييم بعد 24 ساعة ممنوع."""
    student_email = f"student_expired_{id(app)}@test.com"
    tutor_id = make_user(app, role="teacher")
    student_id = make_user(app, role="student", email=student_email)

    with app.app_context():
        from app.extensions import db
        from app.models.tutoring import TutoringSession

        old_time = datetime.now(UTC) - timedelta(hours=25)
        session_ = TutoringSession(
            tutor_id=tutor_id,
            student_id=student_id,
            subject="رياضيات",
            scheduled_at=old_time,
            duration_min=60,
            price=100.0,
            status="completed",
            payment_status="paid",
            end_time=old_time + timedelta(hours=1),
        )
        db.session.add(session_)
        db.session.commit()
        session_id = session_.id

    with client:
        client.post("/auth/login", data={"email": student_email, "password": "TestPass123!"})
        resp = client.post(f"/tutoring/rate/{session_id}", data={"rating": "5"}, follow_redirects=True)
        assert resp.status_code == 200
        data = resp.get_data(as_text=True)
        assert "انتهى وقت التقييم" in data


def test_tutor_earnings_route_tutor_access(app, client):
    """المعلم/المدرس يمكنه الوصول لصفحة الأرباح."""
    tutor_email = f"tutor_earnings_{id(app)}@test.com"
    tutor_id = make_user(app, role="teacher", email=tutor_email)

    with app.app_context():
        from app.services.tutoring import create_tutor_profile

        create_tutor_profile(tutor_id, "رياضيات")

    with client:
        client.post("/auth/login", data={"email": tutor_email, "password": "TestPass123!"})
        resp = client.get("/tutoring/earnings")
        assert resp.status_code == 200


def test_tutor_earnings_route_student_forbidden(app, client):
    """الطالب لا يمكنه الوصول لصفحة الأرباح."""
    student_email = f"student_earnings_{id(app)}@test.com"
    make_user(app, role="student", email=student_email)

    with client:
        client.post("/auth/login", data={"email": student_email, "password": "TestPass123!"})
        resp = client.get("/tutoring/earnings")
        assert resp.status_code == 403
