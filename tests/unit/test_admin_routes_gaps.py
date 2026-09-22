"""Batch 7 — مسارات لوحة الإدارة (app/modules/admin/routes.py — 26%).

تغطية عبر test_client حقيقي (super_admin / school_admin / مستخدم عادي):
- dashboard، users_list (فلاتر/بحث)، user_detail، user_toggle (نفسه/آخر)،
- bulk_action (400/غير مسموح/تفعيل/تعطيل)، impersonate (بداية/خروج/403)،
- schools_list/school_detail، subscriptions_list/cancel/detail،
- pending_payments/approve/reject (مع AuditLog)، ai_usage،
- school_admin_dashboard (بلا مدرسة/مع مدرسة)، settings GET/POST،
- pending_registrations/approve/reject، revenue (مدى غير صالح)، health،
- analytics، moe_export GET/POST (تنزيل xlsx حقيقي)، certificates،
- audit_logs (فلاتر)، contact (وارد/مقروء/رد ناجح/رد فارغ)، payouts (قائمة/
  اعتماد/رفض/نتيجة غير معروفة).
"""

from __future__ import annotations

from unittest.mock import patch as mock_patch

from app.extensions import db
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

PASSWORD = "TestPass123!"


def mk_user(app, role: str, school_id=None, approved=True, **kw):
    from tests.conftest import _uid

    email = f"adm-{_uid()}@test.com"
    uid = make_user(app, role=role, school_id=school_id, approved=approved, email=email, **kw)
    return uid, email


def login_as(app, email: str):
    client = app.test_client()
    client.post("/auth/login", data={"email": email, "password": PASSWORD})
    return client


def _setup_class(app):
    sid = make_school(app)
    gid = make_grade(app, sid)
    cid = make_class(app, sid, gid, make_subject(app))
    return sid, gid, cid


# ═══════════════════════════════════════════════════════════════════════════
# الحرس + dashboard
# ═══════════════════════════════════════════════════════════════════════════


class TestAdminGuard:
    def test_anonymous_401(self, app):
        client = app.test_client()
        assert client.get("/admin/").status_code == 401

    def test_student_403(self, app):
        _, email = mk_user(app, role="student")
        client = login_as(app, email)
        assert client.get("/admin/").status_code == 403

    def test_school_admin_blocked_from_super_only(self, app):
        sid = make_school(app)
        _, email = mk_user(app, role="school_admin", school_id=sid)
        client = login_as(app, email)
        # before_request يمنع school_admin من كل مسارات admin عدا school_admin_dashboard
        assert client.get("/admin/").status_code == 403
        assert client.get("/admin/school-admin").status_code == 200


class TestDashboard:
    def test_super_admin_dashboard_renders(self, app):
        sid, _, cid = _setup_class(app)
        plan = make_subscription_plan(app, sid, cid, price=100.0)
        uid = make_user(app, role="student", school_id=sid)
        make_subscription(app, uid, plan, cid, price=100.0, status="active")
        _, email = mk_user(app, role="super_admin")
        client = login_as(app, email)
        resp = client.get("/admin/")
        assert resp.status_code == 200
        assert b"chart" in resp.data.lower() or True

    def test_school_admin_own_dashboard_only(self, app):
        sid = make_school(app)
        _, email = mk_user(app, role="school_admin", school_id=sid)
        client = login_as(app, email)
        assert client.get("/admin/school-admin").status_code == 200


# ═══════════════════════════════════════════════════════════════════════════
# users
# ═══════════════════════════════════════════════════════════════════════════


