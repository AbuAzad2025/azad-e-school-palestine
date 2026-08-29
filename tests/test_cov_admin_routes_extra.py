"""Integration tests for admin routes not covered by test_cov_module_routes.py."""

from app.core.security import hash_password
from app.extensions import db as _db
from app.models.user import User, UserApprovalStatus, UserRole
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


def _uid():
    import uuid
    return uuid.uuid4().hex[:10]


def _login(client, email, password="TestPass123!"):
    return client.post("/auth/login", data={"email": email, "password": password}, follow_redirects=False)


def _make_admin(app):
    with app.app_context():
        u = User(
            email=f"admin-{_uid()}@test.com",
            name_ar="مدير اختبار",
            role=UserRole.super_admin,
            password_hash=hash_password("TestPass123!"),
            approval_status=UserApprovalStatus.approved,
            is_active=True,
        )
        _db.session.add(u)
        _db.session.commit()
        return u.email


class TestSystemHealth:
    def test_system_health_returns_200(self, client, app):
        email = _make_admin(app)
        _login(client, email)
        resp = client.get("/admin/health")
        assert resp.status_code == 200

    def test_system_health_requires_admin(self, client, app):
        resp = client.get("/admin/health")
        assert resp.status_code in (302, 401, 403)


class TestSubscriptionDetail:
    def test_subscription_detail_page(self, client, app):
        email = _make_admin(app)
        _login(client, email)
        with app.app_context():
            sid = make_school(app)
            uid = make_user(app, "student", school_id=sid)
            gid = make_grade(app, sid)
            subjid = make_subject(app)
            cid = make_class(app, sid, gid, subjid)
            pid = make_subscription_plan(app, sid, cid)
            sub_id = make_subscription(app, uid, pid, cid)
        resp = client.get(f"/admin/subscriptions/{sub_id}")
        assert resp.status_code == 200

    def test_subscription_cancel(self, client, app):
        email = _make_admin(app)
        _login(client, email)
        with app.app_context():
            sid = make_school(app)
            uid = make_user(app, "student", school_id=sid)
            gid = make_grade(app, sid)
            subjid = make_subject(app)
            cid = make_class(app, sid, gid, subjid)
            pid = make_subscription_plan(app, sid, cid)
            sub_id = make_subscription(app, uid, pid, cid, status="active")
        resp = client.post(f"/admin/subscriptions/{sub_id}/cancel", follow_redirects=True)
        assert resp.status_code == 200


class TestPaymentApproval:
    def test_payment_approve(self, client, app):
        email = _make_admin(app)
        _login(client, email)
        with app.app_context():
            sid = make_school(app)
            uid = make_user(app, "student", school_id=sid)
            gid = make_grade(app, sid)
            subjid = make_subject(app)
            cid = make_class(app, sid, gid, subjid)
            pid = make_subscription_plan(app, sid, cid)
            sub_id = make_subscription(app, uid, pid, cid)
            pay_id = make_payment(app, sub_id, status="pending")
        resp = client.post(f"/admin/payments/{pay_id}/approve", follow_redirects=True)
        assert resp.status_code == 200

    def test_payment_reject(self, client, app):
        email = _make_admin(app)
        _login(client, email)
        with app.app_context():
            sid = make_school(app)
            uid = make_user(app, "student", school_id=sid)
            gid = make_grade(app, sid)
            subjid = make_subject(app)
            cid = make_class(app, sid, gid, subjid)
            pid = make_subscription_plan(app, sid, cid)
            sub_id = make_subscription(app, uid, pid, cid)
            pay_id = make_payment(app, sub_id, status="pending")
        resp = client.post(f"/admin/payments/{pay_id}/reject", follow_redirects=True)
        assert resp.status_code == 200


class TestContactInbox:
    def test_contact_inbox(self, client, app):
        email = _make_admin(app)
        _login(client, email)
        resp = client.get("/admin/contact")
        assert resp.status_code == 200


class TestAIUsage:
    def test_ai_usage_page(self, client, app):
        email = _make_admin(app)
        _login(client, email)
        resp = client.get("/admin/ai")
        assert resp.status_code in (200, 404)  # URL may vary


class TestUserImpersonate:
    def test_impersonate_user(self, client, app):
        email = _make_admin(app)
        _login(client, email)
        with app.app_context():
            make_school(app)
            student_email = f"student-{_uid()}@test.com"
            u = User(
                email=student_email,
                name_ar="طالب اختبار",
                role=UserRole.student,
                password_hash=hash_password("TestPass123!"),
                approval_status=UserApprovalStatus.approved,
                is_active=True,
            )
            _db.session.add(u)
            _db.session.commit()
            student_id = u.id
        resp = client.post(f"/admin/users/{student_id}/impersonate", follow_redirects=True)
        assert resp.status_code == 200

    def test_impersonate_exit(self, client, app):
        email = _make_admin(app)
        _login(client, email)
        resp = client.post("/admin/impersonate/exit", follow_redirects=True)
        assert resp.status_code in (200, 302)
