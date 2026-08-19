"""مشتركات الاختبارات — مصنع التطبيق + مُنشئ بيانات تجريبية."""

from __future__ import annotations

import uuid
from datetime import UTC

import pytest
from app import create_app
from app.core.security import hash_password
from app.extensions import db as _db
from app.models.billing import ManualPayment, Subscription, SubscriptionPlan
from app.models.calendar import AcademicEvent
from app.models.class_room import ClassMember, ClassRoom
from app.models.content import Lesson, LessonAttachment
from app.models.family import FamilyLink, FamilyLinkCode
from app.models.gradebook import GradeCategory, GradeEntry, GradeItem
from app.models.progress import StudentProgress, VideoProgress
from app.models.school import Grade, School, Subject
from app.models.tenant import TenantQuota
from app.models.user import User, UserApprovalStatus, UserRole, UserRoleLink


def _ensure_phase2_schema(db_engine):
    """Ensure Phase 2+ columns/tables exist (migration pending separately)."""
    from sqlalchemy import text

    try:
        # Phase 2 (previous batch)
        db_engine.session.execute(
            text("ALTER TABLE quizzes ADD COLUMN IF NOT EXISTS enable_proctoring BOOLEAN DEFAULT FALSE NOT NULL")
        )
        db_engine.session.execute(
            text("ALTER TABLE quizzes ADD COLUMN IF NOT EXISTS max_tab_switches INTEGER DEFAULT 3 NOT NULL")
        )
        db_engine.session.execute(
            text("ALTER TABLE quizzes ADD COLUMN IF NOT EXISTS fullscreen_required BOOLEAN DEFAULT FALSE NOT NULL")
        )
        db_engine.session.execute(
            text(
                "CREATE TABLE IF NOT EXISTS proctoring_logs ("
                "id SERIAL PRIMARY KEY, attempt_id INTEGER NOT NULL REFERENCES quiz_attempts(id), "
                "event_type VARCHAR(20) NOT NULL, timestamp TIMESTAMPTZ DEFAULT NOW(), "
                "created_at TIMESTAMPTZ DEFAULT NOW(), updated_at TIMESTAMPTZ DEFAULT NOW())"
            )
        )
        db_engine.session.execute(
            text(
                "CREATE TABLE IF NOT EXISTS question_bank ("
                "id SERIAL PRIMARY KEY, teacher_id INTEGER NOT NULL REFERENCES users(id), "
                "school_id INTEGER NOT NULL REFERENCES schools(id), subject_id INTEGER REFERENCES subjects(id), "
                "question_text TEXT NOT NULL, question_type VARCHAR(15) NOT NULL, "
                "options JSONB, correct_answer JSONB, difficulty SMALLINT DEFAULT 3 NOT NULL, "
                "tags JSONB, is_shared BOOLEAN DEFAULT FALSE NOT NULL, "
                "created_at TIMESTAMPTZ DEFAULT NOW(), updated_at TIMESTAMPTZ DEFAULT NOW())"
            )
        )
        db_engine.session.execute(
            text(
                "CREATE TABLE IF NOT EXISTS messages ("
                "id SERIAL PRIMARY KEY, sender_id INTEGER NOT NULL REFERENCES users(id), "
                "recipient_id INTEGER NOT NULL REFERENCES users(id), "
                "subject TEXT NOT NULL, body TEXT NOT NULL, "
                "is_read BOOLEAN DEFAULT FALSE NOT NULL, "
                "parent_message_id INTEGER REFERENCES messages(id), "
                "created_at TIMESTAMPTZ DEFAULT NOW(), updated_at TIMESTAMPTZ DEFAULT NOW())"
            )
        )

        # Phase 3 (current batch)
        # Lessons: is_shared, original_lesson_id
        db_engine.session.execute(
            text("ALTER TABLE lessons ADD COLUMN IF NOT EXISTS is_shared BOOLEAN DEFAULT FALSE NOT NULL")
        )
        db_engine.session.execute(
            text("ALTER TABLE lessons ADD COLUMN IF NOT EXISTS original_lesson_id INTEGER REFERENCES lessons(id)")
        )
        # Tutoring sessions: end_time
        db_engine.session.execute(text("ALTER TABLE tutoring_sessions ADD COLUMN IF NOT EXISTS end_time TIMESTAMPTZ"))
        # Tutor reviews table
        db_engine.session.execute(
            text(
                "CREATE TABLE IF NOT EXISTS tutor_reviews ("
                "id SERIAL PRIMARY KEY, session_id INTEGER NOT NULL REFERENCES tutoring_sessions(id), "
                "student_id INTEGER NOT NULL REFERENCES users(id), rating SMALLINT NOT NULL, "
                "comment TEXT, created_at TIMESTAMPTZ DEFAULT NOW(), updated_at TIMESTAMPTZ DEFAULT NOW(), "
                "UNIQUE(session_id, student_id))"
            )
        )

        # Phase 4 (current batch: Payment Gateway Auto-Activation, Payment Reminders, Discount/Coupon)
        # Subscriptions: auto_activated_at, status pending_review
        db_engine.session.execute(
            text("ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS auto_activated_at TIMESTAMPTZ")
        )
        db_engine.session.execute(text("ALTER TABLE subscriptions ALTER COLUMN status TYPE VARCHAR(20)"))
        # ManualPayments: gateway
        db_engine.session.execute(text("ALTER TABLE manual_payments ADD COLUMN IF NOT EXISTS gateway VARCHAR(20)"))
        # ReminderLogs table
        db_engine.session.execute(
            text(
                "CREATE TABLE IF NOT EXISTS reminder_logs ("
                "id SERIAL PRIMARY KEY, subscription_id INTEGER NOT NULL REFERENCES subscriptions(id), "
                "reminder_type VARCHAR(10) NOT NULL, sent_at TIMESTAMPTZ DEFAULT NOW(), "
                "UNIQUE(subscription_id, reminder_type))"
            )
        )

        # Phase 5 (current batch: School-Level Approvals, Revenue Tracking, payments_ui)
        # UserRoleLink: approved_by, approved_at
        db_engine.session.execute(
            text("ALTER TABLE user_role_links ADD COLUMN IF NOT EXISTS approved_by INTEGER REFERENCES users(id)")
        )
        db_engine.session.execute(text("ALTER TABLE user_role_links ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ"))

        # Phase 6: Rubric, Appeals, Offline, Notification Prefs, Health
        db_engine.session.execute(
            text(
                "CREATE TABLE IF NOT EXISTS rubric_templates ("
                "id SERIAL PRIMARY KEY, teacher_id INTEGER NOT NULL REFERENCES users(id), "
                "school_id INTEGER NOT NULL REFERENCES schools(id), "
                "title TEXT NOT NULL, description TEXT, "
                "created_at TIMESTAMPTZ DEFAULT NOW(), updated_at TIMESTAMPTZ DEFAULT NOW())"
            )
        )
        db_engine.session.execute(
            text(
                "CREATE TABLE IF NOT EXISTS rubric_criteria ("
                "id SERIAL PRIMARY KEY, template_id INTEGER NOT NULL REFERENCES rubric_templates(id), "
                "title TEXT NOT NULL, description TEXT, max_score NUMERIC(5,2) NOT NULL, "
                "sort_order SMALLINT, created_at TIMESTAMPTZ DEFAULT NOW(), updated_at TIMESTAMPTZ DEFAULT NOW())"
            )
        )
        db_engine.session.execute(
            text(
                "CREATE TABLE IF NOT EXISTS rubric_grades ("
                "id SERIAL PRIMARY KEY, submission_id INTEGER NOT NULL REFERENCES submissions(id), "
                "criterion_id INTEGER NOT NULL REFERENCES rubric_criteria(id), "
                "score NUMERIC(5,2) NOT NULL, comment TEXT, graded_by INTEGER REFERENCES users(id), "
                "created_at TIMESTAMPTZ DEFAULT NOW(), updated_at TIMESTAMPTZ DEFAULT NOW(), "
                "UNIQUE(submission_id, criterion_id))"
            )
        )

        db_engine.session.execute(
            text(
                "CREATE TABLE IF NOT EXISTS grade_appeals ("
                "id SERIAL PRIMARY KEY, submission_id INTEGER NOT NULL REFERENCES submissions(id), "
                "student_id INTEGER NOT NULL REFERENCES users(id), reason TEXT NOT NULL, "
                "status VARCHAR(15) DEFAULT 'pending' NOT NULL, teacher_response TEXT, "
                "reviewed_by INTEGER REFERENCES users(id), reviewed_at TIMESTAMPTZ, "
                "created_at TIMESTAMPTZ DEFAULT NOW(), updated_at TIMESTAMPTZ DEFAULT NOW(), "
                "UNIQUE(submission_id, student_id))"
            )
        )

        db_engine.session.execute(text("ALTER TABLE classes ADD COLUMN IF NOT EXISTS max_students SMALLINT"))

        db_engine.session.execute(
            text(
                "CREATE TABLE IF NOT EXISTS notification_preferences ("
                "id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), "
                "notif_type TEXT NOT NULL, email_enabled BOOLEAN DEFAULT TRUE NOT NULL, "
                "in_app_enabled BOOLEAN DEFAULT TRUE NOT NULL, "
                "created_at TIMESTAMPTZ DEFAULT NOW(), updated_at TIMESTAMPTZ DEFAULT NOW(), "
                "UNIQUE(user_id, notif_type))"
            )
        )

        db_engine.session.execute(
            text(
                "CREATE TABLE IF NOT EXISTS onboarding_progress ("
                "id SERIAL PRIMARY KEY, school_id INTEGER NOT NULL REFERENCES schools(id) UNIQUE, "
                "current_step SMALLINT DEFAULT 1 NOT NULL, total_steps SMALLINT DEFAULT 5 NOT NULL, "
                "completed_steps JSONB, is_complete BOOLEAN DEFAULT FALSE NOT NULL, "
                "completed_at TIMESTAMPTZ, created_at TIMESTAMPTZ DEFAULT NOW(), updated_at TIMESTAMPTZ DEFAULT NOW())"
            )
        )

        db_engine.session.execute(
            text(
                "CREATE TABLE IF NOT EXISTS health_checks ("
                "id SERIAL PRIMARY KEY, component VARCHAR(50) NOT NULL, "
                "status VARCHAR(10) NOT NULL, message TEXT, latency_ms BIGINT, "
                "checked_at TIMESTAMPTZ DEFAULT NOW(), created_at TIMESTAMPTZ DEFAULT NOW(), "
                "updated_at TIMESTAMPTZ DEFAULT NOW())"
            )
        )

        # Phase 8: MOE Integration & Certificate Templates
        db_engine.session.execute(
            text("ALTER TABLE subjects ADD COLUMN IF NOT EXISTS moe_code VARCHAR(50)")
        )
        db_engine.session.execute(
            text("ALTER TABLE subjects ADD COLUMN IF NOT EXISTS moe_curriculum_version VARCHAR(50)")
        )
        db_engine.session.execute(
            text(
                "CREATE TABLE IF NOT EXISTS certificate_templates ("
                "id SERIAL PRIMARY KEY, school_id INTEGER REFERENCES schools(id), "
                "name TEXT NOT NULL, template_html TEXT DEFAULT '' NOT NULL, "
                "is_active BOOLEAN DEFAULT TRUE NOT NULL, "
                "created_at TIMESTAMPTZ DEFAULT NOW(), updated_at TIMESTAMPTZ DEFAULT NOW())"
            )
        )

        # Phase 9: Zoom + Production Hardening
        db_engine.session.execute(
            text("ALTER TABLE tutor_profiles ADD COLUMN IF NOT EXISTS video_provider VARCHAR(10) DEFAULT 'jitsi' NOT NULL")
        )
        db_engine.session.execute(
            text("ALTER TABLE tutoring_sessions ADD COLUMN IF NOT EXISTS video_provider VARCHAR(10) DEFAULT 'jitsi' NOT NULL")
        )
        db_engine.session.execute(text("ALTER TABLE tutoring_sessions ADD COLUMN IF NOT EXISTS zoom_meeting_id VARCHAR(64)"))
        db_engine.session.execute(text("ALTER TABLE tutoring_sessions ADD COLUMN IF NOT EXISTS zoom_join_url TEXT"))
        db_engine.session.execute(text("ALTER TABLE tutoring_sessions ADD COLUMN IF NOT EXISTS zoom_start_url TEXT"))

        # Phase 7: Hybrid Tenancy
        db_engine.session.execute(
            text("ALTER TABLE schools ADD COLUMN IF NOT EXISTS is_system BOOLEAN DEFAULT FALSE NOT NULL")
        )
        db_engine.session.execute(
            text("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_individual BOOLEAN DEFAULT FALSE NOT NULL")
        )
        db_engine.session.execute(
            text("ALTER TABLE classes ADD COLUMN IF NOT EXISTS is_public BOOLEAN DEFAULT FALSE NOT NULL")
        )
        db_engine.session.execute(text("ALTER TABLE classes ADD COLUMN IF NOT EXISTS price NUMERIC(10,2)"))
        db_engine.session.execute(text("ALTER TABLE classes ADD COLUMN IF NOT EXISTS duration_days SMALLINT"))

        db_engine.session.commit()
    except Exception:
        db_engine.session.rollback()