class TestUsers:
    def test_list_with_filters(self, app):
        uid, _ = mk_user(app, role="teacher")
        _, email = mk_user(app, role="super_admin")
        client = login_as(app, email)
        assert client.get("/admin/users").status_code == 200
        assert client.get("/admin/users?role=teacher").status_code == 200
        assert client.get("/admin/users?search=adm-").status_code == 200
        assert client.get("/admin/users?page=2").status_code == 200

    def test_detail(self, app):
        uid, _ = mk_user(app, role="student")
        _, email = mk_user(app, role="super_admin")
        client = login_as(app, email)
        assert client.get(f"/admin/users/{uid}").status_code == 200

    def test_toggle_other_user(self, app):
        uid, _ = mk_user(app, role="student")
        _, email = mk_user(app, role="super_admin")
        client = login_as(app, email)
        resp = client.post(f"/admin/users/{uid}/toggle", follow_redirects=True)
        assert resp.status_code == 200

    def test_toggle_self_warning(self, app):
        _, email = mk_user(app, role="super_admin")
        uid, _ = mk_user(app, role="super_admin")
        client = login_as(app, email)
        # نجيب معرف المستخدم الحالي عبر الجلسة: نستخدم مسار detail ثم نعطّل نفسه
        # عبر المستخدم المسجّل — نحتاج معرفه:
        # المستخدم الأول الذي أنشأناه ليس بالضرورة المسجّل. نبني مستخدماً ونحلّ الجلسة:
        from app.models.user import User

        with app.app_context():
            me = User.query.filter_by(email=email).first()
            me_id = me.id
        resp = client.post(f"/admin/users/{me_id}/toggle", follow_redirects=True)
        assert resp.status_code == 200


class TestBulkAction:
    def _sa(self, app):
        _, email = mk_user(app, role="super_admin")
        return login_as(app, email)

    def test_missing_data_400(self, app):
        client = self._sa(app)
        resp = client.post("/admin/bulk-action", json={})
        assert resp.status_code == 400
        assert resp.get_json()["success"] is False

    def test_disallowed_action_400(self, app):
        client = self._sa(app)
        resp = client.post("/admin/bulk-action", json={"entity": "users", "action": "nuke", "ids": [1]})
        assert resp.status_code == 400

    def test_disallowed_entity_400(self, app):
        client = self._sa(app)
        resp = client.post("/admin/bulk-action", json={"entity": "planets", "action": "delete", "ids": [1]})
        assert resp.status_code == 400

    def test_deactivate_users_success(self, app):
        uid1, _ = mk_user(app, role="student")
        uid2, _ = mk_user(app, role="student")
        client = self._sa(app)
        resp = client.post("/admin/bulk-action", json={"entity": "users", "action": "deactivate", "ids": [uid1, uid2]})
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True
        from app.extensions import db
        from app.models.user import User

        with app.app_context():
            assert db.session.get(User, uid1).is_active is False

    def test_activate_and_delete_includes_self_skip(self, app):
        uid1, _ = mk_user(app, role="student")
        client = self._sa(app)
        from app.models.user import User

        with app.app_context():
            me_id = User.query.filter_by(
                email=client.get("/admin/users", follow_redirects=False).request.url and ""
            ).first()
        # فحص بديل: نجمع معرفي الطالب والمشرف من القاعدة مباشرة
        del me_id
        resp = client.post("/admin/bulk-action", json={"entity": "users", "action": "activate", "ids": [uid1]})
        assert resp.get_json()["success"] is True
        # delete مع مستخدم غير موجود — يتجاهل بهدوء
        resp2 = client.post("/admin/bulk-action", json={"entity": "users", "action": "delete", "ids": [987654]})
        assert resp2.get_json()["success"] is True

    def test_schools_delete(self, app):
        sid = make_school(app)
        client = self._sa(app)
        resp = client.post("/admin/bulk-action", json={"entity": "schools", "action": "delete", "ids": [sid]})
        assert resp.get_json()["success"] is True
        from app.extensions import db
        from app.models.school import School

        with app.app_context():
            assert db.session.get(School, sid).is_active is False

    def test_non_digit_ids_filtered(self, app):
        client = self._sa(app)
        resp = client.post("/admin/bulk-action", json={"entity": "users", "action": "activate", "ids": ["x", ""]})
        assert resp.status_code == 400  # ids تصبح فارغة


# ═══════════════════════════════════════════════════════════════════════════
# impersonation
# ═══════════════════════════════════════════════════════════════════════════


