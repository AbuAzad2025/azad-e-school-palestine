"""Deep coverage tests for changed files (content.py, family.py, finance.py)
and under-covered services (impersonation, invoice, calendar, access, base, payments).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from app import create_app
from app.extensions import db as _db
from app.core.security import hash_password
from app.models.billing import ManualPayment, Subscription, SubscriptionPlan
from app.models.class_room import ClassMember, ClassRoom
from app.models.content import Lesson, LessonAttachment, Unit
from app.models.family import FamilyLink, FamilyLinkCode
from app.models.school import Grade, School, Subject
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
# content.py — deeper tests
# ======================================================================
class TestContentDeep:
    def _setup(self, app):
        sid = _school(app)
        gid = _grade(app, sid)
        subjid = _subject(app)
        tid = _user(app, "teacher")
        cid = _class(app, sid, gid, subjid, tid)
        return sid, gid, subjid, tid, cid

    def test_import_lesson_not_shared(self, app):
        from app.services.content import create_lesson, import_lesson
        with app.app_context():
            sid, gid, subjid, tid, cid = self._setup(app)
            cid2 = _class(app, sid, gid, subjid)
            l, _ = create_lesson(cid, "درس خاص")
            # is_shared defaults to False
            new_l, err = import_lesson(l.id, cid2, tid)
            assert new_l is None
            assert "خاصة" in err or "special" in err.lower() or "لا يمكن" in err

    def test_import_lesson_nonexistent_lesson(self, app):
        from app.services.content import import_lesson
        with app.app_context():
            sid, gid, subjid, tid, cid = self._setup(app)
            cid2 = _class(app, sid, gid, subjid)
            new_l, err = import_lesson(99999, cid2, tid)
            assert new_l is None
            assert "غير موجود" in err or "not found" in err.lower()

    def test_import_lesson_nonexistent_target_class(self, app):
        from app.services.content import create_lesson, import_lesson
        with app.app_context():
            sid, gid, subjid, tid, cid = self._setup(app)
            l, _ = create_lesson(cid, "درس مشترك")
            l.is_shared = True
            _db.session.commit()
            new_l, err = import_lesson(l.id, 99999, tid)
            assert new_l is None
            assert "الصف" in err or "class" in err.lower() or "غير موجود" in err

    def test_import_lesson_copies_attachments(self, app):
        from app.services.content import create_lesson, import_lesson, add_youtube
        with app.app_context():
            sid, gid, subjid, tid, cid = self._setup(app)
            cid2 = _class(app, sid, gid, subjid)
            l, _ = create_lesson(cid, "درس مع مرفقات")
            l.is_shared = True
            _db.session.commit()
            add_youtube(l, "https://youtube.com/watch?v=abc", "فيديو 1")
            add_youtube(l, "https://youtube.com/watch?v=def", "فيديو 2")
            new_l, err = import_lesson(l.id, cid2, tid)
            assert new_l is not None
            assert len(new_l.attachments) == 2
            assert new_l.original_lesson_id == l.id
            assert new_l.is_shared is False

    def test_list_lessons_exclude_drafts(self, app):
        from app.services.content import create_lesson, publish_lesson, list_lessons
        with app.app_context():
            sid, gid, subjid, tid, cid = self._setup(app)
            create_lesson(cid, "مسودة")
            l2, _ = create_lesson(cid, "منشورة")
            publish_lesson(l2)
            published = list_lessons(cid, include_drafts=False)
            assert len(published) == 1
            assert published[0].title == "منشورة"

    def test_list_lessons_include_drafts(self, app):
        from app.services.content import create_lesson, list_lessons
        with app.app_context():
            sid, gid, subjid, tid, cid = self._setup(app)
            create_lesson(cid, "مسودة 1")
            create_lesson(cid, "مسودة 2")
            all_lessons = list_lessons(cid, include_drafts=True)
            assert len(all_lessons) == 2

    def test_shared_lessons_with_subject_filter(self, app):
        from app.services.content import create_lesson, shared_lessons
        with app.app_context():
            sid, gid, subjid, tid, cid = self._setup(app)
            subjid2 = _subject(app)
            cid2 = _class(app, sid, gid, subjid2)
            l1, _ = create_lesson(cid, "درس مادة 1")
            l1.is_shared = True
            l2, _ = create_lesson(cid2, "درس مادة 2")
            l2.is_shared = True
            _db.session.commit()
            result = shared_lessons(sid, subject_id=subjid)
            assert len(result) == 1

    def test_shared_lessons_empty(self, app):
        from app.services.content import shared_lessons
        with app.app_context():
            sid = _school(app)
            result = shared_lessons(sid)
            assert len(result) == 0

    def test_create_lesson_with_unit(self, app):
        from app.services.content import create_unit, create_lesson, get_lesson
        with app.app_context():
            sid, gid, subjid, tid, cid = self._setup(app)
            unit = create_unit(cid, "الوحدة الأولى")
            l, _ = create_lesson(cid, "درس 1", unit_id=unit.id, body_html="<h1>مرحبا</h1>")
            assert l.unit_id == unit.id
            fetched = get_lesson(l.id)
            assert fetched.body_html == "<h1>مرحبا</h1>"

    def test_sanitize_html_strips_script(self):
        from app.services.content import _sanitize_html
        result = _sanitize_html("<p>نص</p><script>alert('xss')</script><strong>عريض</strong>")
        assert "<script>" not in result
        assert "<p>نص</p>" in result
        assert "<strong>عريض</strong>" in result

    def test_sanitize_html_strips_iframe(self):
        from app.services.content import _sanitize_html
        result = _sanitize_html('<iframe src="evil.com"></iframe><p>amigo</p>')
        assert "<iframe>" not in result
        assert "<p>amigo</p>" in result

    def test_sanitize_html_empty_string(self):
        from app.services.content import _sanitize_html
        assert _sanitize_html("") == ""

    def test_update_lesson_increments_version(self, app):
        from app.services.content import create_lesson, update_lesson
        with app.app_context():
            sid, gid, subjid, tid, cid = self._setup(app)
            l, _ = create_lesson(cid, "درس")
            assert l.version == 1
            update_lesson(l, title="درس محدث", unit_id=None, body_html=None)
            assert l.version == 2


# ======================================================================
# family.py — deeper tests
# ======================================================================
class TestFamilyDeep:
    def test_link_parent_empty_code(self, app):
        from app.services.family import link_parent
        with app.app_context():
            parent = _user(app, "parent")
            link, err = link_parent(parent, "")
            assert link is None
            assert "الرمز مطلوب" in err

    def test_link_parent_none_code(self, app):
        from app.services.family import link_parent
        with app.app_context():
            parent = _user(app, "parent")
            link, err = link_parent(parent, None)
            assert link is None
            assert "الرمز مطلوب" in err

    def test_link_parent_not_parent_role(self, app):
        from app.services.family import link_parent
        with app.app_context():
            student = _user(app, "student")
            link, err = link_parent(student, "SOMECODE")
            assert link is None
            assert "ولي أمر" in err or "parent" in err.lower()

    def test_link_parent_expired_code(self, app):
        from app.services.family import generate_link_code, link_parent
        with app.app_context():
            student = _user(app, "student")
            code, _ = generate_link_code(student)
            # Manually expire the code
            flc = FamilyLinkCode.query.filter_by(code=code).first()
            flc.expires_at = datetime.now(UTC) - timedelta(hours=1)
            _db.session.commit()
            parent = _user(app, "parent")
            link, err = link_parent(parent, code)
            assert link is None
            assert "انتهت صلاحية" in err or "expired" in err.lower()

    def test_link_parent_self_link(self, app):
        from app.services.family import link_parent
        from app.models.family import FamilyLinkCode
        with app.app_context():
            parent = _user(app, "parent")
            # Manually insert a link code where student_id == parent_id
            code = f"SELF{_uid()[:4]}".upper()
            flc = FamilyLinkCode(student_id=parent, code=code, used=False)
            _db.session.add(flc)
            _db.session.commit()
            link, err = link_parent(parent, code)
            assert link is None
            assert "بنفسه" in err or "himself" in err.lower()

    def test_link_parent_duplicate(self, app):
        from app.services.family import generate_link_code, link_parent
        with app.app_context():
            student = _user(app, "student")
            code, _ = generate_link_code(student)
            parent = _user(app, "parent")
            link1, _ = link_parent(parent, code)
            assert link1 is not None
            # Try linking again
            code2, _ = generate_link_code(student)
            link2, err = link_parent(parent, code2)
            assert link2 is None
            assert "مسبقاً" in err or "already" in err.lower()

    def test_remove_link_wrong_parent(self, app):
        from app.services.family import generate_link_code, link_parent, remove_link
        with app.app_context():
            student = _user(app, "student")
            code, _ = generate_link_code(student)
            parent1 = _user(app, "parent")
            link, _ = link_parent(parent1, code)
            parent2 = _user(app, "parent")
            ok, err = remove_link(link.id, parent2)
            assert ok is False
            assert "غير موجود" in err or "not found" in err.lower()

    def test_remove_link_nonexistent(self, app):
        from app.services.family import remove_link
        with app.app_context():
            parent = _user(app, "parent")
            ok, err = remove_link(99999, parent)
            assert ok is False

    def test_get_parent_no_parent(self, app):
        from app.services.family import get_parent
        with app.app_context():
            student = _user(app, "student")
            result = get_parent(student)
            assert result is None

    def test_generate_link_code_invalidates_old_codes(self, app):
        from app.services.family import generate_link_code
        with app.app_context():
            student = _user(app, "student")
            code1, _ = generate_link_code(student)
            code2, _ = generate_link_code(student)
            assert code1 != code2
            # Old code should be marked as used
            old = FamilyLinkCode.query.filter_by(code=code1).first()
            assert old.used is True

    def test_link_parent_case_insensitive_code(self, app):
        from app.services.family import generate_link_code, link_parent
        with app.app_context():
            student = _user(app, "student")
            code, _ = generate_link_code(student)
            parent = _user(app, "parent")
            # Try with lowercase
            link, err = link_parent(parent, code.lower())
            assert link is not None


# ======================================================================
# finance.py — deeper tests
# ======================================================================
class TestFinanceDeep:
    def _setup_with_subscription(self, app):
        sid = _school(app)
        gid = _grade(app, sid)
        subjid = _subject(app)
        cid = _class(app, sid, gid, subjid)
        plan = SubscriptionPlan(school_id=sid, class_id=cid, name="خطة", plan="annual", price=200.0)
        _db.session.add(plan)
        _db.session.commit()
        student = _user(app)
        sub = Subscription(user_id=student, plan_id=plan.id, class_id=cid, price=200.0, status="active")
        _db.session.add(sub)
        _db.session.commit()
        return sid, student, sub.id, cid

    def test_school_revenue_summary_with_data(self, app):
        from app.services.finance import school_revenue_summary
        with app.app_context():
            sid, student, sub_id, cid = self._setup_with_subscription(app)
            # Add an approved payment
            pay = ManualPayment(subscription_id=sub_id, reference="ref-001", amount=100.0, status="approved")
            _db.session.add(pay)
            _db.session.commit()
            result = school_revenue_summary(sid)
            assert result["total_revenue"] == Decimal("100")
            assert result["active_count"] == 1
            assert result["overdue_count"] == 0

    def test_school_revenue_summary_pending(self, app):
        from app.services.finance import school_revenue_summary
        with app.app_context():
            sid, student, sub_id, cid = self._setup_with_subscription(app)
            pay = ManualPayment(subscription_id=sub_id, reference="ref-002", amount=50.0, status="pending")
            _db.session.add(pay)
            _db.session.commit()
            result = school_revenue_summary(sid)
            assert result["pending_amount"] == Decimal("50")

    def test_student_balance_with_subscription(self, app):
        from app.services.finance import student_balance
        with app.app_context():
            sid, student, sub_id, cid = self._setup_with_subscription(app)
            pay = ManualPayment(subscription_id=sub_id, reference="ref-003", amount=80.0, status="approved")
            _db.session.add(pay)
            _db.session.commit()
            result = student_balance(student, cid)
            assert result["has_subscription"] is True
            assert result["total_price"] == 200.0
            assert result["total_paid"] == 80.0
            assert result["balance"] == 120.0

    def test_accounts_receivable_with_data(self, app):
        from app.services.finance import accounts_receivable
        with app.app_context():
            sid, student, sub_id, cid = self._setup_with_subscription(app)
            result = accounts_receivable(sid)
            assert len(result) == 1
            assert result[0]["student_id"] == student
            assert result[0]["balance"] == 200.0
            assert result[0]["total_paid"] == 0.0

    def test_accounts_receivable_excludes_expired(self, app):
        from app.services.finance import accounts_receivable
        with app.app_context():
            sid = _school(app)
            gid = _grade(app, sid)
            subjid = _subject(app)
            cid = _class(app, sid, gid, subjid)
            plan = SubscriptionPlan(school_id=sid, class_id=cid, name="خطة منتهية", plan="annual", price=100.0)
            _db.session.add(plan)
            _db.session.commit()
            student = _user(app)
            sub = Subscription(user_id=student, plan_id=plan.id, class_id=cid, price=100.0, status="expired")
            _db.session.add(sub)
            _db.session.commit()
            result = accounts_receivable(sid)
            assert len(result) == 0


# ======================================================================
# calendar.py — deeper tests
# ======================================================================
class TestCalendarDeep:
    def test_create_event_empty_title(self, app):
        from app.services.calendar import create_event
        with app.app_context():
            sid = _school(app)
            ev, err = create_event(sid, "", "term_start", date(2025, 9, 1))
            assert ev is None
            assert "العنوان مطلوب" in err

    def test_create_event_with_end_date(self, app):
        from app.services.calendar import create_event, list_events
        with app.app_context():
            sid = _school(app)
            ev, err = create_event(sid, "فترة الامتحانات", "exam_period", date(2025, 6, 1), date(2025, 6, 15))
            assert ev is not None
            events = list_events(sid)
            assert len(events) == 1

    def test_list_events_with_type_filter(self, app):
        from app.services.calendar import create_event, list_events
        with app.app_context():
            sid = _school(app)
            create_event(sid, "بداية", "term_start", date(2025, 9, 1))
            create_event(sid, "إجازة", "holiday", date(2025, 12, 25))
            start_events = list_events(sid, event_type="term_start")
            assert len(start_events) == 1

    def test_list_events_empty(self, app):
        from app.services.calendar import list_events
        with app.app_context():
            sid = _school(app)
            events = list_events(sid)
            assert len(events) == 0

    def test_delete_event_nonexistent(self, app):
        from app.services.calendar import delete_event
        with app.app_context():
            ok, err = delete_event(99999)
            assert ok is False
            assert "غير موجود" in err

    def test_current_term_none(self, app):
        from app.services.calendar import current_term
        with app.app_context():
            sid = _school(app)
            term = current_term(sid)
            assert term is None

    def test_all_event_types(self, app):
        from app.services.calendar import create_event, list_events
        with app.app_context():
            sid = _school(app)
            for etype in ("term_start", "term_end", "exam_period", "enrollment", "holiday"):
                ev, err = create_event(sid, f"حدث {etype}", etype, date(2025, 9, 1))
                assert ev is not None
            events = list_events(sid)
            assert len(events) == 5


# ======================================================================
# impersonation.py — deeper tests
# ======================================================================
class TestImpersonationDeep:
    def test_is_impersonating_false(self, app):
        from app.services.impersonation import is_impersonating
        with app.test_request_context():
            assert is_impersonating() is False

    def test_impersonator_user_none(self, app):
        from app.services.impersonation import impersonator_user
        with app.test_request_context():
            assert impersonator_user() is None

    def test_clear_impersonation(self, app):
        from app.services.impersonation import clear_impersonation, SESSION_KEY
        with app.test_request_context():
            from flask import session
            session[SESSION_KEY] = "1"
            clear_impersonation()
            assert SESSION_KEY not in session

    def test_start_impersonation_not_admin(self, app):
        from app.services.impersonation import start_impersonation
        with app.app_context():
            student = _user(app, "student")
            target = _user(app, "student")
            u = User.query.get(student)
            with app.test_request_context():
                from flask_login import login_user
                login_user(u)
                result = start_impersonation(User.query.get(target))
                assert result is not None
                assert "غير مصرح" in result

    def test_start_impersonation_self(self, app):
        from app.services.impersonation import start_impersonation
        with app.app_context():
            admin_id = _user(app, "super_admin")
            admin = User.query.get(admin_id)
            with app.test_request_context():
                from flask_login import login_user
                login_user(admin)
                result = start_impersonation(admin)
                assert result is not None
                assert "حسابك" in result or "yourself" in result.lower()

    def test_start_impersonation_target_admin(self, app):
        from app.services.impersonation import start_impersonation
        with app.app_context():
            admin1_id = _user(app, "super_admin")
            admin2_id = _user(app, "super_admin")
            admin1 = User.query.get(admin1_id)
            target = User.query.get(admin2_id)
            with app.test_request_context():
                from flask_login import login_user
                login_user(admin1)
                result = start_impersonation(target)
                assert result is not None
                assert "مشرف كلي" in result or "super admin" in result.lower()

    def test_start_impersonation_inactive_target(self, app):
        from app.services.impersonation import start_impersonation
        with app.app_context():
            admin_id = _user(app, "super_admin")
            target_id = _user(app, "student")
            target = User.query.get(target_id)
            target.is_active = False
            _db.session.commit()
            admin = User.query.get(admin_id)
            with app.test_request_context():
                from flask_login import login_user
                login_user(admin)
                result = start_impersonation(target)
                assert result is not None
                assert "معطّل" in result or "inactive" in result.lower()

    def test_stop_impersonation_no_session(self, app):
        from app.services.impersonation import stop_impersonation
        with app.test_request_context():
            result = stop_impersonation()
            assert result is not None
            assert "لا توجد" in result


# ======================================================================
# invoice.py — deeper tests
# ======================================================================
class TestInvoiceDeep:
    def test_generate_invoice_html(self, app):
        from app.services.invoice import generate_invoice_html
        with app.app_context():
            result = generate_invoice_html(999999)
            assert result is None

    def test_generate_invoice_number_has_year(self, app):
        from app.services.invoice import generate_invoice_number
        from app.models.billing import Subscription
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
            num = generate_invoice_number(sub)
            assert str(datetime.now().year) in num
            assert "INV-" in num

    def test_render_invoice_pdf_no_xhtml2pdf(self, app):
        from app.services.invoice import render_invoice_pdf
        with app.app_context():
            result = render_invoice_pdf(999999)
            assert result is None


# ======================================================================
# access.py — deeper tests
# ======================================================================
class TestAccessDeep:
    def test_can_view_class_super_admin(self, app):
        from app.services.access import can_view_class
        with app.app_context():
            sid = _school(app)
            gid = _grade(app, sid)
            subjid = _subject(app)
            cid = _class(app, sid, gid, subjid)
            admin_id = _user(app, "super_admin")
            admin = User.query.get(admin_id)
            cls = ClassRoom.query.get(cid)
            assert can_view_class(cls, admin) is True

    def test_can_teach_class_super_admin(self, app):
        from app.services.access import can_teach_class
        with app.app_context():
            sid = _school(app)
            gid = _grade(app, sid)
            subjid = _subject(app)
            tid = _user(app, "teacher")
            cid = _class(app, sid, gid, subjid, tid)
            admin_id = _user(app, "super_admin")
            admin = User.query.get(admin_id)
            cls = ClassRoom.query.get(cid)
            assert can_teach_class(cls, admin) is True

    def test_can_teach_class_teacher_owner(self, app):
        from app.services.access import can_teach_class
        with app.app_context():
            sid = _school(app)
            gid = _grade(app, sid)
            subjid = _subject(app)
            tid = _user(app, "teacher")
            cid = _class(app, sid, gid, subjid, tid)
            teacher = User.query.get(tid)
            cls = ClassRoom.query.get(cid)
            # Without setting current_school_id, teacher might not match
            # But teacher_id should match
            assert can_teach_class(cls, teacher) is True

    def test_can_teach_class_other_teacher(self, app):
        from app.services.access import can_teach_class
        with app.app_context():
            sid = _school(app)
            gid = _grade(app, sid)
            subjid = _subject(app)
            tid = _user(app, "teacher")
            cid = _class(app, sid, gid, subjid, tid)
            other_tid = _user(app, "teacher")
            other_teacher = User.query.get(other_tid)
            cls = ClassRoom.query.get(cid)
            assert can_teach_class(cls, other_teacher) is False


# ======================================================================
# base.py — deeper tests
# ======================================================================
class TestBaseServiceDeep:
    def test_pagination_meta(self):
        from app.services.base import PaginationMeta
        meta = PaginationMeta(page=2, per_page=10, total=25)
        assert meta.pages == 3
        d = meta.to_dict()
        assert d["page"] == 2
        assert d["total"] == 25

    def test_pagination_meta_zero_per_page(self):
        from app.services.base import PaginationMeta
        meta = PaginationMeta(page=1, per_page=0, total=10)
        assert meta.pages == 0

    def test_paginated_result_to_dict(self):
        from app.services.base import PaginatedResult, PaginationMeta
        meta = PaginationMeta(page=1, per_page=10, total=2)
        result = PaginatedResult(items=[{"id": 1}, {"id": 2}], meta=meta)
        d = result.to_dict()
        assert len(d["items"]) == 2
        assert d["meta"]["total"] == 2

    def test_paginated_result_with_serializer(self):
        from app.services.base import PaginatedResult, PaginationMeta
        meta = PaginationMeta(page=1, per_page=10, total=1)
        result = PaginatedResult(items=["hello"], meta=meta)
        d = result.to_dict(serializer=lambda x: {"text": x})
        assert d["items"][0]["text"] == "hello"

    def test_base_service_create_and_get(self, app):
        from app.services.base import BaseService
        with app.app_context():
            # Use School as a concrete model
            class SchoolService(BaseService):
                model = School
            s = SchoolService.create(name_ar="مدرسة اختبار", domain="test.example.org")
            assert s.id is not None
            found = SchoolService.get(s.id)
            assert found is not None

    def test_base_service_get_or_404(self, app):
        from app.services.base import BaseService
        with app.app_context():
            class SchoolService(BaseService):
                model = School
            with pytest.raises(Exception):  # abort(404)
                SchoolService.get_or_404(99999)

    def test_base_service_update(self, app):
        from app.services.base import BaseService
        with app.app_context():
            class SchoolService(BaseService):
                model = School
            s = SchoolService.create(name_ar="أصلية", domain="u.test.org")
            updated = SchoolService.update(s.id, name_ar="محدثة")
            assert updated.name_ar == "محدثة"

    def test_base_service_update_nonexistent(self, app):
        from app.services.base import BaseService
        with app.app_context():
            class SchoolService(BaseService):
                model = School
            result = SchoolService.update(99999, name_ar="test")
            assert result is None

    def test_base_service_delete(self, app):
        from app.services.base import BaseService
        with app.app_context():
            class SchoolService(BaseService):
                model = School
            s = SchoolService.create(name_ar="حذف", domain="d.test.org")
            ok = SchoolService.delete(s.id)
            assert ok is True

    def test_base_service_delete_nonexistent(self, app):
        from app.services.base import BaseService
        with app.app_context():
            class SchoolService(BaseService):
                model = School
            ok = SchoolService.delete(99999)
            assert ok is False

    def test_base_service_count(self, app):
        from app.services.base import BaseService
        with app.app_context():
            class SchoolService(BaseService):
                model = School
            SchoolService.create(name_ar="عد1", domain="c1.test.org")
            SchoolService.create(name_ar="عد2", domain="c2.test.org")
            assert SchoolService.count() == 2

    def test_base_service_list_with_filters(self, app):
        from app.services.base import BaseService
        with app.app_context():
            class SchoolService(BaseService):
                model = School
            SchoolService.create(name_ar="فلتر1", domain="f1.test.org")
            SchoolService.create(name_ar="فلتر2", domain="f2.test.org")
            result = SchoolService.list(filters={"name_ar": "فلتر1"})
            assert result.meta.total == 1

    def test_base_service_list_with_order(self, app):
        from app.services.base import BaseService
        with app.app_context():
            class SchoolService(BaseService):
                model = School
            SchoolService.create(name_ar="ترتيب1", domain="o1.test.org")
            SchoolService.create(name_ar="ترتيب2", domain="o2.test.org")
            result = SchoolService.list(order_by="name_ar", desc_order=True)
            assert len(result.items) == 2

    def test_base_service_list_pagination(self, app):
        from app.services.base import BaseService
        with app.app_context():
            class SchoolService(BaseService):
                model = School
            for i in range(5):
                SchoolService.create(name_ar=f"صفحة{i}", domain=f"p{i}.test.org")
            result = SchoolService.list(page=2, per_page=2)
            assert len(result.items) == 2
            assert result.meta.total == 5
            assert result.meta.pages == 3


# ======================================================================
# payments.py — unit tests for gateway classes
# ======================================================================
class TestPaymentsDeep:
    def test_payment_intent_dataclass(self):
        from app.services.payments import PaymentIntent, PaymentGateway, PaymentStatus
        pi = PaymentIntent(
            id="test_123",
            gateway=PaymentGateway.MANUAL,
            amount=Decimal("100.50"),
            currency="ILS",
            status=PaymentStatus.PENDING,
            user_id=1,
        )
        assert pi.amount == Decimal("100.50")
        assert pi.status == PaymentStatus.PENDING

    def test_manual_gateway_create_intent(self):
        from app.services.payments import ManualPaymentGateway, PaymentStatus
        gw = ManualPaymentGateway({"enabled": True})
        pi = gw.create_payment_intent(Decimal("50"), "ILS", user_id=1)
        assert pi.gateway.value == "manual"
        assert pi.status == PaymentStatus.PENDING

    def test_manual_gateway_verify_not_approved(self):
        from app.services.payments import ManualPaymentGateway, PaymentIntent, PaymentGateway, PaymentStatus
        gw = ManualPaymentGateway({"enabled": True})
        pi = PaymentIntent(id="m1", gateway=PaymentGateway.MANUAL, amount=Decimal("50"), currency="ILS", status=PaymentStatus.PENDING, user_id=1)
        assert gw.verify_payment(pi, {}) is False

    def test_manual_gateway_verify_admin_approved(self):
        from app.services.payments import ManualPaymentGateway, PaymentIntent, PaymentGateway, PaymentStatus
        gw = ManualPaymentGateway({"enabled": True})
        pi = PaymentIntent(id="m2", gateway=PaymentGateway.MANUAL, amount=Decimal("50"), currency="ILS", status=PaymentStatus.PENDING, user_id=1)
        assert gw.verify_payment(pi, {"admin_approved": True}) is True

    def test_whatsapp_gateway_create_intent(self):
        from app.services.payments import WhatsAppPaymentGateway, PaymentStatus
        gw = WhatsAppPaymentGateway({"whatsapp_number": "12345"})
        pi = gw.create_payment_intent(Decimal("100"), "ILS", user_id=1)
        assert pi.gateway.value == "whatsapp"
        assert pi.status == PaymentStatus.PENDING

    def test_whatsapp_gateway_verify_no_auto(self):
        from app.services.payments import WhatsAppPaymentGateway, PaymentIntent, PaymentGateway, PaymentStatus
        gw = WhatsAppPaymentGateway({"whatsapp_number": "12345"})
        pi = PaymentIntent(id="w1", gateway=PaymentGateway.WHATSAPP, amount=Decimal("100"), currency="ILS", status=PaymentStatus.PENDING, user_id=1)
        assert gw.verify_payment(pi, {}) is False

    def test_whatsapp_gateway_verify_admin_approved(self):
        from app.services.payments import WhatsAppPaymentGateway, PaymentIntent, PaymentGateway, PaymentStatus
        gw = WhatsAppPaymentGateway({"whatsapp_number": "12345"})
        pi = PaymentIntent(id="w2", gateway=PaymentGateway.WHATSAPP, amount=Decimal("100"), currency="ILS", status=PaymentStatus.PENDING, user_id=1)
        assert gw.verify_payment(pi, {"admin_approved": True}) is True

    def test_manual_gateway_refund(self):
        from app.services.payments import ManualPaymentGateway, PaymentIntent, PaymentGateway, PaymentStatus
        gw = ManualPaymentGateway({"enabled": True})
        pi = PaymentIntent(id="m3", gateway=PaymentGateway.MANUAL, amount=Decimal("50"), currency="ILS", status=PaymentStatus.PENDING, user_id=1)
        assert gw.refund(pi) is False

    def test_payment_service_singleton(self):
        from app.services.payments import get_payment_service
        svc1 = get_payment_service()
        svc2 = get_payment_service()
        assert svc1 is svc2

    def test_payment_service_create_payment_manual(self):
        from app.services.payments import get_payment_service, PaymentGateway
        svc = get_payment_service()
        pi = svc.create_payment(PaymentGateway.MANUAL, Decimal("100"), "ILS", user_id=1)
        assert pi is not None

    def test_payment_service_process_webhook_unknown(self):
        from app.services.payments import get_payment_service, PaymentGateway
        svc = get_payment_service()
        result = svc.process_webhook(PaymentGateway.STRIPE, {}, {})
        assert result["success"] is False

    def test_cleanup_expired_intents(self):
        from app.services.payments import get_payment_service
        svc = get_payment_service()
        count = svc.cleanup_expired_intents()
        assert count == 0