@pytest.fixture()
def app():
    a = create_app()
    a.config["TESTING"] = True
    a.config["WTF_CSRF_ENABLED"] = False
    a.config["EMAIL_ENABLED"] = False
    a.config["TALISMAN_ENABLED"] = False
    a.config["SESSION_COOKIE_SECURE"] = False
    with a.app_context():
        from sqlalchemy import text

        _db.session.execute(text("CREATE EXTENSION IF NOT EXISTS citext"))
        _db.session.commit()
        _db.create_all()
        _ensure_phase2_schema(_db)
    yield a


@pytest.fixture()
def client(app):
    return app.test_client()


def _uid() -> str:
    return uuid.uuid4().hex[:10]


def _email() -> str:
    return f"u-{_uid()}@test.com"


def make_school(app, **kw):
    with app.app_context():
        s = School(
            name_ar=kw.get("name_ar", f"مدرسة {_uid()}"),
            name_en=kw.get("name_en", f"School {_uid()}"),
            domain=f"{_uid()}.test.org",
        )
        _db.session.add(s)
        _db.session.commit()
        return s.id


def make_user(app, role="student", school_id=None, approved=True, **kw):
    with app.app_context():
        u = User(
            email=kw.get("email", _email()),
            name_ar=kw.get("name_ar", f"مستخدم {_uid()}"),
            role=UserRole(role),
            password_hash=hash_password("TestPass123!"),
            approval_status=UserApprovalStatus.approved if approved else UserApprovalStatus.pending,
            is_active=True,
        )
        _db.session.add(u)
        _db.session.commit()
        if school_id:
            from app.models.user import UserRoleLink

            rl = UserRoleLink(user_id=u.id, school_id=school_id, role=UserRole(role))
            _db.session.add(rl)
            _db.session.commit()
        return u.id