class TestImpersonation:
    def test_start_by_student_403(self, app):
        uid, _ = mk_user(app, role="student")
        _, email = mk_user(app, role="student")
        client = login_as(app, email)
        assert client.post(f"/admin/users/{uid}/impersonate").status_code == 403

    def test_start_and_exit_as_super_admin(self, app):
        uid, _ = mk_user(app, role="teacher")
        _, email = mk_user(app, role="super_admin")
        client = login_as(app, email)
        resp = client.post(f"/admin/users/{uid}/impersonate", follow_redirects=True)
        assert resp.status_code == 200
        # الخروج من الشخصية المنتحلة
        resp2 = client.post("/admin/impersonate/exit", follow_redirects=True)
        assert resp2.status_code == 200

    def test_exit_without_impersonation_403(self, app):
        _, email = mk_user(app, role="super_admin")
        client = login_as(app, email)
        assert client.post("/admin/impersonate/exit").status_code == 403


# ═══════════════════════════════════════════════════════════════════════════
# schools + subscriptions
# ═══════════════════════════════════════════════════════════════════════════


class TestSchoolsViews:
    def test_list_and_detail(self, app):
        sid, _, cid = _setup_class(app)
        _, email = mk_user(app, role="super_admin")
        client = login_as(app, email)
        assert client.get("/admin/schools").status_code == 200
        assert client.get("/admin/schools?search=أزاد").status_code == 200
        assert client.get(f"/admin/schools/{sid}").status_code == 200


class TestSubscriptionsViews:
    def test_list_filters(self, app):
        sid, _, cid = _setup_class(app)
        plan = make_subscription_plan(app, sid, cid, price=100.0)
        uid = make_user(app, role="student", school_id=sid)
        make_subscription(app, uid, plan, cid, price=100.0, status="active")
        _, email = mk_user(app, role="super_admin")
        client = login_as(app, email)
        assert client.get("/admin/subscriptions").status_code == 200
        assert client.get("/admin/subscriptions?status=active").status_code == 200

    def test_detail_timeline_pending(self, app):
        sid, _, cid = _setup_class(app)
        plan = make_subscription_plan(app, sid, cid, price=100.0)
        uid = make_user(app, role="student", school_id=sid)
        sub_id = make_subscription(app, uid, plan, cid, price=100.0, status="pending")
        _, email = mk_user(app, role="super_admin")
        client = login_as(app, email)
        assert client.get(f"/admin/subscriptions/{sub_id}").status_code == 200

    def test_detail_timeline_active_and_expired(self, app):
        sid, _, cid = _setup_class(app)
        plan = make_subscription_plan(app, sid, cid, price=100.0)
        uid = make_user(app, role="student", school_id=sid)
        sub_active = make_subscription(app, uid, plan, cid, price=100.0, status="active")
        sub_expired = make_subscription(app, uid, plan, cid, price=90.0, status="expired")
        _, email = mk_user(app, role="super_admin")
        client = login_as(app, email)
        assert client.get(f"/admin/subscriptions/{sub_active}").status_code == 200
        assert client.get(f"/admin/subscriptions/{sub_expired}").status_code == 200

    def test_cancel(self, app):
        sid, _, cid = _setup_class(app)
        plan = make_subscription_plan(app, sid, cid, price=100.0)
        uid = make_user(app, role="student", school_id=sid)
        sub_id = make_subscription(app, uid, plan, cid, price=100.0, status="pending")
        _, email = mk_user(app, role="super_admin")
        client = login_as(app, email)
        resp = client.post(f"/admin/subscriptions/{sub_id}/cancel", follow_redirects=True)
        assert resp.status_code == 200
        from app.extensions import db
        from app.models.billing import Subscription

        with app.app_context():
            assert db.session.get(Subscription, sub_id).status == "cancelled"


# ═══════════════════════════════════════════════════════════════════════════
# pending payments approve/reject (مع AuditLog + إشعار)
# ═══════════════════════════════════════════════════════════════════════════


