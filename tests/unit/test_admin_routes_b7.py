"""B7 — admin route coverage: registrations, contact inbox, payouts, subscription timeline, filters.

Targets admin write/action endpoints and branch forks verified as uncovered.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from tests.conftest import (
    make_class,
    make_grade,
    make_school,
    make_subject,
    make_subscription,
    make_subscription_plan,
    make_tutoring_session,
    make_user,
)

PASSWORD = "TestPass123!"


def _email() -> str:
    return f"b7-{uuid.uuid4().hex[:10]}@test.com"


def superadmin(app):
    """Super-admin persona → (user_id, client)."""
    email = _email()
    uid = make_user(app, role="super_admin", email=email)
    client = app.test_client()
    client.post("/auth/login", data={"email": email, "password": PASSWORD})
    return uid, client


def _status_of(app, model, row_id):
    with app.app_context():
        from app.extensions import db

        return db.session.get(model, row_id).status


# ═══════════════════ registrations ═══════════════════


class TestRegistrations:
    def test_approve_pending_user(self, app):
        _, client = superadmin(app)
        email = _email()
        uid = make_user(app, role="student", approved=False, email=email)
        resp = client.post(f"/admin/registrations/{uid}/approve", follow_redirects=False)
        assert resp.status_code == 302
        with app.app_context():
            from app.extensions import db
            from app.models.user import User

            assert db.session.get(User, uid).approval_status.value == "approved"

    def test_approve_non_pending_is_noop(self, app):
        _, client = superadmin(app)
        uid = make_user(app, role="student", approved=True)
        assert client.post(f"/admin/registrations/{uid}/approve", follow_redirects=False).status_code == 302

    def test_reject_pending_user(self, app):
        _, client = superadmin(app)
        uid = make_user(app, role="student", approved=False)
        resp = client.post(f"/admin/registrations/{uid}/reject", follow_redirects=False)
        assert resp.status_code == 302
        with app.app_context():
            from app.extensions import db
            from app.models.user import User

            assert db.session.get(User, uid).approval_status.value == "rejected"

    def test_pending_list_with_search_and_page(self, app):
        _, client = superadmin(app)
        make_user(app, role="student", approved=False)
        assert client.get("/admin/registrations/pending?search=zz&page=1").status_code == 200


# ═══════════════════ contact inbox ═══════════════════


class TestContactInbox:
    def _msg(self, app, status="new") -> int:
        from app.extensions import db
        from app.models.communication import ContactMessage

        with app.app_context():
            m = ContactMessage(name="طالب", email=_email(), subject="استفسار", message="مرحبا", status=status)
            db.session.add(m)
            db.session.commit()
            return m.id

    def test_mark_read(self, app):
        _, client = superadmin(app)
        mid = self._msg(app, "new")
        assert client.post(f"/admin/contact/{mid}/read", follow_redirects=False).status_code == 302
        from app.models.communication import ContactMessage

        assert _status_of(app, ContactMessage, mid) == "read"

    def test_mark_read_idempotent_when_already_read(self, app):
        _, client = superadmin(app)
        mid = self._msg(app, "read")
        assert client.post(f"/admin/contact/{mid}/read", follow_redirects=False).status_code == 302

    def test_reply_empty_text_rejected(self, app):
        _, client = superadmin(app)
        mid = self._msg(app, "new")
        resp = client.post(f"/admin/contact/{mid}/reply", data={"reply_text": "  "}, follow_redirects=False)
        assert resp.status_code == 302
        from app.models.communication import ContactMessage

        assert _status_of(app, ContactMessage, mid) == "new"

    def test_reply_success_marks_replied(self, app, monkeypatch):
        import app.services.email as email_svc

        monkeypatch.setattr(email_svc, "send_contact_reply_email", lambda msg, text: True)
        _, client = superadmin(app)
        mid = self._msg(app, "new")
        resp = client.post(f"/admin/contact/{mid}/reply", data={"reply_text": "ردنا عليك"}, follow_redirects=False)
        assert resp.status_code == 302
        from app.models.communication import ContactMessage

        assert _status_of(app, ContactMessage, mid) == "replied"

    def test_reply_send_failure_keeps_status(self, app, monkeypatch):
        import app.services.email as email_svc

        monkeypatch.setattr(email_svc, "send_contact_reply_email", lambda msg, text: False)
        _, client = superadmin(app)
        mid = self._msg(app, "new")
        resp = client.post(f"/admin/contact/{mid}/reply", data={"reply_text": "رد"}, follow_redirects=False)
        assert resp.status_code == 302
        from app.models.communication import ContactMessage

        assert _status_of(app, ContactMessage, mid) == "new"


# ═══════════════════ payouts queue ═══════════════════


class TestPayoutReview:
    def _payout(self, app, status="pending") -> int:
        from app.extensions import db
        from app.models.tutoring import TutorPayout

        tutor = make_user(app, role="teacher")
        with app.app_context():
            p = TutorPayout(tutor_id=tutor, amount=Decimal("250.00"), status=status)
            db.session.add(p)
            db.session.commit()
            return p.id

    def test_approve_marks_payout_approved(self, app):
        _, client = superadmin(app)
        pid = self._payout(app)
        resp = client.post(f"/admin/payouts/{pid}/approve", follow_redirects=False)
        assert resp.status_code == 302
        from app.models.tutoring import TutorPayout

        assert _status_of(app, TutorPayout, pid) == "approved"

    def test_approve_withdraws_pending_commissions(self, app):
        from app.extensions import db
        from app.models.tutoring import TutorCommission, TutorPayout

        tutor = make_user(app, role="teacher")
        stud = make_user(app, role="student")
        sess = make_tutoring_session(app, tutor, stud, status="completed")
        with app.app_context():
            p = TutorPayout(tutor_id=tutor, amount=Decimal("80.00"), status="pending")
            db.session.add(p)
            db.session.flush()
            pid = p.id
            c = TutorCommission(
                session_id=sess,
                tutor_id=tutor,
                session_amount=Decimal("100.00"),
                commission_amount=Decimal("20.00"),
                tutor_net=Decimal("80.00"),
                status="pending",
            )
            db.session.add(c)
            db.session.commit()
            cid = c.id
        _, client = superadmin(app)
        assert client.post(f"/admin/payouts/{pid}/approve", follow_redirects=False).status_code == 302
        with app.app_context():
            assert db.session.get(TutorCommission, cid).status == "withdrawn"

    def test_reject_with_note(self, app):
        _, client = superadmin(app)
        pid = self._payout(app)
        resp = client.post(f"/admin/payouts/{pid}/reject", data={"note": "بيانات ناقصة"}, follow_redirects=False)
        assert resp.status_code == 302
        with app.app_context():
            from app.extensions import db
            from app.models.tutoring import TutorPayout

            p = db.session.get(TutorPayout, pid)
            assert p.status == "rejected"
            assert p.note == "بيانات ناقصة"

    def test_invalid_result_404(self, app):
        _, client = superadmin(app)
        pid = self._payout(app)
        assert client.post(f"/admin/payouts/{pid}/explode", follow_redirects=False).status_code == 404

    def test_payouts_queue_page(self, app):
        _, client = superadmin(app)
        self._payout(app)
        assert client.get("/admin/payouts").status_code == 200


# ═══════════════════ subscription detail timeline ═══════════════════


class TestSubscriptionTimeline:
    def _sub(self, app, status: str) -> int:
        sid = make_school(app)
        gid = make_grade(app, sid)
        subj = make_subject(app)
        cid = make_class(app, sid, gid, subj)
        plan = make_subscription_plan(app, sid, class_id=cid)
        uid = make_user(app, role="student", school_id=sid)
        return make_subscription(app, uid, plan, cid, status=status)

    def test_detail_active(self, app):
        _, client = superadmin(app)
        sub_id = self._sub(app, "active")
        resp = client.get(f"/admin/subscriptions/{sub_id}")
        assert resp.status_code == 200
        assert "مُعتمد".encode() in resp.data

    def test_detail_expired_shows_expired_step(self, app):
        _, client = superadmin(app)
        sub_id = self._sub(app, "expired")
        resp = client.get(f"/admin/subscriptions/{sub_id}")
        assert resp.status_code == 200
        assert "منتهي".encode() in resp.data

    def test_detail_pending(self, app):
        _, client = superadmin(app)
        sub_id = self._sub(app, "pending")
        assert client.get(f"/admin/subscriptions/{sub_id}").status_code == 200


# ═══════════════════ audit-logs filters + dashboards ═══════════════════


class TestAuditLogsAndDashboards:
    def _log(self, app, action: str, entity: str | None, user_id: int | None = None) -> int:
        from app.extensions import db
        from app.models.system import AuditLog

        with app.app_context():
            row = AuditLog(user_id=user_id, action=action, entity=entity, entity_id=1, detail={})
            db.session.add(row)
            db.session.commit()
            return row.id

    def test_filters_narrow_results(self, app):
        _, client = superadmin(app)
        self._log(app, "school.create", "schools")
        self._log(app, "user.login", None)
        assert client.get("/admin/audit-logs?action=school&entity=schools").status_code == 200
        assert client.get("/admin/audit-logs?user_id=99999").status_code == 200
        assert client.get("/admin/audit-logs?search=login").status_code == 200

    def test_revenue_days_branches(self, app):
        _, client = superadmin(app)
        assert client.get("/admin/revenue?days=13").status_code == 200  # invalid → 30
        assert client.get("/admin/revenue?days=90").status_code == 200

    def test_analytics_days_branches(self, app):
        _, client = superadmin(app)
        assert client.get("/admin/analytics?days=45").status_code == 200  # invalid → 30
        assert client.get("/admin/analytics?days=7").status_code == 200