def make_grade(app, school_id, grade_level=1):
    with app.app_context():
        g = Grade(school_id=school_id, grade_level=grade_level, name_ar=f"صف {grade_level}")
        _db.session.add(g)
        _db.session.commit()
        return g.id


def make_subject(app, name=None):
    with app.app_context():
        s = Subject(name_ar=name or f"مادة {_uid()}")
        _db.session.add(s)
        _db.session.commit()
        return s.id


def make_class(app, school_id, grade_id, subject_id, teacher_id=None):
    with app.app_context():
        c = ClassRoom(
            school_id=school_id,
            grade_id=grade_id,
            subject_id=subject_id,
            teacher_id=teacher_id,
            join_code=f"C-{_uid()[:6]}",
            name=f"صف {_uid()}",
        )
        _db.session.add(c)
        _db.session.commit()
        return c.id


def make_class_member(app, class_id, user_id, status="active"):
    with app.app_context():
        m = ClassMember(class_id=class_id, user_id=user_id, status=status)
        _db.session.add(m)
        _db.session.commit()
        return m.id


def make_lesson(app, class_id, title=None, status="published"):
    with app.app_context():
        l = Lesson(class_id=class_id, title=title or f"درس {_uid()}", status=status, sort_order=1)
        _db.session.add(l)
        _db.session.commit()
        return l.id


