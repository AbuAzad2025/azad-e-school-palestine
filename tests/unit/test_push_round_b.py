"""Extended coverage round B — content/grades routes + payments gateways + email.

Targets CI-verified missed lines:
- app/modules/content/routes.py: attachment upload/youtube/delete/download, shared library, import
- app/modules/grades/routes.py: submission file/grade, rubric create/grade, report-card branches
- app/services/payments.py: Stripe/PayTabs/CashU verify paths, webhook processing,
  fraud detection, ledger entries, extraction helpers
- app/services/email.py: disabled-email, send-failure, renewal-reminder branches
"""

from __future__ import annotations

import hashlib
import hmac as hmac_mod
import json
from decimal import Decimal
from unittest.mock import MagicMock, patch

from tests.conftest import (
    make_class,
    make_class_member,
    make_grade,
    make_grade_category,
    make_grade_item,
    make_lesson,
    make_school,
    make_subject,
    make_subscription,
    make_subscription_plan,
    make_user,
)

PASSWORD = "TestPass123!"

_LEVELS: dict[int, int] = {}


def mk_user(app, role: str, school_id=None):
    from tests.conftest import _uid

    email = f"xb-{_uid()}@test.com"
    uid = make_user(app, role=role, school_id=school_id, email=email)
    return uid, email


def persona(app, role: str, school_id=None):
    uid, email = mk_user(app, role, school_id)
    client = app.test_client()
    client.post("/auth/login", data={"email": email, "password": PASSWORD})
    return uid, client


def login_as(app, uid_email: tuple[int, str]):
    client = app.test_client()
    client.post("/auth/login", data={"email": uid_email[1], "password": PASSWORD})
    return client


def _next_level(sid: int) -> int:
    _LEVELS[sid] = _LEVELS.get(sid, 0) + 1
    return _LEVELS[sid]


def _setup_class(app):
    sid = make_school(app)
    gid = make_grade(app, sid, grade_level=_next_level(sid))
    subj = make_subject(app)
    cid = make_class(app, sid, gid, subj)
    return sid, cid, gid


def _set_class_teacher(app, cid: int, tid: int):
    from app.extensions import db
    from app.models.class_room import ClassRoom

    with app.app_context():
        db.session.get(ClassRoom, cid).teacher_id = tid
        db.session.commit()


# ═════════════════════════════ content routes ═════════════════════════════


class TestContentAttachmentRoutes:
    def _teacher_and_lesson(self, app):
        sid, cid, _ = _setup_class(app)
        tid, t_email = mk_user(app, "teacher", school_id=sid)
        _set_class_teacher(app, cid, tid)
        lid = make_lesson(app, cid)
        return sid, cid, lid, tid, t_email

    def test_youtube_add_by_teacher(self, app):
        _, cid, lid, _, t_email = self._teacher_and_lesson(app)
        client = login_as(app, (0, t_email))
        resp = client.post(
            f"/classes/{cid}/lessons/{lid}/youtube",
            data={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "title": "فيديو الدرس"},
            follow_redirects=False,
        )
        assert resp.status_code == 302

    def test_youtube_by_student_403(self, app):
        sid, cid, lid, _, _ = self._teacher_and_lesson(app)
        stu_id, s_email = mk_user(app, "student", school_id=sid)
        client = login_as(app, (stu_id, s_email))
        resp = client.post(
            f"/classes/{cid}/lessons/{lid}/youtube",
            data={"url": "https://youtube.com/watch?v=x"},
            follow_redirects=False,
        )
        assert resp.status_code == 403

    def test_attachment_delete_by_teacher(self, app):
        _, cid, lid, _, t_email = self._teacher_and_lesson(app)
        att_id = make_attachment_kb(app, lid, kind="video", youtube_url="https://youtube.com/watch?v=abc")
        client = login_as(app, (0, t_email))
        resp = client.post(f"/classes/attachments/{att_id}/delete", follow_redirects=False)
        assert resp.status_code == 302

    def test_attachment_delete_by_student_403(self, app):
        sid, cid, lid, _, _ = self._teacher_and_lesson(app)
        att_id = make_attachment_kb(app, lid, kind="video", youtube_url="https://youtube.com/watch?v=abc")
        stu_id, s_email = mk_user(app, "student", school_id=sid)
        client = login_as(app, (stu_id, s_email))
        resp = client.post(f"/classes/attachments/{att_id}/delete", follow_redirects=False)
        assert resp.status_code == 403

    def test_shared_library_no_school_redirects(self, app):
        uid, email = mk_user(app, "student")
        client = login_as(app, (uid, email))
        resp = client.get("/classes/shared", follow_redirects=False)
        assert resp.status_code == 302

    def test_shared_library_ok(self, app):
        sid = make_school(app)
        uid, email = mk_user(app, "teacher", school_id=sid)
        client = login_as(app, (uid, email))
        resp = client.get("/classes/shared")
        assert resp.status_code == 200

    def test_lesson_import_missing_target_redirects(self, app):
        sid = make_school(app)
        uid, email = mk_user(app, "teacher", school_id=sid)
        gid = make_grade(app, sid, grade_level=_next_level(sid))
        cid = make_class(app, sid, gid, make_subject(app))
        lid = make_lesson(app, cid)
        _set_class_teacher(app, cid, uid)
        client = login_as(app, (uid, email))
        resp = client.post(f"/classes/import/{lid}", follow_redirects=False)
        assert resp.status_code == 302


