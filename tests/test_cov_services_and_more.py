"""Tests for more services and routes to boost coverage: communication, messages,
revenue, question_bank, quiz_stats, gradebook, family, individual, school_approvals,
schools, base, assessment, content, tutoring, billing."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from app import create_app
from app.extensions import db as _db
from app.core.security import hash_password
from app.models.billing import ManualPayment, Subscription, SubscriptionPlan
from app.models.class_room import ClassMember, ClassRoom
from app.models.communication import Announcement, ContactMessage, Notification, NotificationPreference
from app.models.content import Lesson, LessonAttachment, Unit
from app.models.family import FamilyLink, FamilyLinkCode
from app.models.gradebook import (
    Assignment,
    GradeCategory,
    GradeEntry,
    GradeItem,
    Submission,
)
from app.models.message import Message
from app.models.progress import StudentProgress, VideoProgress
from app.models.school import Grade, School, Subject
from app.models.tutoring import TutorCommission, TutorProfile, TutoringRequest, TutoringSession, TutorPayout
from app.models.user import User, UserApprovalStatus, UserRole, UserRoleLink


@pytest.fixture(scope="module")
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
            approval_status=kw.get("approval_status", UserApprovalStatus.approved),
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


def _role_link(app, user_id, school_id, role="teacher"):
    with app.app_context():
        rl = UserRoleLink(user_id=user_id, school_id=school_id, role=UserRole(role))
        _db.session.add(rl)
        _db.session.commit()
        return rl.id


# ======================================================================
# communication.py tests
# ======================================================================
class TestCommunicationService:
    def test_notify(self, app):
        from app.services.communication import notify, unread_count, mark_all_read
        with app.app_context():
            uid = _user(app)
            notify(uid, "result", "نتيجة جديدة", "حصلت على درجة 90")
            assert unread_count(uid) == 1
            mark_all_read(uid)
            assert unread_count(uid) == 0

    def test_audit(self, app):
        from app.services.communication import audit
        from flask_login import login_user
        uid = _user(app)
        with app.app_context():
            user = __import__('app.models.user', fromlist=['User']).User.query.get(uid)
            with app.test_request_context(environ_base={"REMOTE_ADDR": "127.0.0.1"}):
                login_user(user)
                audit("test.action", "users", 1, detail={"key": "value"})
                from app.models.system import AuditLog
                assert AuditLog.query.count() >= 1

    def test_audit_with_financial(self, app):
        from app.services.communication import audit
        from flask_login import login_user
        uid = _user(app)
        with app.app_context():
            user = __import__('app.models.user', fromlist=['User']).User.query.get(uid)
            with app.test_request_context(environ_base={"REMOTE_ADDR": "127.0.0.1"}):
                login_user(user)
                audit(
                    "billing.test",
                    "subscriptions",
                    1,
                    amount=100.0,
                    currency="ILS",
                    gateway="manual",
                    subscription_id=1,
                )
            from app.models.system import AuditLog
            log = AuditLog.query.first()
            assert log.detail["amount"] == 100.0

    def test_audit_with_changes(self, app):
        from app.services.communication import audit
        from flask_login import login_user
        uid = _user(app)
        with app.app_context():
            user = __import__('app.models.user', fromlist=['User']).User.query.get(uid)
            with app.test_request_context(environ_base={"REMOTE_ADDR": "127.0.0.1"}):
                login_user(user)
                audit("test.update", changes={"name": {"old": "a", "new": "b"}})
            from app.models.system import AuditLog
            log = AuditLog.query.first()
            assert "changes" in log.detail


# ======================================================================
# messages.py tests
# ======================================================================
class TestMessagesService:
    def test_send_message(self, app):
        from app.services.messages import send_message
        with app.app_context():
            sender = _user(app)
            recipient = _user(app)
            msg, err = send_message(sender, recipient, "موضوع", "نص الرسالة")
            assert msg is not None
            assert err is None

    def test_send_message_no_subject(self, app):
        from app.services.messages import send_message
        with app.app_context():
            sender = _user(app)
            recipient = _user(app)
            msg, err = send_message(sender, recipient, "", "نص")
            assert msg is None

    def test_send_message_no_body(self, app):
        from app.services.messages import send_message
        with app.app_context():
            sender = _user(app)
            recipient = _user(app)
            msg, err = send_message(sender, recipient, "موضوع", "")
            assert msg is None

    def test_send_message_to_self(self, app):
        from app.services.messages import send_message
        with app.app_context():
            uid = _user(app)
            msg, err = send_message(uid, uid, "موضوع", "نص")
            assert msg is None

    def test_send_message_nonexistent_recipient(self, app):
        from app.services.messages import send_message
        with app.app_context():
            sender = _user(app)
            msg, err = send_message(sender, 99999, "موضوع", "نص")
            assert msg is None

    def test_inbox(self, app):
        from app.services.messages import send_message, inbox
        with app.app_context():
            sender = _user(app)
            recipient = _user(app)
            send_message(sender, recipient, "موضوع", "نص")
            messages = inbox(recipient)
            assert len(messages) == 1

    def test_sent(self, app):
        from app.services.messages import send_message, sent
        with app.app_context():
            sender = _user(app)
            recipient = _user(app)
            send_message(sender, recipient, "موضوع", "نص")
            messages = sent(sender)
            assert len(messages) == 1

    def test_mark_read(self, app):
        from app.services.messages import send_message, mark_read, unread_count
        with app.app_context():
            sender = _user(app)
            recipient = _user(app)
            msg, _ = send_message(sender, recipient, "موضوع", "نص")
            assert unread_count(recipient) == 1
            mark_read(msg.id, recipient)
            assert unread_count(recipient) == 0

    def test_get_thread(self, app):
        from app.services.messages import send_message, get_thread
        with app.app_context():
            sender = _user(app)
            recipient = _user(app)
            msg, _ = send_message(sender, recipient, "موضوع", "نص")
            thread = get_thread(msg.id)
            assert thread is not None


# ======================================================================
# revenue.py tests
# ======================================================================
class TestRevenueService:
    def test_get_revenue_summary(self, app):
        from app.services.revenue import get_revenue_summary
        with app.app_context():
            result = get_revenue_summary()
            assert "total_revenue" in result
            assert "transaction_count" in result

    def test_get_revenue_by_gateway(self, app):
        from app.services.revenue import get_revenue_by_gateway
        with app.app_context():
            result = get_revenue_by_gateway()
            assert isinstance(result, list)

    def test_get_revenue_by_school(self, app):
        from app.services.revenue import get_revenue_by_school
        with app.app_context():
            result = get_revenue_by_school()
            assert isinstance(result, list)

    def test_get_monthly_revenue_trend(self, app):
        from app.services.revenue import get_monthly_revenue_trend
        with app.app_context():
            result = get_monthly_revenue_trend(6)
            assert isinstance(result, list)

    def test_get_growth_rate(self, app):
        from app.services.revenue import get_growth_rate
        with app.app_context():
            rate = get_growth_rate()
            assert isinstance(rate, float)

    def test_get_revenue_dashboard_data(self, app):
        from app.services.revenue import get_revenue_dashboard_data
        with app.app_context():
            data = get_revenue_dashboard_data(30)
            assert "summary" in data
            assert "by_gateway" in data
            assert "by_school" in data
            assert "monthly_trend" in data
            assert "growth_rate" in data


# ======================================================================
# question_bank.py tests
# ======================================================================
class TestQuestionBankService:
    def _setup(self, app):
        tid = _user(app, "teacher")
        sid = _school(app)
        return tid, sid

    def test_create_bank_question(self, app):
        from app.services.question_bank import create_bank_question
        with app.app_context():
            tid, sid = self._setup(app)
            q, err = create_bank_question(tid, sid, "ما هو 2+2؟", "mcq", difficulty=3)
            assert q is not None
            assert err is None

    def test_create_bank_question_empty_text(self, app):
        from app.services.question_bank import create_bank_question
        with app.app_context():
            tid, sid = self._setup(app)
            q, err = create_bank_question(tid, sid, "", "mcq")
            assert q is None

    def test_create_bank_question_invalid_type(self, app):
        from app.services.question_bank import create_bank_question
        with app.app_context():
            tid, sid = self._setup(app)
            q, err = create_bank_question(tid, sid, "سؤال", "invalid")
            assert q is None

    def test_create_bank_question_invalid_difficulty(self, app):
        from app.services.question_bank import create_bank_question
        with app.app_context():
            tid, sid = self._setup(app)
            q, err = create_bank_question(tid, sid, "سؤال", "mcq", difficulty=10)
            assert q is None

    def test_list_bank_questions(self, app):
        from app.services.question_bank import create_bank_question, list_bank_questions
        with app.app_context():
            tid, sid = self._setup(app)
            create_bank_question(tid, sid, "سؤال 1", "mcq")
            create_bank_question(tid, sid, "سؤال 2", "essay")
            result = list_bank_questions(tid)
            assert len(result) == 2

    def test_update_bank_question(self, app):
        from app.services.question_bank import create_bank_question, update_bank_question
        with app.app_context():
            tid, sid = self._setup(app)
            q, _ = create_bank_question(tid, sid, "سؤال", "mcq")
            updated, err = update_bank_question(q.id, tid, question_text="سؤال محدث")
            assert updated.question_text == "سؤال محدث"

    def test_delete_bank_question(self, app):
        from app.services.question_bank import create_bank_question, delete_bank_question
        with app.app_context():
            tid, sid = self._setup(app)
            q, _ = create_bank_question(tid, sid, "سؤال", "mcq")
            ok, err = delete_bank_question(q.id, tid)
            assert ok is True

    def test_delete_bank_question_wrong_teacher(self, app):
        from app.services.question_bank import create_bank_question, delete_bank_question
        with app.app_context():
            tid, sid = self._setup(app)
            tid2 = _user(app, "teacher")
            q, _ = create_bank_question(tid, sid, "سؤال", "mcq")
            ok, err = delete_bank_question(q.id, tid2)
            assert ok is False


# ======================================================================
# quiz_stats.py tests
# ======================================================================
class TestQuizStatsService:
    def test_get_quiz_stats_nonexistent(self, app):
        from app.services.quiz_stats import get_quiz_stats
        with app.app_context():
            result = get_quiz_stats(99999)
            assert result is None

    def test_get_quiz_stats_empty(self, app):
        from app.services.quiz_stats import get_quiz_stats
        from app.models.assessment import Quiz
        with app.app_context():
            sid = _school(app)
            gid = _grade(app, sid)
            subjid = _subject(app)
            cid = _class(app, sid, gid, subjid)
            quiz = Quiz(class_id=cid, title="اختبار فارغ", status="draft")
            _db.session.add(quiz)
            _db.session.commit()
            result = get_quiz_stats(quiz.id)
            assert result is not None
            assert result.total_attempts == 0
            assert result.avg_score == 0.0


# ======================================================================
# gradebook.py tests
# ======================================================================
class TestGradebookService:
    def _setup(self, app):
        tid = _user(app, "teacher")
        sid = _school(app)
        gid = _grade(app, sid)
        subjid = _subject(app)
        cid = _class(app, sid, gid, subjid, tid)
        return tid, sid, cid

    def test_create_assignment(self, app):
        from app.services.gradebook import create_assignment
        with app.app_context():
            _, _, cid = self._setup(app)
            a, err = create_assignment(cid, "واجب 1", body="محتوى")
            assert a is not None
            assert err is None

    def test_create_assignment_empty_title(self, app):
        from app.services.gradebook import create_assignment
        with app.app_context():
            _, _, cid = self._setup(app)
            a, err = create_assignment(cid, "")
            assert a is None

    def test_list_assignments(self, app):
        from app.services.gradebook import create_assignment, list_assignments
        with app.app_context():
            _, _, cid = self._setup(app)
            create_assignment(cid, "واجب 1")
            create_assignment(cid, "واجب 2")
            result = list_assignments(cid)
            assert len(result) == 2

    def test_submit_assignment(self, app):
        from app.services.gradebook import create_assignment, submit_assignment, list_submissions
        with app.app_context():
            _, _, cid = self._setup(app)
            a, _ = create_assignment(cid, "واجب 1")
            student = _user(app)
            cm = ClassMember(class_id=cid, user_id=student, status="active")
            _db.session.add(cm)
            _db.session.commit()
            sub, err = submit_assignment(a, student, body="جواب الطالب")
            assert sub is not None
            subs = list_submissions(a)
            assert len(subs) == 1

    def test_grade_submission(self, app):
        from app.services.gradebook import create_assignment, submit_assignment, grade_submission
        with app.app_context():
            _, _, cid = self._setup(app)
            a, _ = create_assignment(cid, "واجب 1", max_mark=10)
            student = _user(app)
            sub, _ = submit_assignment(a, student, body="جواب")
            grade_submission(sub, 8, feedback="جيد", graded_by=_user(app, "teacher"))
            assert sub.mark == 8

    def test_create_category(self, app):
        from app.services.gradebook import create_category, list_categories
        with app.app_context():
            _, _, cid = self._setup(app)
            c = create_category(cid, "الفصل الأول", weight=Decimal("0.5"))
            assert c.id is not None
            cats = list_categories(cid)
            assert len(cats) == 1


# ======================================================================
# family.py tests
# ======================================================================
class TestFamilyService:
    def test_generate_link_code(self, app):
        from app.services.family import generate_link_code
        with app.app_context():
            student = _user(app, "student")
            code, err = generate_link_code(student)
            assert code is not None
            assert len(code) == 8

    def test_generate_link_code_not_student(self, app):
        from app.services.family import generate_link_code
        with app.app_context():
            teacher = _user(app, "teacher")
            code, err = generate_link_code(teacher)
            assert code is None

    def test_link_parent(self, app):
        from app.services.family import generate_link_code, link_parent
        with app.app_context():
            student = _user(app, "student")
            code, _ = generate_link_code(student)
            parent = _user(app, "parent")
            link, err = link_parent(parent, code)
            assert link is not None
            assert err is None

    def test_link_parent_invalid_code(self, app):
        from app.services.family import link_parent
        with app.app_context():
            parent = _user(app, "parent")
            link, err = link_parent(parent, "INVALID")
            assert link is None

    def test_list_children(self, app):
        from app.services.family import generate_link_code, link_parent, list_children
        with app.app_context():
            student = _user(app, "student")
            code, _ = generate_link_code(student)
            parent = _user(app, "parent")
            link_parent(parent, code)
            children = list_children(parent)
            assert len(children) == 1

    def test_is_parent_of(self, app):
        from app.services.family import generate_link_code, link_parent, is_parent_of
        with app.app_context():
            student = _user(app, "student")
            code, _ = generate_link_code(student)
            parent = _user(app, "parent")
            link_parent(parent, code)
            assert is_parent_of(parent, student) is True
            assert is_parent_of(student, parent) is False

    def test_get_parent(self, app):
        from app.services.family import generate_link_code, link_parent, get_parent
        with app.app_context():
            student = _user(app, "student")
            code, _ = generate_link_code(student)
            parent = _user(app, "parent")
            link_parent(parent, code)
            found = get_parent(student)
            assert found is not None

    def test_remove_link(self, app):
        from app.services.family import generate_link_code, link_parent, remove_link, list_children
        with app.app_context():
            student = _user(app, "student")
            code, _ = generate_link_code(student)
            parent = _user(app, "parent")
            link, _ = link_parent(parent, code)
            ok, err = remove_link(link.id, parent)
            assert ok is True
            assert len(list_children(parent)) == 0


# ======================================================================
# school_approvals.py tests
# ======================================================================
class TestSchoolApprovalsService:
    def test_get_school_admins(self, app):
        from app.services.school_approvals import get_school_admins
        with app.app_context():
            sid = _school(app)
            admin = _user(app, "school_admin")
            _role_link(app, admin, sid, "school_admin")
            admins = get_school_admins(sid)
            assert len(admins) == 1

    def test_get_pending_approvals_empty(self, app):
        from app.services.school_approvals import get_pending_approvals_for_school
        with app.app_context():
            sid = _school(app)
            result = get_pending_approvals_for_school(sid)
            assert len(result) == 0

    def test_approve_user_role_link(self, app):
        from app.services.school_approvals import approve_user_role_link
        with app.app_context():
            sid = _school(app)
            student = _user(app, "student", approval_status=UserApprovalStatus.pending)
            rl = UserRoleLink(user_id=student, school_id=sid, role=UserRole.student)
            _db.session.add(rl)
            _db.session.commit()
            approver = _user(app, "super_admin")
            ok, err = approve_user_role_link(rl.id, approver)
            assert ok is True

    def test_approve_nonexistent_link(self, app):
        from app.services.school_approvals import approve_user_role_link
        with app.app_context():
            approver = _user(app, "super_admin")
            ok, err = approve_user_role_link(99999, approver)
            assert ok is False

    def test_reject_user_role_link(self, app):
        from app.services.school_approvals import reject_user_role_link
        with app.app_context():
            sid = _school(app)
            student = _user(app, "student", approval_status=UserApprovalStatus.pending)
            rl = UserRoleLink(user_id=student, school_id=sid, role=UserRole.student)
            _db.session.add(rl)
            _db.session.commit()
            approver = _user(app, "super_admin")
            ok, err = reject_user_role_link(rl.id, approver, "لا نقبل")
            assert ok is True

    def test_can_user_approve(self, app):
        from app.services.school_approvals import can_user_approve
        with app.app_context():
            sid = _school(app)
            student = _user(app, "student", approval_status=UserApprovalStatus.pending)
            rl = UserRoleLink(user_id=student, school_id=sid, role=UserRole.student)
            _db.session.add(rl)
            _db.session.commit()
            admin = _user(app, "super_admin")
            assert can_user_approve(admin, rl.id) is True

    def test_can_user_approve_regular_user(self, app):
        from app.services.school_approvals import can_user_approve
        with app.app_context():
            sid = _school(app)
            student = _user(app, "student", approval_status=UserApprovalStatus.pending)
            rl = UserRoleLink(user_id=student, school_id=sid, role=UserRole.student)
            _db.session.add(rl)
            _db.session.commit()
            regular = _user(app, "student")
            assert can_user_approve(regular, rl.id) is False


# ======================================================================
# schools.py tests
# ======================================================================
class TestSchoolsService:
    def test_create_school(self, app):
        from app.services.schools import create_school
        with app.app_context():
            s, err = create_school("مدرسة تجريبية")
            assert s is not None
            assert err is None

    def test_create_school_empty_name(self, app):
        from app.services.schools import create_school
        with app.app_context():
            s, err = create_school("")
            assert s is None

    def test_create_school_duplicate_domain(self, app):
        from app.services.schools import create_school
        with app.app_context():
            create_school("م1", domain="test.com")
            s, err = create_school("م2", domain="test.com")
            assert s is None

    def test_list_schools(self, app):
        from app.services.schools import create_school, list_schools
        with app.app_context():
            create_school("م1")
            create_school("م2")
            result = list_schools()
            assert len(result) == 2

    def test_create_class(self, app):
        from app.services.schools import create_class
        with app.app_context():
            sid = _school(app)
            gid = _grade(app, sid)
            subjid = _subject(app)
            c, err = create_class(sid, subjid, gid)
            assert c is not None
            assert c.join_code is not None

    def test_create_class_with_teacher(self, app):
        from app.services.schools import create_class
        with app.app_context():
            sid = _school(app)
            gid = _grade(app, sid)
            subjid = _subject(app)
            tid = _user(app, "teacher")
            c, err = create_class(sid, subjid, gid, teacher_id=tid)
            assert c is not None
            assert c.teacher_id == tid

    def test_regenerate_join_code(self, app):
        from app.services.schools import create_class, regenerate_join_code
        with app.app_context():
            sid = _school(app)
            gid = _grade(app, sid)
            subjid = _subject(app)
            c, _ = create_class(sid, subjid, gid)
            old_code = c.join_code
            new_code = regenerate_join_code(c)
            assert new_code != old_code

    def test_join_class(self, app):
        from app.services.schools import join_class, is_member
        with app.app_context():
            sid = _school(app)
            gid = _grade(app, sid)
            subjid = _subject(app)
            c_obj = ClassRoom(school_id=sid, subject_id=subjid, grade_id=gid,
                              join_code=f"C-{_uid()[:6]}", name=f"صف {_uid()}")
            _db.session.add(c_obj)
            _db.session.commit()
            student = _user(app, "student")
            err = join_class(c_obj, User.query.get(student))
            assert err is None
            assert is_member(c_obj, User.query.get(student)) is True

    def test_join_class_already_member(self, app):
        from app.services.schools import join_class
        with app.app_context():
            sid = _school(app)
            gid = _grade(app, sid)
            subjid = _subject(app)
            c_obj = ClassRoom(school_id=sid, subject_id=subjid, grade_id=gid,
                              join_code=f"C-{_uid()[:6]}", name=f"صف {_uid()}")
            _db.session.add(c_obj)
            _db.session.commit()
            student = _user(app, "student")
            join_class(c_obj, User.query.get(student))
            err = join_class(c_obj, User.query.get(student))
            assert err is not None

    def test_join_class_full(self, app):
        from app.services.schools import join_class
        with app.app_context():
            sid = _school(app)
            gid = _grade(app, sid)
            subjid = _subject(app)
            c_obj = ClassRoom(school_id=sid, subject_id=subjid, grade_id=gid,
                              join_code=f"C-{_uid()[:6]}", name=f"صف {_uid()}",
                              max_students=1)
            _db.session.add(c_obj)
            _db.session.commit()
            s1 = _user(app, "student")
            join_class(c_obj, User.query.get(s1))
            s2 = _user(app, "student")
            err = join_class(c_obj, User.query.get(s2))
            assert "ممتلئ" in err

    def test_get_or_create_subject(self, app):
        from app.services.schools import get_or_create_subject
        with app.app_context():
            s1 = get_or_create_subject("رياضيات")
            s2 = get_or_create_subject("رياضيات")
            assert s1.id == s2.id

    def test_add_grade(self, app):
        from app.services.schools import add_grade
        with app.app_context():
            sid = _school(app)
            g = add_grade(sid, 1, "الصف الأول")
            assert g.grade_level == 1
            g2 = add_grade(sid, 1)
            assert g.id == g2.id

    def test_create_school_with_defaults(self, app):
        from app.services.schools import create_school_with_defaults
        with app.app_context():
            s, err = create_school_with_defaults("مدرسة كاملة")
            assert s is not None
            from app.models.school import Grade
            grades = Grade.query.filter_by(school_id=s.id).count()
            assert grades == 12

    def test_get_or_create_system_school(self, app):
        from app.services.schools import get_or_create_system_school
        with app.app_context():
            s1 = get_or_create_system_school()
            s2 = get_or_create_system_school()
            assert s1.id == s2.id
            assert s1.is_system is True

    def test_join_class_individual(self, app):
        from app.services.schools import join_class_individual
        with app.app_context():
            sid = _school(app)
            gid = _grade(app, sid)
            subjid = _subject(app)
            teacher = _user(app, "teacher")
            c_obj = ClassRoom(school_id=sid, subject_id=subjid, grade_id=gid,
                              teacher_id=teacher, join_code=f"C-{_uid()[:6]}",
                              name=f"صف {_uid()}", is_public=True, price=50.0)
            _db.session.add(c_obj)
            _db.session.commit()
            student = _user(app)
            member, err = join_class_individual(student, c_obj.id)
            assert member is not None

    def test_join_class_individual_not_public(self, app):
        from app.services.schools import join_class_individual
        with app.app_context():
            sid = _school(app)
            gid = _grade(app, sid)
            subjid = _subject(app)
            c_obj = ClassRoom(school_id=sid, subject_id=subjid, grade_id=gid,
                              join_code=f"C-{_uid()[:6]}", name=f"صف {_uid()}", is_public=False)
            _db.session.add(c_obj)
            _db.session.commit()
            student = _user(app)
            member, err = join_class_individual(student, c_obj.id)
            assert member is None


# ======================================================================
# content.py tests
# ======================================================================
class TestContentService:
    def _setup(self, app):
        sid = _school(app)
        gid = _grade(app, sid)
        subjid = _subject(app)
        cid = _class(app, sid, gid, subjid)
        return sid, cid

    def test_create_unit(self, app):
        from app.services.content import create_unit, list_units
        with app.app_context():
            _, cid = self._setup(app)
            u = create_unit(cid, "الوحدة الأولى")
            assert u.id is not None
            assert len(list_units(cid)) == 1

    def test_create_lesson(self, app):
        from app.services.content import create_lesson, list_lessons
        with app.app_context():
            _, cid = self._setup(app)
            l, err = create_lesson(cid, "درس 1")
            assert l is not None
            assert err is None
            assert len(list_lessons(cid)) == 1

    def test_create_lesson_empty_title(self, app):
        from app.services.content import create_lesson
        with app.app_context():
            _, cid = self._setup(app)
            l, err = create_lesson(cid, "")
            assert l is None

    def test_get_lesson(self, app):
        from app.services.content import create_lesson, get_lesson
        with app.app_context():
            _, cid = self._setup(app)
            l, _ = create_lesson(cid, "درس")
            found = get_lesson(l.id)
            assert found is not None

    def test_publish_unpublish_lesson(self, app):
        from app.services.content import create_lesson, publish_lesson, unpublish_lesson, list_lessons
        with app.app_context():
            _, cid = self._setup(app)
            l, _ = create_lesson(cid, "درس")
            assert l.status == "draft"
            publish_lesson(l)
            published = list_lessons(cid, include_drafts=False)
            assert len(published) == 1
            unpublish_lesson(l)
            published = list_lessons(cid, include_drafts=False)
            assert len(published) == 0

    def test_update_lesson(self, app):
        from app.services.content import create_lesson, update_lesson
        with app.app_context():
            _, cid = self._setup(app)
            l, _ = create_lesson(cid, "درس قديم")
            update_lesson(l, title="درس جديد", unit_id=None, body_html="<p>محتوى</p>")
            assert l.title == "درس جديد"

    def test_add_youtube(self, app):
        from app.services.content import create_lesson, add_youtube
        with app.app_context():
            _, cid = self._setup(app)
            l, _ = create_lesson(cid, "درس")
            att = add_youtube(l, "https://youtube.com/watch?v=123", "فيديو")
            assert att.youtube_url is not None

    def test_delete_attachment(self, app):
        from app.services.content import create_lesson, add_youtube, delete_attachment
        with app.app_context():
            _, cid = self._setup(app)
            l, _ = create_lesson(cid, "درس")
            att = add_youtube(l, "https://youtube.com/watch?v=123")
            delete_attachment(att)
            from app.models.content import LessonAttachment
            assert LessonAttachment.query.get(att.id) is None

    def test_shared_lessons(self, app):
        from app.services.content import create_lesson, shared_lessons
        with app.app_context():
            sid, cid = self._setup(app)
            l, _ = create_lesson(cid, "درس مشترك")
            l.is_shared = True
            _db.session.commit()
            result = shared_lessons(sid)
            assert len(result) == 1

    def test_sanitize_html(self, app):
        from app.services.content import _sanitize_html
        with app.app_context():
            clean = _sanitize_html("<p>نص</p><script>alert('x')</script>")
            assert "<script>" not in clean
            assert "<p>" in clean

    def test_sanitize_html_none(self, app):
        from app.services.content import _sanitize_html
        with app.app_context():
            assert _sanitize_html(None) is None

    def test_import_lesson(self, app):
        from app.services.content import create_lesson, import_lesson
        with app.app_context():
            sid, cid = self._setup(app)
            gid2 = _grade(app, sid, grade_level=2)
            subjid2 = _subject(app)
            cid2 = _class(app, sid, gid2, subjid2)
            l, _ = create_lesson(cid, "درس للتصدير")
            l.is_shared = True
            _db.session.commit()
            new_l, err = import_lesson(l.id, cid2, _user(app))
            assert new_l is not None
            assert new_l.class_id == cid2