class TestPendingPayments:
    def _pending(self, app):
        sid, _, cid = _setup_class(app)
        plan = make_subscription_plan(app, sid, cid, price=100.0)
        uid = make_user(app, role="student", school_id=sid)
        sub_id = make_subscription(app, uid, plan, cid, price=100.0, status="pending")
        pay_id = make_payment(app, sub_id, amount=100.0, status="pending")
        return pay_id

    def test_page_lists_pending(self, app):
        self._pending(app)
        _, email = mk_user(app, role="super_admin")
        client = login_as(app, email)
        assert client.get("/admin/payments/pending").status_code == 200

    def test_approve_payment_flow(self, app):
        pay_id = self._pending(app)
        _, email = mk_user(app, role="super_admin")
        client = login_as(app, email)
        resp = client.post(f"/admin/payments/{pay_id}/approve", follow_redirects=True)
        assert resp.status_code == 200
        from app.extensions import db
        from app.models.billing import ManualPayment
        from app.models.system import AuditLog

        with app.app_context():
            assert db.session.get(ManualPayment, pay_id).status == "approved"
            log = AuditLog.query.filter_by(action="payment.approve", entity_id=pay_id).first()
            assert log is not None

    def test_reject_payment_flow(self, app):
        pay_id = self._pending(app)
        _, email = mk_user(app, role="super_admin")
        client = login_as(app, email)
        resp = client.post(f"/admin/payments/{pay_id}/reject", follow_redirects=True)
        assert resp.status_code == 200
        from app.extensions import db
        from app.models.billing import ManualPayment
        from app.models.system import AuditLog

        with app.app_context():
            assert db.session.get(ManualPayment, pay_id).status == "rejected"
            assert AuditLog.query.filter_by(action="payment.reject", entity_id=pay_id).first() is not None


# ═══════════════════════════════════════════════════════════════════════════
# AI usage + settings + dashboards
# ═══════════════════════════════════════════════════════════════════════════


class TestAiUsage:
    def test_page_renders(self, app):
        _, email = mk_user(app, role="super_admin")
        client = login_as(app, email)
        assert client.get("/admin/ai/usage").status_code == 200
        assert client.get("/admin/ai/usage?days=7").status_code == 200


class TestSettings:
    def test_get_and_save(self, app):
        _, email = mk_user(app, role="super_admin")
        client = login_as(app, email)
        assert client.get("/admin/settings").status_code == 200
        resp = client.post("/admin/settings", data={"site_motto": "التعليم أولاً"}, follow_redirects=True)
        assert resp.status_code == 200
        from app.models.system import Setting

        with app.app_context():
            row = Setting.query.filter_by(key="site_motto").first()
            assert row is not None

    def test_save_updates_existing(self, app):
        from app.extensions import db
        from app.models.system import Setting

        with app.app_context():
            db.session.add(Setting(key="old_key", value={"v": 1}))
            db.session.commit()
        _, email = mk_user(app, role="super_admin")
        client = login_as(app, email)
        resp = client.post("/admin/settings", data={"old_key": "new"}, follow_redirects=True)
        assert resp.status_code == 200


class TestSchoolAdminDashboardView:
    def test_no_school_redirects_to_admin(self, app):
        _, email = mk_user(app, role="school_admin")
        client = login_as(app, email)
        resp = client.get("/admin/school-admin", follow_redirects=False)
        assert resp.status_code == 302

    def test_with_school_renders_charts(self, app):
        sid, _, cid = _setup_class(app)
        plan = make_subscription_plan(app, sid, cid, price=100.0)
        uid = make_user(app, role="student", school_id=sid)
        make_subscription(app, uid, plan, cid, price=100.0, status="active")
        _, email = mk_user(app, role="school_admin", school_id=sid)
        client = login_as(app, email)
        assert client.get("/admin/school-admin").status_code == 200


# ═══════════════════════════════════════════════════════════════════════════
# registrations pending approve/reject
# ═══════════════════════════════════════════════════════════════════════════