def make_attachment(app, lesson_id, kind="video", youtube_url=None):
    with app.app_context():
        a = LessonAttachment(
            lesson_id=lesson_id,
            kind=kind,
            stored_name=f"{_uid()}.mp4",
            youtube_url=youtube_url,
        )
        _db.session.add(a)
        _db.session.commit()
        return a.id


def make_grade_category(app, class_id, name, weight):
    with app.app_context():
        c = GradeCategory(class_id=class_id, name=name, weight=weight)
        _db.session.add(c)
        _db.session.commit()
        return c.id


def make_grade_item(app, class_id, category_id, title, max_mark):
    with app.app_context():
        i = GradeItem(class_id=class_id, category_id=category_id, title=title, max_mark=max_mark)
        _db.session.add(i)
        _db.session.commit()
        return i.id


def make_grade_entry(app, student_id, grade_item_id, mark):
    with app.app_context():
        e = GradeEntry(student_id=student_id, grade_item_id=grade_item_id, mark=mark)
        _db.session.add(e)
        _db.session.commit()
        return e.id


def make_subscription_plan(app, school_id, class_id=None, name=None, price=100.0, plan="annual"):
    with app.app_context():
        p = SubscriptionPlan(
            school_id=school_id,
            class_id=class_id,
            name=name or f"خطة {_uid()}",
            plan=plan,
            price=price,
        )
        _db.session.add(p)
        _db.session.commit()
        return p.id


