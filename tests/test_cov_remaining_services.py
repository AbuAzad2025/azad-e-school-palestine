"""Tests for remaining services needing coverage: assessment, auth (more),
tutoring, billing, payments, progress, gradebook (more), base."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from app import create_app
from app.extensions import db as _db
from app.core.security import hash_password
from app.models.assessment import Answer, Question, Quiz, QuizAttempt
from app.models.billing import ManualPayment, Subscription, SubscriptionPlan
from app.models.class_room import ClassMember, ClassRoom
from app.models.content import Lesson, LessonAttachment
from app.models.gradebook import (
    Assignment,
    GradeCategory,
    GradeEntry,
    GradeItem,
    Submission,
)
from app.models.progress import StudentProgress, VideoProgress
from app.models.question_bank import QuestionBank
from app.models.school import Grade, School, Subject
from app.models.tutoring import (
    TutorCommission,
    TutorProfile,
    TutoringRequest,
    TutoringSession,
    TutorPayout,
    TutorReview,
)
from app.models.user import User, UserApprovalStatus, UserRole, UserRoleLink


@pytest.fixture(scope="module")
def app():
    a = create_app()
    a.config["TESTING"] = True
    a.config["WTF_CSRF_ENABLED"] = False
    a.config["EMAIL_ENABLED"] = False
    a.config["TALISMAN_ENABLED"] = False
    a.config["SESSION_COOKIE_SECURE"] = False
    a.config["LOGIN_MAX_ATTEMPTS"] = 5
    a.config["LOGIN_LOCKOUT_DURATION"] = 900
    with a.app_context():
        from sqlalchemy import text
        _db.session.execute(text("CREATE EXTENSION IF NOT EXISTS citext"))
        _db.session.commit()
        _db.create_all()
    yield a


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture(autouse=True)
def _clean(app):
    yield
    with app.app_context():
        from sqlalchemy import text, inspect
        inspector = inspect(_db.engine)
        tables = inspector.get_table_names(schema="public")
        tables = [t for t in tables if t != "alembic_version"]
        if tables:
            _db.session.execute(text(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE"))
            _db.session.commit()


def _uid():
    import uuid
    return uuid.uuid4().hex[:10]


def _email():
    return f"u-{_uid()}@test.com"


def _user(app, role="student", **kw):
    with app.app_context():
        u = User(
            email=kw.get("email", _email()),
            name_ar=kw.get("name_ar", f"مستخدم {_uid()}"),
            role=UserRole(role),
            password_hash=hash_password("TestPass123!"),
            approval_status=UserApprovalStatus.approved,
            is_active=True,
        )
        _db.session.add(u)
        _db.session.commit()
        return u.id


def _school(app, **kw):
    with app.app_context():
        s = School(
            name_ar=kw.get("name_ar", f"مدرسة {_uid()}"),
            domain=f"{_uid()}.test.org",
            join_code=kw.get("join_code", f"S-{_uid()[:6]}"),
        )
        _db.session.add(s)
        _db.session.commit()
        return s.id


def _grade(app, school_id, grade_level=1):
    with app.app_context():
        g = Grade(school_id=school_id, grade_level=grade_level, name_ar=f"صف {grade_level}")
        _db.session.add(g)
        _db.session.commit()
        return g.id


def _subject(app):
    with app.app_context():
        s = Subject(name_ar=f"مادة {_uid()}")
        _db.session.add(s)
        _db.session.commit()
        return s.id


def _class(app, school_id, grade_id, subject_id, teacher_id=None):
    with app.app_context():
        c = ClassRoom(
            school_id=school_id, grade_id=grade_id, subject_id=subject_id,
            teacher_id=teacher_id, join_code=f"C-{_uid()[:6]}", name=f"صف {_uid()}",
        )
        _db.session.add(c)
        _db.session.commit()
        return c.id


# ======================================================================
# assessment.py tests
# ======================================================================
class TestAssessmentService:
    def _setup_quiz(self, app):
        sid = _school(app)
        gid = _grade(app, sid)
        subjid = _subject(app)
        tid = _user(app, "teacher")
        cid = _class(app, sid, gid, subjid, tid)
        quiz = Quiz(class_id=cid, title="اختبار", status="published", total_mark=10.0)
        _db.session.add(quiz)
        _db.session.commit()
        q = Question(quiz_id=quiz.id, type="mcq", prompt="ما هو 1+1؟",
                     options={"a": "2", "b": "3"}, correct_answer="a", mark=5.0, sort_order=1)
        _db.session.add(q)
        _db.session.commit()
        return quiz, q, tid, cid, sid

    def test_create_quiz(self, app):
        from app.models.assessment import Quiz as QuizModel
        with app.app_context():
            sid = _school(app)
            gid = _grade(app, sid)
            subjid = _subject(app)
            tid = _user(app, "teacher")
            cid = _class(app, sid, gid, subjid, tid)
            quiz = QuizModel(class_id=cid, title="اختبار جديد")
            _db.session.add(quiz)
            _db.session.commit()
            assert quiz.id is not None


# ======================================================================
# tutoring.py service tests
# ======================================================================
class TestTutoringService:
    def test_create_tutor_profile(self, app):
        from app.services.tutoring import create_tutor_profile
        with app.app_context():
            tid = _user(app, "teacher")
            profile, err = create_tutor_profile(tid, "رياضيات", price_hour=100.0)
            assert profile is not None
            assert err is None
            assert profile.invite_code is not None

    def test_create_tutor_profile_duplicate(self, app):
        from app.services.tutoring import create_tutor_profile
        with app.app_context():
            tid = _user(app, "teacher")
            create_tutor_profile(tid, "رياضيات")
            profile, err = create_tutor_profile(tid, "فيزياء")
            assert profile is None

    def test_get_profile(self, app):
        from app.services.tutoring import create_tutor_profile, get_profile
        with app.app_context():
            tid = _user(app, "teacher")
            create_tutor_profile(tid, "رياضيات")
            p = get_profile(tid)
            assert p is not None

    def test_search_tutors(self, app):
        from app.services.tutoring import create_tutor_profile, search_tutors
        with app.app_context():
            tid = _user(app, "teacher")
            create_tutor_profile(tid, "رياضيات", bio="معلم خبرة 5 سنوات")
            results = search_tutors(q="رياضيات")
            assert len(results) >= 1

    def test_find_by_invite_code(self, app):
        from app.services.tutoring import create_tutor_profile, find_by_invite_code
        with app.app_context():
            tid = _user(app, "teacher")
            p, _ = create_tutor_profile(tid, "رياضيات")
            found = find_by_invite_code(p.invite_code)
            assert found is not None

    def test_update_profile(self, app):
        from app.services.tutoring import create_tutor_profile, update_profile, get_profile
        with app.app_context():
            tid = _user(app, "teacher")
            p, _ = create_tutor_profile(tid, "رياضيات")
            update_profile(p, bio="معلم ممتاز", price_hour=150.0)
            updated = get_profile(tid)
            assert updated.bio == "معلم ممتاز"

    def test_create_request(self, app):
        from app.services.tutoring import create_tutor_profile, create_request
        with app.app_context():
            tid = _user(app, "teacher")
            create_tutor_profile(tid, "رياضيات")
            student = _user(app, "student")
            req, err = create_request(tid, student, "رياضيات", datetime.now(UTC) + timedelta(days=1))
            assert req is not None

    def test_create_request_duplicate(self, app):
        from app.services.tutoring import create_tutor_profile, create_request
        with app.app_context():
            tid = _user(app, "teacher")
            create_tutor_profile(tid, "رياضيات")
            student = _user(app, "student")
            create_request(tid, student, "رياضيات", datetime.now(UTC) + timedelta(days=1))
            req, err = create_request(tid, student, "رياضيات", datetime.now(UTC) + timedelta(days=2))
            assert req is None


# ======================================================================
# billing.py tests
# ======================================================================
class TestBillingService:
    def test_subscription_payment_summary(self, app):
        from app.services.billing import subscription_payment_summary
        with app.app_context():
            sid = _school(app)
            gid = _grade(app, sid)
            subjid = _subject(app)
            cid = _class(app, sid, gid, subjid)
            plan = SubscriptionPlan(school_id=sid, class_id=cid, name="خطة", plan="annual", price=100.0)
            _db.session.add(plan)
            _db.session.commit()
            student = _user(app)
            sub = Subscription(user_id=student, plan_id=plan.id, class_id=cid, price=100.0, status="pending")
            _db.session.add(sub)
            _db.session.commit()
            result = subscription_payment_summary(sub.id)
            assert "total_paid" in result
            assert "remaining" in result

    def test_approve_payment(self, app):
        from app.services.billing import approve_payment
        with app.app_context():
            sid = _school(app)
            gid = _grade(app, sid)
            subjid = _subject(app)
            cid = _class(app, sid, gid, subjid)
            plan = SubscriptionPlan(school_id=sid, class_id=cid, name="خطة", plan="annual", price=100.0)
            _db.session.add(plan)
            _db.session.commit()
            student = _user(app)
            sub = Subscription(user_id=student, plan_id=plan.id, class_id=cid, price=100.0, status="pending")
            _db.session.add(sub)
            _db.session.commit()
            payment = ManualPayment(subscription_id=sub.id, reference=f"ref-{_uid()[:6]}", amount=50.0, status="pending")
            _db.session.add(payment)
            _db.session.commit()
            reviewer = _user(app, "super_admin")
            approve_payment(payment, reviewer_id=reviewer)
            assert payment.status == "approved"

    def test_reject_payment(self, app):
        from app.services.billing import reject_payment
        with app.app_context():
            sid = _school(app)
            gid = _grade(app, sid)
            subjid = _subject(app)
            cid = _class(app, sid, gid, subjid)
            plan = SubscriptionPlan(school_id=sid, class_id=cid, name="خطة", plan="annual", price=100.0)
            _db.session.add(plan)
            _db.session.commit()
            student = _user(app)
            sub = Subscription(user_id=student, plan_id=plan.id, class_id=cid, price=100.0, status="pending")
            _db.session.add(sub)
            _db.session.commit()
            payment = ManualPayment(subscription_id=sub.id, reference=f"ref-{_uid()[:6]}", amount=50.0, status="pending")
            _db.session.add(payment)
            _db.session.commit()
            reviewer = _user(app, "super_admin")
            reject_payment(payment, reviewer_id=reviewer)
            assert payment.status == "rejected"


# ======================================================================
# progress.py service tests
# ======================================================================
class TestProgressService:
    def _setup(self, app):
        sid = _school(app)
        gid = _grade(app, sid)
        subjid = _subject(app)
        tid = _user(app, "teacher")
        cid = _class(app, sid, gid, subjid, tid)
        student = _user(app)
        cm = ClassMember(class_id=cid, user_id=student, status="active")
        _db.session.add(cm)
        _db.session.commit()
        lesson = Lesson(class_id=cid, title="درس", status="published", sort_order=1)
        _db.session.add(lesson)
        _db.session.commit()
        return cid, student, lesson.id

    def test_record_lesson_view(self, app):
        from app.services.progress import record_lesson_view
        with app.app_context():
            cid, student, lid = self._setup(app)
            p = record_lesson_view(student, lid, cid)
            assert p.status == "in_progress"

    def test_record_lesson_view_existing(self, app):
        from app.services.progress import record_lesson_view
        with app.app_context():
            cid, student, lid = self._setup(app)
            p1 = record_lesson_view(student, lid, cid)
            p2 = record_lesson_view(student, lid, cid)
            assert p1.id == p2.id

    def test_update_time_spent(self, app):
        from app.services.progress import record_lesson_view, update_time_spent
        with app.app_context():
            cid, student, lid = self._setup(app)
            record_lesson_view(student, lid, cid)
            p = update_time_spent(student, lid, 60)
            assert p.seconds_spent == 60

    def test_update_time_spent_not_found(self, app):
        from app.services.progress import update_time_spent
        with app.app_context():
            p = update_time_spent(99999, 99999, 60)
            assert p is None

    def test_update_video_progress(self, app):
        from app.services.progress import update_video_progress
        with app.app_context():
            cid, student, lid = self._setup(app)
            att = LessonAttachment(lesson_id=lid, kind="video", stored_name="test.mp4")
            _db.session.add(att)
            _db.session.commit()
            vp = update_video_progress(student, att.id, lid, cid, 50, 100)
            assert vp.seconds_watched == 50

    def test_update_video_progress_completed(self, app):
        from app.services.progress import update_video_progress
        with app.app_context():
            cid, student, lid = self._setup(app)
            att = LessonAttachment(lesson_id=lid, kind="video", stored_name="test.mp4")
            _db.session.add(att)
            _db.session.commit()
            vp = update_video_progress(student, att.id, lid, cid, 95, 100)
            assert vp.completed is True

    def test_student_class_progress(self, app):
        from app.services.progress import student_class_progress
        with app.app_context():
            cid, student, lid = self._setup(app)
            result = student_class_progress(student, cid)
            assert len(result) >= 1

    def test_class_progress_overview(self, app):
        from app.services.progress import class_progress_overview
        with app.app_context():
            cid, student, lid = self._setup(app)
            result = class_progress_overview(cid)
            assert len(result) >= 1

    def test_last_active_days(self, app):
        from app.services.progress import record_lesson_view, last_active_days
        with app.app_context():
            cid, student, lid = self._setup(app)
            record_lesson_view(student, lid, cid)
            days = last_active_days(student)
            assert isinstance(days, list)


# ======================================================================
# auth.py service tests  
# ======================================================================
class TestAuthService:
    def test_register_user(self, app):
        from app.services.auth import register_user
        with app.app_context():
            user, err = register_user("new@test.com", "مستخدم جديد", "student", "StrongPass123!")
            assert user is not None
            assert err is None

    def test_register_user_duplicate(self, app):
        from app.services.auth import register_user
        with app.app_context():
            email = _email()
            register_user(email, "مستخدم", "student", "StrongPass123!")
            user, err = register_user(email, "مستخدم آخر", "student", "StrongPass123!")
            assert user is None

    def test_register_user_weak_password(self, app):
        from app.services.auth import register_user
        with app.app_context():
            user, err = register_user("new@test.com", "مستخدم", "student", "weak")
            assert user is None

    def test_register_user_invalid_role(self, app):
        from app.services.auth import register_user
        with app.app_context():
            user, err = register_user("new@test.com", "مستخدم", "invalid_role", "StrongPass123!")
            assert user is None

    def test_authenticate_success(self, app):
        from app.services.auth import register_user, authenticate
        with app.app_context():
            register_user("auth@test.com", "مستخدم", "student", "StrongPass123!")
            user, err = authenticate("auth@test.com", "StrongPass123!")
            assert user is not None

    def test_authenticate_wrong_password(self, app):
        from app.services.auth import register_user, authenticate
        with app.app_context():
            register_user("auth2@test.com", "مستخدم", "student", "StrongPass123!")
            user, err = authenticate("auth2@test.com", "WrongPassword1!")
            assert user is None

    def test_authenticate_nonexistent(self, app):
        from app.services.auth import authenticate
        with app.app_context():
            user, err = authenticate("nonexistent@test.com", "password")
            assert user is None

    def test_authenticate_inactive(self, app):
        from app.services.auth import authenticate
        with app.app_context():
            uid = _user(app)
            u = User.query.get(uid)
            u.is_active = False
            _db.session.commit()
            user, err = authenticate(u.email, "TestPass123!")
            assert user is None
            assert "معطّل" in err

    def test_request_password_reset(self, app):
        from app.services.auth import request_password_reset
        with app.app_context():
            uid = _user(app)
            u = User.query.get(uid)
            token = request_password_reset(u.email)
            assert token is not None

    def test_request_password_reset_nonexistent(self, app):
        from app.services.auth import request_password_reset
        with app.app_context():
            token = request_password_reset("nonexistent@test.com")
            assert token is None

    def test_mark_login(self, app):
        from app.services.auth import mark_login
        with app.app_context():
            uid = _user(app)
            u = User.query.get(uid)
            mark_login(u)
            assert u.last_login_at is not None

    def test_register_individual(self, app):
        from app.services.auth import register_individual
        with app.app_context():
            user, err = register_individual("ind@test.com", "طالب فردي", "StrongPass123!")
            assert user is not None
            assert user.is_individual is True


# ======================================================================
# gradebook.py more tests
# ======================================================================
class TestGradebookMore:
    def _setup(self, app):
        sid = _school(app)
        gid = _grade(app, sid)
        subjid = _subject(app)
        tid = _user(app, "teacher")
        cid = _class(app, sid, gid, subjid, tid)
        return sid, cid, tid

    def test_create_grade_item(self, app):
        from app.services.gradebook import create_category, create_grade_item
        with app.app_context():
            _, cid, _ = self._setup(app)
            cat = create_category(cid, "الفصل", weight=Decimal("0.5"))
            item = create_grade_item(cat, "اختبار", max_mark=20)
            assert item.id is not None

    def test_set_grade(self, app):
        from app.services.gradebook import create_category, create_grade_item, set_grade
        with app.app_context():
            _, cid, _ = self._setup(app)
            cat = create_category(cid, "الفصل", weight=Decimal("0.5"))
            item = create_grade_item(cat, "اختبار", max_mark=20)
            student = _user(app)
            cm = ClassMember(class_id=cid, user_id=student, status="active")
            _db.session.add(cm)
            _db.session.commit()
            set_grade(student, item, Decimal("15"))
            assert GradeEntry.query.filter_by(student_id=student, grade_item_id=item.id).count() == 1

    def test_student_gradebook(self, app):
        from app.services.gradebook import create_category, create_grade_item, set_grade, student_gradebook
        with app.app_context():
            _, cid, _ = self._setup(app)
            cat = create_category(cid, "الفصل", weight=Decimal("0.5"))
            item = create_grade_item(cat, "اختبار", max_mark=20)
            student = _user(app)
            cm = ClassMember(class_id=cid, user_id=student, status="active")
            _db.session.add(cm)
            _db.session.commit()
            set_grade(student, item, Decimal("15"))
            result = student_gradebook(student, cid)
            assert len(result) >= 1

    def test_record_attendance(self, app):
        from app.services.gradebook import record_attendance, get_attendance, attendance_summary
        with app.app_context():
            _, cid, _ = self._setup(app)
            student = _user(app)
            cm = ClassMember(class_id=cid, user_id=student, status="active")
            _db.session.add(cm)
            _db.session.commit()
            record_attendance(cid, student, "present", date=datetime.now(UTC).date())
            attendees = get_attendance(cid, datetime.now(UTC).date())
            assert len(attendees) >= 1
            summary = attendance_summary(cid, student)
            assert "present" in summary

    def test_submit_assignment_resubmit(self, app):
        from app.services.gradebook import create_assignment, submit_assignment
        with app.app_context():
            _, cid, _ = self._setup(app)
            a, _ = create_assignment(cid, "واجب")
            student = _user(app)
            sub1, _ = submit_assignment(a, student, body="جواب 1")
            sub2, _ = submit_assignment(a, student, body="جواب 2")
            assert sub1.id == sub2.id
            assert sub2.body == "جواب 2"