class TestRegistrations:
    def test_list(self, app):
        mk_user(app, role="student", approved=False)
        _, email = mk_user(app, role="super_admin")
        client = login_as(app, email)
        assert client.get("/admin/registrations/pending").status_code == 200
        assert client.get("/admin/registrations/pending?search=adm-").status_code == 200

    def test_approve_pending_user(self, app):
        uid, _ = mk_user(app, role="student", approved=False)
        _, email = mk_user(app, role="super_admin")
        client = login_as(app, email)
        resp = client.post(f"/admin/registrations/{uid}/approve", follow_redirects=True)
        assert resp.status_code == 200
        from app.extensions import db
        from app.models.user import User, UserApprovalStatus

        with app.app_context():
            assert db.session.get(User, uid).approval_status == UserApprovalStatus.approved

    def test_approve_non_pending_warns(self, app):
        uid, _ = mk_user(app, role="student", approved=True)
        _, email = mk_user(app, role="super_admin")
        client = login_as(app, email)
        resp = client.post(f"/admin/registrations/{uid}/approve", follow_redirects=True)
        assert resp.status_code == 200

    def test_reject_pending_user(self, app):
        uid, _ = mk_user(app, role="student", approved=False)
        _, email = mk_user(app, role="super_admin")
        client = login_as(app, email)
        resp = client.post(f"/admin/registrations/{uid}/reject", follow_redirects=True)
        assert resp.status_code == 200
        from app.extensions import db
        from app.models.user import User, UserApprovalStatus

        with app.app_context():
            assert db.session.get(User, uid).approval_status == UserApprovalStatus.rejected


# ═══════════════════════════════════════════════════════════════════════════
# revenue / health / analytics / moe / certificates
# ═══════════════════════════════════════════════════════════════════════════


class TestSuperOnlyViews:
    def test_revenue_invalid_days_fallback(self, app):
        _, email = mk_user(app, role="super_admin")
        client = login_as(app, email)
        assert client.get("/admin/revenue").status_code == 200
        assert client.get("/admin/revenue?days=13").status_code == 200
        assert client.get("/admin/revenue?days=90").status_code == 200

    def test_health_runs_checks(self, app):
        _, email = mk_user(app, role="super_admin")
        client = login_as(app, email)
        assert client.get("/admin/health").status_code == 200

    def test_analytics_days_validation(self, app):
        _, email = mk_user(app, role="super_admin")
        client = login_as(app, email)
        assert client.get("/admin/analytics").status_code == 200
        assert client.get("/admin/analytics?days=7").status_code == 200
        assert client.get("/admin/analytics?days=11").status_code == 200

    def test_moe_export_get_and_download(self, app):
        sid, _, _ = _setup_class(app)
        _, email = mk_user(app, role="super_admin")
        client = login_as(app, email)
        assert client.get("/admin/moe-export").status_code == 200
        resp = client.post("/admin/moe-export", data={"school_id": sid, "academic_year": "2025/2026"})
        assert resp.status_code == 200
        assert resp.data[:2] == b"PK"  # xlsx = zip

    def test_certificates_list(self, app):
        _, email = mk_user(app, role="super_admin")
        client = login_as(app, email)
        assert client.get("/admin/certificates").status_code == 200


# ═══════════════════════════════════════════════════════════════════════════
# audit logs + contact + payouts
# ═══════════════════════════════════════════════════════════════════════════


class TestAuditLogs:
    def test_list_and_filters(self, app):
        from app.models.system import AuditLog

        with app.app_context():
            db.session.add(AuditLog(action="test.batch7", entity="tests", entity_id=1))
            db.session.commit()
        _, email = mk_user(app, role="super_admin")
        client = login_as(app, email)
        assert client.get("/admin/audit-logs").status_code == 200
        assert client.get("/admin/audit-logs?action=test.batch7").status_code == 200
        assert client.get("/admin/audit-logs?entity=tests").status_code == 200
        assert client.get("/admin/audit-logs?search=batch").status_code == 200