def make_subscription(app, user_id, plan_id, class_id, price=100.0, status="pending"):
    with app.app_context():
        s = Subscription(user_id=user_id, plan_id=plan_id, class_id=class_id, price=price, status=status)
        _db.session.add(s)
        _db.session.commit()
        return s.id


def make_payment(app, subscription_id, reference=None, amount=50.0, status="approved"):
    with app.app_context():
        p = ManualPayment(
            subscription_id=subscription_id,
            reference=reference or f"ref-{_uid()[:6]}",
            amount=amount,
            status=status,
        )
        _db.session.add(p)
        _db.session.commit()
        return p.id


def make_family_link(app, parent_id, student_id):
    with app.app_context():
        f = FamilyLink(parent_id=parent_id, student_id=student_id, status="active")
        _db.session.add(f)
        _db.session.commit()
        return f.id


def make_family_link_code(app, student_id, code=None):
    with app.app_context():
        c = FamilyLinkCode(student_id=student_id, code=code or f"CODE-{_uid()[:6]}")
        _db.session.add(c)
        _db.session.commit()
        return c.id


def make_student_progress(app, student_id, lesson_id, class_id, status="completed", pct=50, seconds=300):
    with app.app_context():
        p = StudentProgress(
            student_id=student_id,
            lesson_id=lesson_id,
            class_id=class_id,
            status=status,
            progress_pct=pct,
            seconds_spent=seconds,
        )
        _db.session.add(p)
        _db.session.commit()
        return p.id


def make_video_progress(app, student_id, attachment_id, lesson_id, class_id, seconds_watched=30, total_seconds=100):
    with app.app_context():
        v = VideoProgress(
            student_id=student_id,
            attachment_id=attachment_id,
            lesson_id=lesson_id,
            class_id=class_id,
            seconds_watched=seconds_watched,
            total_seconds=total_seconds,
        )
        _db.session.add(v)
        _db.session.commit()
        return v.id


def make_academic_event(app, school_id, title, event_type, start_date, end_date=None):
    with app.app_context():

        e = AcademicEvent(
            school_id=school_id,
            title=title,
            event_type=event_type,
            start_date=start_date,
            end_date=end_date,
        )
        _db.session.add(e)
        _db.session.commit()
        return e.id


