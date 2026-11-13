"""Round K — branch closure: billing + tutoring + admin partial branches.

Targets the branch arcs still reported missing by CI (run 43296221930):

- app/modules/billing/routes.py: invalid plan form, ``create_plan`` /
  ``subscribe`` / ``record_manual_payment`` returning ``(None, None)``, invalid
  payment form, receipt whose subscription is invisible to the caller, and
  ``create_discount_code`` returning ``(None, None)``.
- app/modules/tutoring/routes.py: ``create_tutor_profile`` returning
  ``(None, None)``, in-range booking price, ``create_request`` returning
  ``(None, None)``, payment rejection that leaves the session not ``pending``,
  a session with no timing data at all, and ``request_payout`` returning
  ``(None, None)``.
- app/modules/admin/routes.py: ``_find_pg_tool`` PATH/ProgramFiles fallback and
  the bulk-action delete arms for users and schools.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

from app.models.billing import PaymentReceipt
from tests.conftest import (
    _db,
    _uid,
    make_class,
    make_class_member,
    make_grade,
    make_payment,
    make_school,
    make_subject,
    make_subscription,
    make_subscription_plan,
    make_tutor_profile,
    make_user,
)

PASSWORD = "TestPass123!"

_LEVELS: dict[int, int] = {}


def _next_level(sid: int) -> int:
    _LEVELS[sid] = _LEVELS.get(sid, 0) + 1
    return _LEVELS[sid]


def mk_user(app, role: str, school_id=None):
    email = f"rnd-k-{_uid()}@test.com"
    uid = make_user(app, role=role, school_id=school_id, email=email)
    return uid, email


def login_as(app, email: str):
    client = app.test_client()
    client.post("/auth/login", data={"email": email, "password": PASSWORD})
    return client


def _setup_class(app, teacher_id=None):
    sid = make_school(app)
    gid = make_grade(app, sid, grade_level=_next_level(sid))
    subj = make_subject(app)
    cid = make_class(app, sid, gid, subj, teacher_id=teacher_id)
    return sid, cid


# ═════════════════════════════ billing ═════════════════════════════


class TestBillingBranchClosure:
    def _teacher_class(self, app):
        sid = make_school(app)
        tid, t_email = mk_user(app, "teacher", school_id=sid)
        gid = make_grade(app, sid, grade_level=_next_level(sid))
        cid = make_class(app, sid, gid, make_subject(app), teacher_id=tid)
        return sid, cid, tid, t_email

    def _student_with_subscription(self, app, sid: int, cid: int):
        stu, s_email = mk_user(app, "student", school_id=sid)
        make_class_member(app, cid, stu)
        plan_id = make_subscription_plan(app, sid, class_id=cid, price=0.0)
        sub_id = make_subscription(app, stu, plan_id, cid, price=0.0)
        return stu, s_email, plan_id, sub_id

    def test_plan_create_rejects_invalid_form(self, app):
        """خطة بلا اسم أو سعر لا تُمرَّر إلى الخدمة."""
        _, cid, _, t_email = self._teacher_class(app)
        client = login_as(app, t_email)
        with patch("app.modules.billing.routes.create_plan") as created:
            resp = client.post(f"/billing/{cid}/plans", data={"name": "", "price": ""}, follow_redirects=False)
        assert resp.status_code == 302
        created.assert_not_called()

    def test_plan_create_without_object_or_error(self, app):
        """create_plan → (None, None): لا تدقيق ولا رسالة نجاح."""
        _, cid, _, t_email = self._teacher_class(app)
        client = login_as(app, t_email)
        with (
            patch("app.modules.billing.routes.create_plan", return_value=(None, None)),
            patch("app.modules.billing.routes.audit") as audited,
        ):
            resp = client.post(
                f"/billing/{cid}/plans",
                data={"name": "خطة", "price": "50", "currency": "ILS"},
                follow_redirects=False,
            )
        assert resp.status_code == 302
        audited.assert_not_called()

    def test_subscribe_without_object_or_error(self, app):
        """subscribe → (None, None): لا اشتراك ولا تدقيق."""
        sid, cid, _, _ = self._teacher_class(app)
        _, s_email, plan_id, _ = self._student_with_subscription(app, sid, cid)
        client = login_as(app, s_email)
        with (
            patch("app.modules.billing.routes.subscribe", return_value=(None, None)),
            patch("app.modules.billing.routes.audit") as audited,
        ):
            resp = client.post(f"/billing/{cid}/subscribe", data={"plan_id": plan_id}, follow_redirects=False)
        assert resp.status_code == 302
        audited.assert_not_called()

    def test_payment_create_rejects_invalid_form(self, app):
        """دفع بلا مرجع أو مبلغ لا يُسجَّل."""
        sid, cid, _, _ = self._teacher_class(app)
        _, s_email, _, sub_id = self._student_with_subscription(app, sid, cid)
        client = login_as(app, s_email)
        with patch("app.modules.billing.routes.record_manual_payment") as recorded:
            resp = client.post(f"/billing/subscriptions/{sub_id}/pay", data={}, follow_redirects=False)
        assert resp.status_code == 302
        recorded.assert_not_called()

    def test_payment_create_without_object_or_error(self, app):
        """record_manual_payment → (None, None): لا تدقيق ولا رسالة نجاح."""
        sid, cid, _, _ = self._teacher_class(app)
        _, s_email, _, sub_id = self._student_with_subscription(app, sid, cid)
        client = login_as(app, s_email)
        with (
            patch("app.modules.billing.routes.record_manual_payment", return_value=(None, None)),
            patch("app.modules.billing.routes.audit") as audited,
        ):
            resp = client.post(
                f"/billing/subscriptions/{sub_id}/pay",
                data={"reference": "TRX-1", "amount": "10"},
                follow_redirects=False,
            )
        assert resp.status_code == 302
        audited.assert_not_called()

    def test_payment_file_hidden_from_non_owner(self, app):
        """إيصال اشتراك لا يُرى لغير صاحب الاشتراك — RLS يُخفيه فيصير 404.

        ``payment_receipts`` مُقيَّد بذراع ملكية الاشتراك، فالمستخدم غير
        المرتبط لا يصل إلى الصفّ أصلاً (لا يُبنى له قرار وصول).
        """
        sid, cid, _, _ = self._teacher_class(app)
        stu_a, _ = mk_user(app, "student", school_id=sid)
        make_class_member(app, cid, stu_a)
        plan_id = make_subscription_plan(app, sid, class_id=cid)
        sub_id = make_subscription(app, stu_a, plan_id, cid)
        pay_id = make_payment(app, sub_id, amount=55.0)
        stored = f"receipt-{_uid()[:10]}.pdf"
        with app.app_context():
            _db.session.add(PaymentReceipt(manual_payment_id=pay_id, stored_name=stored, original_name="r.pdf"))
            _db.session.commit()

        _, o_email = mk_user(app, "student")
        client = login_as(app, o_email)
        resp = client.get(f"/billing/payments/receipts/{stored}", follow_redirects=False)
        assert resp.status_code == 404

    def test_discount_create_without_object_or_error(self, app):
        """create_discount_code → (None, None): تعود الاستمارة بلا توجيه."""
        sid = make_school(app)
        _, a_email = mk_user(app, "school_admin", school_id=sid)
        client = login_as(app, a_email)
        with patch("app.modules.billing.routes.create_discount_code", return_value=(None, None)):
            resp = client.post(
                "/billing/discounts/new",
                data={"code": "SAVE10", "name": "خصم", "type": "percentage", "value": "10", "max_uses": "5"},
                follow_redirects=False,
            )
        assert resp.status_code == 200


# ═════════════════════════════ tutoring ═════════════════════════════


class TestTutoringBranchClosure:
    def _tutor_and_student(self, app, price_hour=100.0, price_session=100.0):
        sid = make_school(app)
        tid, t_email = mk_user(app, "teacher", school_id=sid)
        make_tutor_profile(app, tid, price_hour=price_hour)
        with app.app_context():
            from app.models.tutoring import TutorProfile

            prof = TutorProfile.query.filter_by(tutor_id=tid).first()
            prof.price_session = Decimal(str(price_session))
            _db.session.commit()
        stu, s_email = mk_user(app, "student", school_id=sid)
        return tid, t_email, stu, s_email

    def test_profile_new_without_object_or_error(self, app):
        """create_tutor_profile → (None, None): لا تدقيق ولا توجيه للملف."""
        _, t_email = mk_user(app, "teacher")
        client = login_as(app, t_email)
        with (
            patch("app.modules.tutoring.routes.create_tutor_profile", return_value=(None, None)),
            patch("app.modules.tutoring.routes.audit") as audited,
        ):
            resp = client.post(
                "/tutoring/profile/new",
                data={"subject": "رياضيات", "price_hour": "80", "mode": "both"},
                follow_redirects=False,
            )
        assert resp.status_code == 200
        audited.assert_not_called()

    def test_book_with_price_inside_allowed_range(self, app):
        """سعر داخل 80%–150% من سعر المعلم يمرّ إلى إنشاء الطلب."""
        tid, _, _, s_email = self._tutor_and_student(app, price_hour=100.0)
        client = login_as(app, s_email)
        resp = client.post(
            f"/tutoring/book/{tid}",
            data={
                "subject": "رياضيات",
                "preferred_time": "2026-12-01T10:00",
                "mode": "offline",
                "price_quote": "100",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302
        with app.app_context():
            from app.models.tutoring import TutoringRequest

            req = TutoringRequest.query.filter_by(tutor_id=tid).first()
            assert req is not None
            assert float(req.price_quote) == 100.0

    def test_book_without_object_or_error(self, app):
        """create_request → (None, None): تعود صفحة الحجز بلا طلب."""
        tid, _, _, s_email = self._tutor_and_student(app)
        client = login_as(app, s_email)
        with patch("app.modules.tutoring.routes.create_request", return_value=(None, None)):
            resp = client.post(
                f"/tutoring/book/{tid}",
                data={
                    "subject": "رياضيات",
                    "preferred_time": "2026-12-01T10:00",
                    "mode": "offline",
                    "price_quote": "100",
                },
                follow_redirects=False,
            )
        assert resp.status_code == 200
        with app.app_context():
            from app.models.tutoring import TutoringRequest

            assert TutoringRequest.query.filter_by(tutor_id=tid).count() == 0

    def test_pay_reject_when_session_not_pending(self, app):
        """رفض الدفع على جلسة غير معلّقة لا يُدوَّن كرفض."""
        tid, t_email, stu, _ = self._tutor_and_student(app)
        with app.app_context():
            from app.models.tutoring import TutoringSession

            sess = TutoringSession(tutor_id=tid, student_id=stu, subject="رياضيات", status="active")
            _db.session.add(sess)
            _db.session.commit()
            sess_id = sess.id
        client = login_as(app, t_email)
        with (
            patch(
                "app.services.tutoring.reject_session_payment_by_tutor",
                return_value=("unpaid", None),
            ),
            patch("app.modules.tutoring.routes.audit") as audited,
        ):
            resp = client.post(f"/tutoring/sessions/{sess_id}/pay-reject", follow_redirects=False)
        assert resp.status_code == 302
        audited.assert_not_called()

    def test_rate_session_without_any_timing(self, app):
        """جلسة بلا وقت بدء ولا مدة ولا وقت انتهاء تُفتح للتقييم بلا حجب."""
        tid, _, stu, s_email = self._tutor_and_student(app)
        with app.app_context():
            from app.models.tutoring import TutoringSession

            sess = TutoringSession(
                tutor_id=tid,
                student_id=stu,
                subject="رياضيات",
                status="completed",
                scheduled_at=None,
                duration_min=None,
                end_time=None,
            )
            _db.session.add(sess)
            _db.session.commit()
            sess_id = sess.id
        client = login_as(app, s_email)
        resp = client.get(f"/tutoring/rate/{sess_id}")
        assert resp.status_code == 200

    def test_payout_request_without_payout(self, app):
        """request_payout → (None, None): لا رسالة نجاح ولا سحب."""
        _, t_email = mk_user(app, "teacher")
        client = login_as(app, t_email)
        with patch("app.modules.tutoring.routes.request_payout", return_value=(None, None)):
            resp = client.post("/tutoring/payout-request", data={"amount": "500"}, follow_redirects=False)
        assert resp.status_code == 302


# ═════════════════════════════ admin ═════════════════════════════


class TestAdminBranchClosure:
    def test_find_pg_tool_scans_program_files_without_match(self, app):
        """لا أداة في PATH ولا ملف في ProgramFiles → يعود الاسم المجرّد."""
        from app.modules.admin import routes as admin_routes

        with (
            patch("app.modules.admin.routes.shutil.which", return_value=None),
            patch("app.modules.admin.routes.os.path.isdir", return_value=True),
            patch("app.modules.admin.routes.os.listdir", return_value=["16", "15"]),
            patch("app.modules.admin.routes.os.path.isfile", return_value=False),
        ):
            assert admin_routes._find_pg_tool("pg_dump") == "pg_dump"

    def test_bulk_action_soft_deletes_users(self, app):
        """إجراء «حذف» على المستخدمين يوقف الحساب ويضع تاريخ الحذف."""
        _, a_email = mk_user(app, "super_admin")
        first, _ = mk_user(app, "student")
        second, _ = mk_user(app, "student")
        client = login_as(app, a_email)
        resp = client.post(
            "/admin/bulk-action",
            json={"entity": "users", "action": "delete", "ids": [first, second]},
        )
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True
        with app.app_context():
            from app.models.user import User

            for uid in (first, second):
                user = _db.session.get(User, uid)
                assert user.is_active is False
                assert user.deleted_at is not None

    def test_bulk_action_soft_deletes_schools(self, app):
        """إجراء «حذف» على المدارس يعطّل المدرسة."""
        _, a_email = mk_user(app, "super_admin")
        first = make_school(app)
        second = make_school(app)
        client = login_as(app, a_email)
        resp = client.post(
            "/admin/bulk-action",
            json={"entity": "schools", "action": "delete", "ids": [first, second]},
        )
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True
        with app.app_context():
            from app.models.school import School

            for sid in (first, second):
                assert _db.session.get(School, sid).is_active is False