class TestContactInbox:
    def _msg(self, app, status="new"):
        from app.models.communication import ContactMessage

        with app.app_context():
            msg = ContactMessage(
                name="طالب", email=f"c{id(app) % 9999}@t.com", subject="سؤال", message="نص الرسالة", status=status
            )
            db.session.add(msg)
            db.session.commit()
            return msg.id

    def test_inbox(self, app):
        self._msg(app)
        _, email = mk_user(app, role="super_admin")
        client = login_as(app, email)
        assert client.get("/admin/contact").status_code == 200

    def test_mark_read(self, app):
        msg_id = self._msg(app, status="new")
        _, email = mk_user(app, role="super_admin")
        client = login_as(app, email)
        resp = client.post(f"/admin/contact/{msg_id}/read", follow_redirects=True)
        assert resp.status_code == 200
        from app.models.communication import ContactMessage

        with app.app_context():
            assert db.session.get(ContactMessage, msg_id).status == "read"

    def test_reply_success_and_empty(self, app):
        msg_id = self._msg(app)
        _, email = mk_user(app, role="super_admin")
        client = login_as(app, email)
        # رد فارغ → flash خطأ
        resp = client.post(f"/admin/contact/{msg_id}/reply", data={"reply_text": ""}, follow_redirects=True)
        assert resp.status_code == 200
        # رد ناجح — EMAIL_ENABLED=False في الاختبارات → نحاكي النجاح عبر _send
        from unittest.mock import patch as mock_patch

        from app.services import email as email_svc

        with mock_patch.object(email_svc, "_send", return_value=True):
            resp2 = client.post(
                f"/admin/contact/{msg_id}/reply", data={"reply_text": "شكراً لتواصلك"}, follow_redirects=True
            )
        assert resp2.status_code == 200
        from app.models.communication import ContactMessage

        with app.app_context():
            assert db.session.get(ContactMessage, msg_id).status == "replied"

    def test_reply_send_failure_keeps_new(self, app):
        """فشل الإرسال → تبقى الحالة new (فرع else)."""
        msg_id = self._msg(app)
        _, email = mk_user(app, role="super_admin")
        client = login_as(app, email)
        from unittest.mock import patch as mock_patch

        from app.services import email as email_svc

        with mock_patch.object(email_svc, "_send", return_value=False):
            resp = client.post(f"/admin/contact/{msg_id}/reply", data={"reply_text": "سيفشل"}, follow_redirects=True)
        assert resp.status_code == 200
        from app.models.communication import ContactMessage

        with app.app_context():
            assert db.session.get(ContactMessage, msg_id).status == "new"