def make_tenant_quota(app, school_id, tier="free", **kw):
    with app.app_context():
        q = TenantQuota(
            school_id=school_id,
            tier=tier,
            max_students=kw.get("max_students", 50),
            max_teachers=kw.get("max_teachers", 10),
            max_classes=kw.get("max_classes", 20),
        )
        _db.session.add(q)
        _db.session.commit()
        return q.id


def make_tutor_profile(app, tutor_id, subject="رياضيات", price_hour=100.0):
    with app.app_context():
        import secrets

        from app.models.tutoring import TutorProfile

        code = secrets.token_urlsafe(8)
        while TutorProfile.query.filter_by(invite_code=code).first():
            code = secrets.token_urlsafe(8)
        p = TutorProfile(tutor_id=tutor_id, subject=subject, price_hour=price_hour, invite_code=code, is_active=True)
        _db.session.add(p)
        _db.session.commit()
        return p.id


def make_tutoring_session(app, tutor_id, student_id, subject="رياضيات", status="completed", price=100.0, end_time=None):
    with app.app_context():
        from datetime import datetime, timedelta

        from app.models.tutoring import TutoringSession

        scheduled_at = datetime.now(UTC) - timedelta(days=1)
        if end_time is None:
            end_time = scheduled_at + timedelta(hours=1)
        s = TutoringSession(
            tutor_id=tutor_id,
            student_id=student_id,
            subject=subject,
            scheduled_at=scheduled_at,
            duration_min=60,
            price=price,
            status=status,
            payment_status="paid",
            end_time=end_time,
        )
        _db.session.add(s)
        _db.session.commit()
        return s.id


def make_tutor_review(app, session_id, student_id, rating=5, comment="جيد"):
    with app.app_context():
        from app.models.tutoring import TutorReview

        r = TutorReview(session_id=session_id, student_id=student_id, rating=rating, comment=comment)
        _db.session.add(r)
        _db.session.commit()
        return r.id


def make_reminder_log(app, subscription_id, reminder_type="7d"):
    with app.app_context():
        from app.models.billing import ReminderLog

        r = ReminderLog(subscription_id=subscription_id, reminder_type=reminder_type)
        _db.session.add(r)
        _db.session.commit()


def make_user_role_link(app, user_id, school_id, role="teacher", approved_by=None, approved_at=None, is_active=True):
    with app.app_context():
        from app.models.user import UserRole, UserRoleLink

        rl = UserRoleLink(
            user_id=user_id,
            school_id=school_id,
            role=UserRole(role),
            is_active=is_active,
            approved_by=approved_by,
            approved_at=approved_at,
        )
        _db.session.add(rl)
        _db.session.commit()
        return rl.id


def make_revenue_ledger_entry(app, school_id, amount, currency="ILS", gateway="manual", subscription_id=None):
    with app.app_context():

        # This is a helper to create test revenue data
        # We'll use ManualPayment as the ledger entry
        pass
        return r.id


def make_system_school(app):
    with app.app_context():
        from app.services.schools import get_or_create_system_school

        s = get_or_create_system_school()
        return s.id


def make_individual_user(app, school_id=None, **kw):
    """Create an individual (non-school) user."""
    with app.app_context():
        u = User(
            email=kw.get("email", _email()),
            name_ar=kw.get("name_ar", f"طالب فردي {_uid()}"),
            role=UserRole.student,
            password_hash=hash_password("TestPass123!"),
            approval_status=UserApprovalStatus.approved,
            is_active=True,
            is_individual=True,
        )
        _db.session.add(u)
        _db.session.commit()
        if school_id:
            rl = UserRoleLink(user_id=u.id, school_id=school_id, role=UserRole.student)
            _db.session.add(rl)
            _db.session.commit()
        return u.id


def make_public_class(app, school_id, grade_id, subject_id, teacher_id=None, price=50.0):
    with app.app_context():
        c = ClassRoom(
            school_id=school_id,
            grade_id=grade_id,
            subject_id=subject_id,
            teacher_id=teacher_id,
            join_code=f"PC-{_uid()[:6]}",
            name=f"صف عام {_uid()}",
            is_public=True,
            price=price,
            duration_days=30,
        )
        _db.session.add(c)
        _db.session.commit()
        return c.id