def make_attachment_kb(app, lesson_id, kind="video", youtube_url=None):
    """Attachment helper: kind=youtube requires youtube_url and no stored_name (CHECK)."""
    from tests.conftest import make_attachment

    return make_attachment(app, lesson_id, kind=kind, youtube_url=youtube_url)


# ═════════════════════════════ grades routes ═════════════════════════════


class TestGradesRoutesGaps:
    def _graded_setup(self, app):
        sid, cid, _ = _setup_class(app)
        tid, t_email = mk_user(app, "teacher", school_id=sid)
        _set_class_teacher(app, cid, tid)
        stu_id, s_email = mk_user(app, "student", school_id=sid)
        make_class_member(app, cid, stu_id)
        cat_id = make_grade_category(app, cid, "واجبات", 50)
        item_id = make_grade_item(app, cid, cat_id, "واجب 1", 100)
        return sid, cid, tid, t_email, stu_id, s_email, item_id

    def test_gradebook_student_view(self, app):
        sid, cid, _, _, stu_id, s_email, item_id = self._graded_setup(app)
        from tests.conftest import make_grade_entry

        make_grade_entry(app, stu_id, item_id, 88)
        client = login_as(app, (stu_id, s_email))
        resp = client.get(f"/classes/{cid}/gradebook")
        assert resp.status_code == 200

    def test_rubric_new_page(self, app):
        sid, cid, _, t_email, _, _, _ = self._graded_setup(app)
        client = login_as(app, (0, t_email))
        resp = client.get(f"/classes/{cid}/rubric/new")
        assert resp.status_code == 200

    def test_rubric_create_success(self, app):
        sid, cid, _, t_email, _, _, _ = self._graded_setup(app)
        client = login_as(app, (0, t_email))
        resp = client.post(
            f"/classes/{cid}/rubric",
            data={
                "title": "معيار الواجب",
                "criteria[0][title]": "الإتقان",
                "criteria[0][max_score]": "10",
                "criteria[1][title]": "التنظيم",
                "criteria[1][max_score]": "5",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302

    def test_rubric_create_missing_title(self, app):
        sid, cid, _, t_email, _, _, _ = self._graded_setup(app)
        client = login_as(app, (0, t_email))
        resp = client.post(
            f"/classes/{cid}/rubric",
            data={"criteria[0][title]": "ب", "criteria[0][max_score]": "5"},
            follow_redirects=True,
        )
        assert resp.status_code == 200

    def test_rubric_grade_denies_other_teacher(self, app):
        sid, cid, _, _, stu_id, _, item_id = self._graded_setup(app)
        from app.models.gradebook import Assignment, Submission
        from tests.conftest import _db

        with app.app_context():
            asg = Assignment.query.filter_by(class_id=cid).first()
            if asg is None:
                asg = Assignment(class_id=cid, title="واجب", created_by=1)
                _db.session.add(asg)
                _db.session.commit()
            sub = Submission(assignment_id=asg.id, student_id=stu_id, body="حل")
            _db.session.add(sub)
            _db.session.commit()
            sub_id = sub.id

        other_tid, other_email = mk_user(app, "teacher", school_id=sid)
        client = login_as(app, (other_tid, other_email))
        resp = client.get(f"/classes/rubric/1/grade/{sub_id}", follow_redirects=False)
        assert resp.status_code == 403


# ═════════════════════════════ payments gateways ═════════════════════════════


def _gateway_config(secret="s3cret"):
    return {"webhook_secret": secret, "server_key": "sk", "encryption_key": "ek", "base_url": "https://api.test"}


class TestPaytabsGatewayVerify:
    def _gw(self):
        from app.services.payments import PayTabsGateway

        return PayTabsGateway(_gateway_config())

    def _intent(self):
        from app.services.payments import PaymentGateway, PaymentIntent, PaymentStatus

        return PaymentIntent(
            id="paytabs_T1",
            gateway=PaymentGateway.PAYTABS,
            amount=Decimal("100"),
            currency="ILS",
            status=PaymentStatus.PENDING,
            user_id=1,
        )

    def test_no_secret_fails(self):
        from app.services.payments import PayTabsGateway

        gw = PayTabsGateway({"webhook_secret": None})
        assert gw.verify_payment(self._intent(), {"payload": {}, "headers": {}}) is False

    def test_bad_signature_fails(self, app):
        gw = self._gw()
        with app.app_context():
            ok = gw.verify_payment(
                self._intent(), {"payload": {"tran_ref": "T1"}, "headers": {"X-Paytabs-Signature": "bad"}}
            )
        assert ok is False

    def test_good_signature_idempotent_hit(self, app):
        from app.models.billing import ProcessedEvent
        from tests.conftest import _db

        gw = self._gw()
        payload = {"tran_ref": "T-IDEM-1"}
        sig = hmac_mod.new(b"s3cret", json.dumps(payload, sort_keys=True).encode(), hashlib.sha256).hexdigest()
        with app.app_context():
            _db.session.add(ProcessedEvent(event_id="paytabs_T-IDEM-1", gateway="paytabs", payload=payload))
            _db.session.commit()
            ok = gw.verify_payment(self._intent(), {"payload": payload, "headers": {"X-Paytabs-Signature": sig}})
        assert ok is True

    def test_good_signature_api_success(self, app):
        gw = self._gw()
        payload = {"tran_ref": "T-NEW-2"}
        sig = hmac_mod.new(b"s3cret", json.dumps(payload, sort_keys=True).encode(), hashlib.sha256).hexdigest()
        fake_resp = MagicMock()
        fake_resp.status_code = 200
        fake_resp.json.return_value = {"payment_result": {"response_code": "100"}}
        with app.app_context():
            with patch("requests.get", return_value=fake_resp):
                ok = gw.verify_payment(self._intent(), {"payload": payload, "headers": {"X-Paytabs-Signature": sig}})
        assert ok is True

    def test_good_signature_api_reject(self, app):
        gw = self._gw()
        payload = {"tran_ref": "T-NEW-3"}
        sig = hmac_mod.new(b"s3cret", json.dumps(payload, sort_keys=True).encode(), hashlib.sha256).hexdigest()
        fake_resp = MagicMock()
        fake_resp.status_code = 200
        fake_resp.json.return_value = {"payment_result": {"response_code": "999"}}
        with app.app_context():
            with patch("requests.get", return_value=fake_resp):
                ok = gw.verify_payment(self._intent(), {"payload": payload, "headers": {"X-Paytabs-Signature": sig}})
        assert ok is False


class TestCashuGatewayVerify:
    def _gw(self):
        from app.services.payments import CashUGateway

        return CashUGateway(_gateway_config())

    def _intent(self):
        from app.services.payments import PaymentGateway, PaymentIntent, PaymentStatus

        return PaymentIntent(
            id="cashu_C1",
            gateway=PaymentGateway.CASHU,
            amount=Decimal("50"),
            currency="ILS",
            status=PaymentStatus.PENDING,
            user_id=1,
        )

    def test_no_secret_fails(self):
        from app.services.payments import CashUGateway

        gw = CashUGateway({"webhook_secret": None})
        assert gw.verify_payment(self._intent(), {"payload": {}, "headers": {}}) is False

    def test_bad_signature_fails(self, app):
        gw = self._gw()
        with app.app_context():
            ok = gw.verify_payment(
                self._intent(),
                {"payload": {"transaction_id": "C1"}, "headers": {"X-Cashu-Signature": "nope"}},
            )
        assert ok is False

    def test_api_success_records_event(self, app):
        from app.models.billing import ProcessedEvent

        gw = self._gw()
        payload = {"transaction_id": "C-OK-1"}
        sig = hmac_mod.new(b"s3cret", json.dumps(payload, sort_keys=True).encode(), hashlib.sha256).hexdigest()
        fake_resp = MagicMock()
        fake_resp.status_code = 200
        fake_resp.json.return_value = {"status": "completed"}
        with app.app_context():
            with patch("requests.get", return_value=fake_resp):
                ok = gw.verify_payment(self._intent(), {"payload": payload, "headers": {"X-Cashu-Signature": sig}})
            assert ok is True
            assert ProcessedEvent.query.filter_by(event_id="cashu_C-OK-1").first() is not None


class TestWebhookProcessing:
    def test_unknown_gateway_returns_error(self, app):
        from app.services.payments import PaymentGateway, get_payment_service

        svc = get_payment_service()
        result = svc.process_webhook(PaymentGateway.MANUAL, {}, {})
        assert result["success"] is False

    def test_verification_failure_path(self, app):
        from app.services.payments import PaymentGateway, get_payment_service

        svc = get_payment_service()
        fake_gw = MagicMock()
        fake_gw.verify_payment.return_value = False
        with patch.object(svc, "gateways", {PaymentGateway.STRIPE: fake_gw}):
            result = svc.process_webhook(PaymentGateway.STRIPE, {"payload": "x"}, {"Stripe-Signature": "y"})
        assert result["success"] is False
        assert result["error"] == "Verification failed"

    def test_handle_missing_subscription_id(self, app):
        from app.services.payments import PaymentGateway, get_payment_service

        svc = get_payment_service()
        # WhatsApp/Manual → None extraction → early return, no crash
        svc._handle_successful_payment({}, PaymentGateway.WHATSAPP)

    def test_extract_subscription_id_all_gateways(self, app):
        from app.services.payments import PaymentGateway, get_payment_service

        svc = get_payment_service()
        assert svc._extract_subscription_id({"metadata": {"subscription_id": "7"}}, PaymentGateway.PAYTABS) == 7
        assert svc._extract_subscription_id({"metadata": {"subscription_id": "9"}}, PaymentGateway.CASHU) == 9
        assert svc._extract_subscription_id({}, PaymentGateway.WHATSAPP) is None
        assert svc._extract_subscription_id({}, PaymentGateway.MANUAL) is None

    def test_extract_amount_variants(self, app):
        from app.services.payments import PaymentGateway, get_payment_service

        svc = get_payment_service()
        stripe_payload = {"data": {"object": {"amount_received": 15050}}}
        assert svc._extract_amount(stripe_payload, PaymentGateway.STRIPE) == Decimal("150.50")
        pt = svc._extract_amount({"amount": "75.25"}, PaymentGateway.PAYTABS)
        assert pt is not None
        assert svc._extract_amount({}, PaymentGateway.STRIPE) is None

    def test_fraud_check_no_history(self, app):

        from app.services.payments import get_payment_service

        svc = get_payment_service()
        sid = make_school(app)
        with app.app_context():
            assert svc._is_suspicious_amount(sid, Decimal("999")) is False

    def test_fraud_check_triggers_review(self, app):

        from app.services.payments import get_payment_service

        svc = get_payment_service()
        sid, cid, _ = _setup_class(app)
        stu_id, _ = mk_user(app, "student", school_id=sid)
        plan_id = make_subscription_plan(app, sid, class_id=cid, price=100.0)
        sub_id = make_subscription(app, stu_id, plan_id, cid, status="pending")
        # seed history: 90 days of small payments via ManualPayment amounts
        from app.models.billing import ManualPayment
        from tests.conftest import _db

        with app.app_context():
            for i in range(5):
                _db.session.add(
                    ManualPayment(
                        subscription_id=sub_id,
                        reference=f"hist-{i}-{sub_id}",
                        amount=Decimal("10.00"),
                        status="approved",
                    )
                )
            _db.session.commit()
            suspicious = svc._is_suspicious_amount(sid, Decimal("500.00"))
        assert suspicious is True

    def test_create_ledger_entry_with_payment(self, app):
        from app.services.payments import PaymentGateway, get_payment_service

        svc = get_payment_service()
        sid, cid, _ = _setup_class(app)
        stu_id, _ = mk_user(app, "student", school_id=sid)
        plan_id = make_subscription_plan(app, sid, class_id=cid, price=100.0)
        sub_id = make_subscription(app, stu_id, plan_id, cid, status="active")
        from app.models.billing import ManualPayment, Subscription
        from tests.conftest import _db

        with app.app_context():
            _db.session.add(
                ManualPayment(
                    subscription_id=sub_id,
                    reference=f"led-{sub_id}",
                    amount=Decimal("100.00"),
                    status="approved",
                )
            )
            _db.session.commit()
            sub = _db.session.get(Subscription, sub_id)
            svc._create_ledger_entry(sub, Decimal("120.00"), PaymentGateway.PAYTABS)
            _db.session.expire_all()
            pay = ManualPayment.query.filter_by(subscription_id=sub_id).order_by(ManualPayment.id.desc()).first()
            assert pay.gateway == "paytabs"

    def test_cleanup_expired_intents(self, app):
        from app.services.payments import get_payment_service

        assert get_payment_service().cleanup_expired_intents() == 0


# ═════════════════════════════ email branches ═════════════════════════════


class TestEmailBranches:
    def test_send_disabled(self, app):
        with app.app_context():
            app.config["EMAIL_ENABLED"] = False
            from app.services.email import _send

            assert _send("x@y.z", "t", "<p>b</p>") is False
            app.config["EMAIL_ENABLED"] = True

    def test_send_failure_returns_false(self, app):
        with app.app_context():
            app.config["EMAIL_ENABLED"] = True
            from app.services import email as email_mod

            with patch.object(email_mod.mail, "send", side_effect=RuntimeError("smtp down")):
                assert email_mod._send("x@y.z", "t", "<p>b</p>") is False
            app.config["EMAIL_ENABLED"] = False

    def test_footer_renders(self, app):
        with app.app_context():
            from app.services.email import _footer

            html = _footer()
        assert "رسالة تلقائية" in html or "<p" in html

    def test_payment_reminder_email_disabled(self, app):
        from app.services.email import send_payment_reminder_email

        sid, cid, _ = _setup_class(app)
        stu_id, _ = mk_user(app, "student", school_id=sid)
        plan_id = make_subscription_plan(app, sid, class_id=cid, price=100.0)
        sub_id = make_subscription(app, stu_id, plan_id, cid, status="active")
        from app.models.billing import Subscription

        with app.app_context():
            sub = _db_get(Subscription, sub_id)
            with app.test_request_context("/"):
                ok = send_payment_reminder_email(sub, days_until_expiry=3)
        assert ok is False  # email disabled in tests


def _db_get(model, id_):
    from app.extensions import db

    return db.session.get(model, id_)