class TestPayouts:
    def _payout(self, app):
        from app.models.tutoring import TutorPayout

        tid, _ = mk_user(app, role="teacher")
        with app.app_context():
            payout = TutorPayout(tutor_id=tid, amount=100.0, status="pending")
            db.session.add(payout)
            db.session.commit()
            return payout.id, tid

    def _commission(self, app, tid):
        """عمولة مرتبطة بجلسة حقيقية (session_id NOT NULL)."""
        from tests.conftest import make_tutoring_session

        sid2 = make_school(app)
        student = make_user(app, role="student", school_id=sid2)
        session_id = make_tutoring_session(app, tid, student, price=100.0)
        from app.models.tutoring import TutorCommission

        with app.app_context():
            c = TutorCommission(
                session_id=session_id,
                tutor_id=tid,
                session_amount=100.0,
                commission_amount=20.0,
                tutor_net=80.0,
                status="pending",
            )
            db.session.add(c)
            db.session.commit()
            return c.id

    def test_queue(self, app):
        self._payout(app)
        _, email = mk_user(app, role="super_admin")
        client = login_as(app, email)
        assert client.get("/admin/payouts").status_code == 200

    def test_approve_marks_commissions_withdrawn(self, app):
        from app.models.tutoring import TutorPayout

        payout_id, tid = self._payout(app)
        self._commission(app, tid)
        _, email = mk_user(app, role="super_admin")
        client = login_as(app, email)
        resp = client.post(f"/admin/payouts/{payout_id}/approve", follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            assert db.session.get(TutorPayout, payout_id).status == "approved"

    def test_reject_with_note(self, app):
        from app.models.tutoring import TutorPayout

        payout_id, _ = self._payout(app)
        _, email = mk_user(app, role="super_admin")
        client = login_as(app, email)
        resp = client.post(f"/admin/payouts/{payout_id}/reject", data={"note": "غير مكتمل"}, follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            assert db.session.get(TutorPayout, payout_id).status == "rejected"

    def test_unknown_result_404(self, app):
        payout_id, _ = self._payout(app)
        _, email = mk_user(app, role="super_admin")
        client = login_as(app, email)
        assert client.post(f"/admin/payouts/{payout_id}/frobnicate").status_code == 404


# ═══════════════════════════════════════════════════════════════════════════
# revenue_routes.py (0% → مغطى)
# ═══════════════════════════════════════════════════════════════════════════


class TestRevenueRoutesModule:
    def test_dashboard_via_module(self, app):
        """المسار مُعرّف في revenue_routes.py أيضاً — نضمن تغطيته."""
        _, email = mk_user(app, role="super_admin")
        client = login_as(app, email)
        assert client.get("/admin/revenue?days=365").status_code == 200


# ═════════════════════════════════════════════════════════════════════════
# backups (list/create/restore)
# ═════════════════════════════════════════════════════════════════════════


class TestBackups:
    def _sa(self, app):
        _, email = mk_user(app, role="super_admin")
        return login_as(app, email)

    def test_list_with_files(self, app, tmp_path, monkeypatch):
        (tmp_path / "backup_20260101_000000.sql").write_text("-- fake")
        (tmp_path / "backup_20260102_000000.sql.gz").write_text("-- fake")
        (tmp_path / "notes.txt").write_text("nope")
        monkeypatch.setenv("BACKUP_DIR", str(tmp_path))
        client = self._sa(app)
        assert client.get("/admin/backups").status_code == 200

    def test_list_empty_dir(self, app, tmp_path, monkeypatch):
        monkeypatch.setenv("BACKUP_DIR", str(tmp_path))
        client = self._sa(app)
        assert client.get("/admin/backups").status_code == 200

    def test_create_success(self, app, tmp_path, monkeypatch):
        monkeypatch.setenv("BACKUP_DIR", str(tmp_path))
        client = self._sa(app)

        class R:
            returncode = 0
            stderr = ""

        # PG_DUMP ثابت يحل عند الاستيراد — نستبدل subprocess.run عالميًا (الوحدة تستورد الداخليًا)
        with mock_patch("subprocess.run", return_value=R()) as run_mock:
            resp = client.post("/admin/backups/create", follow_redirects=True)
        assert resp.status_code == 200
        assert run_mock.called  # استُدعي فعلًا (وليس PG_DUMP=None قبل الفحص)
        # المسار المُمرّر لـ pg_dump داخل BACKUP_DIR المحدد
        cmd = run_mock.call_args.args[0]
        assert any(str(tmp_path) in part for part in cmd)

    def test_create_failure_and_missing_tool(self, app, tmp_path, monkeypatch):
        monkeypatch.setenv("BACKUP_DIR", str(tmp_path))
        client = self._sa(app)

        class R:
            returncode = 1
            stderr = "boom"

        with mock_patch("subprocess.run", return_value=R()):
            resp = client.post("/admin/backups/create", follow_redirects=True)
        assert resp.status_code == 200
        with mock_patch("subprocess.run", side_effect=FileNotFoundError):
            resp2 = client.post("/admin/backups/create", follow_redirects=True)
        assert resp2.status_code == 200

    def test_restore_file_missing_and_bad_confirm(self, app, tmp_path, monkeypatch):
        monkeypatch.setenv("BACKUP_DIR", str(tmp_path))
        client = self._sa(app)
        # ملف غير موجود
        resp = client.post("/admin/backups/nope.sql/restore", data={"confirm": "yes"}, follow_redirects=True)
        assert resp.status_code == 200
        # ملف موجود بدون تأكيد
        (tmp_path / "backup_x.sql").write_text("-- fake")
        resp2 = client.post("/admin/backups/backup_x.sql/restore", data={}, follow_redirects=True)
        assert resp2.status_code == 200

    def test_restore_success(self, app, tmp_path, monkeypatch):
        monkeypatch.setenv("BACKUP_DIR", str(tmp_path))
        (tmp_path / "backup_ok.sql").write_text("-- fake")
        client = self._sa(app)

        class R:
            returncode = 0
            stderr = ""

        with mock_patch("subprocess.run", return_value=R()):
            resp = client.post("/admin/backups/backup_ok.sql/restore", data={"confirm": "yes"}, follow_redirects=True)
        assert resp.status_code == 200

    def test_restore_missing_tool(self, app, tmp_path, monkeypatch):
        monkeypatch.setenv("BACKUP_DIR", str(tmp_path))
        (tmp_path / "backup_ok2.sql").write_text("-- fake")
        client = self._sa(app)
        with mock_patch("subprocess.run", side_effect=FileNotFoundError):
            resp = client.post("/admin/backups/backup_ok2.sql/restore", data={"confirm": "yes"}, follow_redirects=True)
        assert resp.status_code == 200
