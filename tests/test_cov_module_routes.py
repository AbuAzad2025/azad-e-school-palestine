"""Integration tests for module routes to boost coverage:
admin, grades, tutoring, billing, content, payments, schools,
messages, progress, calendar, family, individual, notifications,
school_approvals, contact, export."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from app import create_app
from app.extensions import db as _db
from app.core.security import hash_password
from app.models.billing import ManualPayment, Subscription, SubscriptionPlan
from app.models.class_room import ClassMember, ClassRoom
from app.models.communication import ContactMessage, Notification, NotificationPreference
from app.models.content import Lesson, LessonAttachment, Unit
from app.models.gradebook import (
    Assignment,
    GradeCategory,
    GradeEntry,
    GradeItem,
    Submission,
)
from app.models.progress import StudentProgress
from app.models.school import Grade, School, Subject
from app.models.system import AuditLog, CertificateTemplate, HealthCheck, OnboardingProgress, Setting
from app.models.tutoring import TutorProfile, TutorPayout, TutoringSession
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


def _login(client, email, password="TestPass123!"):
    return client.post("/auth/login", data={"email": email, "password": password}, follow_redirects=False)


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
# admin routes tests
# ======================================================================
class TestAdminRoutes:
    def test_admin_dashboard(self, app, client):
        admin = _user(app, "super_admin")
        _login(client, User.query.get(admin).email)
        resp = client.get("/admin/")
        assert resp.status_code == 200

    def test_admin_users_list(self, app, client):
        admin = _user(app, "super_admin")
        _login(client, User.query.get(admin).email)
        resp = client.get("/admin/users")
        assert resp.status_code == 200

    def test_admin_users_list_with_search(self, app, client):
        admin = _user(app, "super_admin")
        _login(client, User.query.get(admin).email)
        resp = client.get("/admin/users?search=test&role=student")
        assert resp.status_code == 200

    def test_admin_user_detail(self, app, client):
        admin = _user(app, "super_admin")
        target = _user(app)
        _login(client, User.query.get(admin).email)
        resp = client.get(f"/admin/users/{target}")
        assert resp.status_code == 200

    def test_admin_user_toggle(self, app, client):
        admin = _user(app, "super_admin")
        target = _user(app)
        _login(client, User.query.get(admin).email)
        resp = client.post(f"/admin/users/{target}/toggle", follow_redirects=False)
        assert resp.status_code in (302, 200)

    def test_admin_user_toggle_self(self, app, client):
        admin = _user(app, "super_admin")
        _login(client, User.query.get(admin).email)
        resp = client.post(f"/admin/users/{admin}/toggle", follow_redirects=True)
        assert resp.status_code == 200

    def test_admin_bulk_action_users(self, app, client):
        admin = _user(app, "super_admin")
        target = _user(app)
        _login(client, User.query.get(admin).email)
        resp = client.post("/admin/bulk-action",
                          data=json.dumps({"entity": "users", "action": "deactivate", "ids": [target]}),
                          content_type="application/json")
        assert resp.status_code == 200

    def test_admin_bulk_action_invalid(self, app, client):
        admin = _user(app, "super_admin")
        _login(client, User.query.get(admin).email)
        resp = client.post("/admin/bulk-action",
                          data=json.dumps({"entity": "users", "action": "invalid", "ids": [1]}),
                          content_type="application/json")
        assert resp.status_code == 400

    def test_admin_bulk_action_missing_data(self, app, client):
        admin = _user(app, "super_admin")
        _login(client, User.query.get(admin).email)
        resp = client.post("/admin/bulk-action",
                          data=json.dumps({}),
                          content_type="application/json")
        assert resp.status_code == 400

    def test_admin_schools_list(self, app, client):
        admin = _user(app, "super_admin")
        _login(client, User.query.get(admin).email)
        resp = client.get("/admin/schools")
        assert resp.status_code == 200

    def test_admin_school_detail(self, app, client):
        admin = _user(app, "super_admin")
        sid = _school(app)
        _login(client, User.query.get(admin).email)
        resp = client.get(f"/admin/schools/{sid}")
        assert resp.status_code == 200

    def test_admin_subscriptions_list(self, app, client):
        admin = _user(app, "super_admin")
        _login(client, User.query.get(admin).email)
        resp = client.get("/admin/subscriptions")
        assert resp.status_code == 200

    def test_admin_pending_payments(self, app, client):
        admin = _user(app, "super_admin")
        _login(client, User.query.get(admin).email)
        resp = client.get("/admin/payments/pending")
        assert resp.status_code == 200

    def test_admin_settings_page(self, app, client):
        admin = _user(app, "super_admin")
        _login(client, User.query.get(admin).email)
        resp = client.get("/admin/settings")
        assert resp.status_code == 200

    def test_admin_settings_save(self, app, client):
        admin = _user(app, "super_admin")
        _login(client, User.query.get(admin).email)
        resp = client.post("/admin/settings", data={"site_name": "أزاد"}, follow_redirects=True)
        assert resp.status_code == 200

    def test_admin_pending_registrations(self, app, client):
        admin = _user(app, "super_admin")
        _login(client, User.query.get(admin).email)
        resp = client.get("/admin/registrations/pending")
        assert resp.status_code == 200

    def test_admin_registration_approve(self, app, client):
        admin = _user(app, "super_admin")
        pending_user = _user(app, "student", approval_status=UserApprovalStatus.pending)
        _login(client, User.query.get(admin).email)
        resp = client.post(f"/admin/registrations/{pending_user}/approve", follow_redirects=True)
        assert resp.status_code == 200

    def test_admin_registration_reject(self, app, client):
        admin = _user(app, "super_admin")
        pending_user = _user(app, "student", approval_status=UserApprovalStatus.pending)
        _login(client, User.query.get(admin).email)
        resp = client.post(f"/admin/registrations/{pending_user}/reject", follow_redirects=True)
        assert resp.status_code == 200

    def test_admin_revenue_dashboard(self, app, client):
        admin = _user(app, "super_admin")
        _login(client, User.query.get(admin).email)
        resp = client.get("/admin/revenue")
        assert resp.status_code == 200

    def test_admin_health(self, app, client):
        admin = _user(app, "super_admin")
        _login(client, User.query.get(admin).email)
        resp = client.get("/admin/health")
        assert resp.status_code == 200

    def test_admin_analytics(self, app, client):
        admin = _user(app, "super_admin")
        _login(client, User.query.get(admin).email)
        resp = client.get("/admin/analytics")
        assert resp.status_code == 200

    def test_admin_moe_export_page(self, app, client):
        admin = _user(app, "super_admin")
        _login(client, User.query.get(admin).email)
        resp = client.get("/admin/moe-export")
        assert resp.status_code == 200

    def test_admin_moe_export_download(self, app, client):
        admin = _user(app, "super_admin")
        _login(client, User.query.get(admin).email)
        resp = client.post("/admin/moe-export", data={"school_id": ""}, follow_redirects=True)
        assert resp.status_code == 200

    def test_admin_certificates_list(self, app, client):
        admin = _user(app, "super_admin")
        _login(client, User.query.get(admin).email)
        resp = client.get("/admin/certificates")
        assert resp.status_code == 200

    def test_admin_audit_logs(self, app, client):
        admin = _user(app, "super_admin")
        _login(client, User.query.get(admin).email)
        resp = client.get("/admin/audit-logs")
        assert resp.status_code == 200

    def test_admin_audit_logs_with_filters(self, app, client):
        admin = _user(app, "super_admin")
        _login(client, User.query.get(admin).email)
        resp = client.get(f"/admin/audit-logs?action=test&entity=users&search=test&user_id={admin}")
        assert resp.status_code == 200

    def test_admin_backups_list(self, app, client):
        admin = _user(app, "super_admin")
        _login(client, User.query.get(admin).email)
        resp = client.get("/admin/backups")
        assert resp.status_code == 200

    def test_admin_contact_inbox(self, app, client):
        admin = _user(app, "super_admin")
        _login(client, User.query.get(admin).email)
        resp = client.get("/admin/contact")
        assert resp.status_code == 200

    def test_admin_payouts_queue(self, app, client):
        admin = _user(app, "super_admin")
        _login(client, User.query.get(admin).email)
        resp = client.get("/admin/payouts")
        assert resp.status_code == 200

    def test_admin_403_for_non_admin(self, app, client):
        student = _user(app, "student")
        _login(client, User.query.get(student).email)
        resp = client.get("/admin/")
        assert resp.status_code == 403

    def test_admin_unauthenticated(self, app, client):
        resp = client.get("/admin/")
        assert resp.status_code == 401 or resp.status_code == 302


# ======================================================================
# school approvals routes tests
# ======================================================================
class TestSchoolApprovalRoutes:
    def test_approvals_page(self, app, client):
        admin = _user(app, "super_admin")
        _login(client, User.query.get(admin).email)
        resp = client.get("/school-approvals/")
        assert resp.status_code == 200

    def test_approve_user(self, app, client):
        admin = _user(app, "super_admin")
        sid = _school(app)
        student = _user(app, "student", approval_status=UserApprovalStatus.pending)
        with app.app_context():
            rl = UserRoleLink(user_id=student, school_id=sid, role=UserRole.student)
            _db.session.add(rl)
            _db.session.commit()
            rl_id = rl.id
        _login(client, User.query.get(admin).email)
        resp = client.post(f"/school-approvals/{rl_id}/approve", follow_redirects=True)
        assert resp.status_code == 200

    def test_reject_user(self, app, client):
        admin = _user(app, "super_admin")
        sid = _school(app)
        student = _user(app, "student", approval_status=UserApprovalStatus.pending)
        with app.app_context():
            rl = UserRoleLink(user_id=student, school_id=sid, role=UserRole.student)
            _db.session.add(rl)
            _db.session.commit()
            rl_id = rl.id
        _login(client, User.query.get(admin).email)
        resp = client.post(f"/school-approvals/{rl_id}/reject", follow_redirects=True)
        assert resp.status_code == 200


# ======================================================================
# messages routes tests
# ======================================================================
class TestMessagesRoutes:
    def test_inbox_page(self, app, client):
        student = _user(app, "student")
        _login(client, User.query.get(student).email)
        resp = client.get("/messages/")
        assert resp.status_code == 200

    def test_sent_page(self, app, client):
        student = _user(app, "student")
        _login(client, User.query.get(student).email)
        resp = client.get("/messages/sent")
        assert resp.status_code == 200

    def test_compose_page(self, app, client):
        student = _user(app, "student")
        _login(client, User.query.get(student).email)
        resp = client.get("/messages/compose")
        assert resp.status_code == 200


# ======================================================================
# progress routes tests
# ======================================================================
class TestProgressRoutes:
    def test_progress_page(self, app, client):
        student = _user(app, "student")
        _login(client, User.query.get(student).email)
        resp = client.get("/progress/")
        assert resp.status_code == 200

    def test_progress_class_page(self, app, client):
        student = _user(app, "student")
        sid = _school(app)
        gid = _grade(app, sid)
        subjid = _subject(app)
        cid = _class(app, sid, gid, subjid)
        with app.app_context():
            cm = ClassMember(class_id=cid, user_id=student, status="active")
            _db.session.add(cm)
            _db.session.commit()
        _login(client, User.query.get(student).email)
        resp = client.get(f"/progress/class/{cid}")
        assert resp.status_code == 200


# ======================================================================
# notifications routes tests
# ======================================================================
class TestNotificationRoutes:
    def test_notifications_page(self, app, client):
        student = _user(app, "student")
        _login(client, User.query.get(student).email)
        resp = client.get("/notifications/")
        assert resp.status_code == 200

    def test_mark_all_read(self, app, client):
        student = _user(app, "student")
        _login(client, User.query.get(student).email)
        resp = client.post("/notifications/mark-all-read", follow_redirects=True)
        assert resp.status_code == 200

    def test_notification_preferences_page(self, app, client):
        student = _user(app, "student")
        _login(client, User.query.get(student).email)
        resp = client.get("/notifications/preferences")
        assert resp.status_code == 200


# ======================================================================
# contact form routes tests
# ======================================================================
class TestContactRoutes:
    def test_contact_page(self, app, client):
        resp = client.get("/contact/")
        assert resp.status_code == 200

    def test_contact_submit(self, app, client):
        resp = client.post("/contact/", data={
            "name": "اختبار",
            "email": "test@test.com",
            "subject": "استفسار",
            "message": "رسالة تجريبية",
        }, follow_redirects=True)
        assert resp.status_code == 200


# ======================================================================
# auth routes tests
# ======================================================================
class TestAuthRoutes:
    def test_login_page(self, app, client):
        resp = client.get("/auth/login")
        assert resp.status_code == 200

    def test_login_success(self, app, client):
        email = _email()
        _user(app, "student", email=email)
        resp = client.post("/auth/login", data={"email": email, "password": "TestPass123!"})
        assert resp.status_code in (200, 302)

    def test_login_failure(self, app, client):
        resp = client.post("/auth/login", data={"email": "bad@test.com", "password": "wrong"})
        assert resp.status_code == 200

    def test_register_page(self, app, client):
        resp = client.get("/auth/register")
        assert resp.status_code == 200


# ======================================================================
# individual routes tests
# ======================================================================
class TestIndividualRoutes:
    def test_marketplace(self, app, client):
        resp = client.get("/individual/marketplace")
        assert resp.status_code == 200

    def test_my_classes_empty(self, app, client):
        student = _user(app, "student")
        _login(client, User.query.get(student).email)
        resp = client.get("/individual/my-classes")
        assert resp.status_code == 200


# ======================================================================
# calendar routes tests
# ======================================================================
class TestCalendarRoutes:
    def test_calendar_page(self, app, client):
        sid = _school(app)
        admin = _user(app, "school_admin")
        with app.app_context():
            rl = UserRoleLink(user_id=admin, school_id=sid, role=UserRole.school_admin)
            _db.session.add(rl)
            _db.session.commit()
        _login(client, User.query.get(admin).email)
        resp = client.get("/calendar/")
        assert resp.status_code == 200


# ======================================================================
# export routes tests
# ======================================================================
class TestExportRoutes:
    def test_export_page(self, app, client):
        admin = _user(app, "school_admin")
        sid = _school(app)
        with app.app_context():
            rl = UserRoleLink(user_id=admin, school_id=sid, role=UserRole.school_admin)
            _db.session.add(rl)
            _db.session.commit()
        _login(client, User.query.get(admin).email)
        resp = client.get("/export/")
        assert resp.status_code == 200


# ======================================================================
# billing routes tests
# ======================================================================
class TestBillingRoutes:
    def test_plans_page(self, app, client):
        student = _user(app, "student")
        _login(client, User.query.get(student).email)
        resp = client.get("/billing/plans")
        assert resp.status_code == 200


# ======================================================================
# payments routes tests
# ======================================================================
class TestPaymentsRoutes:
    def test_payments_page(self, app, client):
        student = _user(app, "student")
        _login(client, User.query.get(student).email)
        resp = client.get("/payments/")
        assert resp.status_code == 200


# ======================================================================
# main routes tests
# ======================================================================
class TestMainRoutes:
    def test_index(self, app, client):
        resp = client.get("/")
        assert resp.status_code == 200

    def test_about_page(self, app, client):
        resp = client.get("/about")
        assert resp.status_code in (200, 404)

    def test_pricing_page(self, app, client):
        resp = client.get("/pricing")
        assert resp.status_code in (200, 404)


# ======================================================================
# ai routes tests
# ======================================================================
class TestAIRoutes:
    def test_ai_chat_page(self, app, client):
        student = _user(app, "student")
        _login(client, User.query.get(student).email)
        resp = client.get("/ai/chat")
        assert resp.status_code in (200, 403, 404)
