"""محرّك واتساب — تحقّق توقيع، توجيه أوامر، تكرار، ميزانيات استعلامات.

كل اختبار سالب يقابل اختباراً موجب: نفس المسار بتوقيع خاطئ أو رقم غير
مربوط يجب أن يُرفض أو يردّ دون تسريب بيانات.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import UTC, date, datetime
from unittest.mock import MagicMock, patch

import pytest
from app.services.whatsapp import (
    HELP_TEXT,
    MAX_BODY_BYTES,
    META_SIGNATURE_HEADER,
    UNLINKED_REPLY,
    OutboundMessage,
    WhatsAppIdentity,
    already_handled,
    deliver_outbound,
    dispatch_outbound,
    normalize_phone,
    now_iso,
    parse_command,
    process_incoming_message,
    resolve_identity,
    route_command,
    verification_challenge_response,
    verify_inbound_signature,
    verify_twilio_signature,
)
from tests.conftest import QueryCounter

SECRET = "wa_app_secret_test"
PHONE = "+970599123456"


def _sign(body: bytes, secret: str = SECRET) -> str:
    return f"sha256={hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()}"


def _meta_payload(text: str = "#مساعدة", phone: str = PHONE, message_id: str = "wamid.1") -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "0",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messages": [
                                {
                                    "id": message_id,
                                    "from": phone,
                                    "type": "text",
                                    "text": {"body": text},
                                }
                            ]
                        },
                    }
                ],
            }
        ],
    }


# ═════════════════════════ تطبيع الأرقام ═════════════════════════
class TestNormalizePhone:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("+970599123456", "+970599123456"),
            ("970599123456", "+970599123456"),
            ("00970599123456", "+970599123456"),
            ("  +970-599-123-456  ", "+970599123456"),
            ("+1 (415) 555-2671", "+14155552671"),
        ],
    )
    def test_valid_variants_normalize_to_e164(self, raw, expected):
        assert normalize_phone(raw) == expected

    @pytest.mark.parametrize("raw", [None, "", "   ", "abc", "+12", "0", "++970", "+000000000", "00"])
    def test_invalid_inputs_rejected(self, raw):
        """رقم غير صالح ⇒ None: لا استعلام ولا ردّ على_basisرقم مشوَّه."""
        assert normalize_phone(raw) is None


# ═════════════════════════ التحقّق من التوقيع ═════════════════════════
class TestSignatureVerification:
    def test_valid_signature_accepted(self):
        body = b'{"object":"whatsapp"}'
        assert verify_inbound_signature(raw_body=body, headers={META_SIGNATURE_HEADER: _sign(body)}, secret=SECRET)

    def test_signature_without_prefix_accepted(self):
        body = b'{"a":1}'
        raw = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
        assert verify_inbound_signature(raw_body=body, headers={META_SIGNATURE_HEADER: raw}, secret=SECRET)

    def test_header_lookup_case_insensitive(self):
        body = b'{"b":2}'
        headers = {"x-hub-signature-256": _sign(body)}
        assert verify_inbound_signature(raw_body=body, headers=headers, secret=SECRET)

    def test_tampered_body_rejected(self):
        """التوقيع سليم لكن الجسم عُدِّل بعده — تلاعب بالحمولة."""
        body = b'{"user":"+970599000000"}'
        tampered = b'{"user":"+972599999999"}'
        headers = {META_SIGNATURE_HEADER: _sign(body)}
        assert verify_inbound_signature(raw_body=tampered, headers=headers, secret=SECRET) is False

    def test_wrong_secret_rejected(self):
        body = b"{}"
        headers = {META_SIGNATURE_HEADER: _sign(body, "other_secret")}
        assert verify_inbound_signature(raw_body=body, headers=headers, secret=SECRET) is False

    def test_missing_secret_fails_closed(self):
        body = b"{}"
        headers = {META_SIGNATURE_HEADER: _sign(body)}
        assert verify_inbound_signature(raw_body=body, headers=headers, secret=None) is False
        assert verify_inbound_signature(raw_body=body, headers=headers, secret="") is False

    def test_missing_header_rejected(self):
        assert verify_inbound_signature(raw_body=b"{}", headers={}, secret=SECRET) is False

    def test_empty_signature_rejected(self):
        assert verify_inbound_signature(raw_body=b"{}", headers={META_SIGNATURE_HEADER: ""}, secret=SECRET) is False

    def test_oversized_body_rejected_before_hashing(self):
        big = b"x" * (MAX_BODY_BYTES + 1)
        assert (
            verify_inbound_signature(raw_body=big, headers={META_SIGNATURE_HEADER: _sign(big)}, secret=SECRET) is False
        )

    def test_custom_header_name_supported(self):
        body = b"{}"
        sig = _sign(body)
        assert verify_inbound_signature(raw_body=body, headers={"X-Custom": sig}, secret=SECRET, header_name="X-Custom")


class TestTwilioSignature:
    def _sig(self, url: str, params: dict[str, str], token: str = "tok") -> str:
        payload = url + "".join(f"{k}{params[k]}" for k in sorted(params))
        return base64.b64encode(hmac.new(token.encode(), payload.encode(), hashlib.sha1).digest()).decode()

    def test_valid_signature_accepted(self):
        url, params = "https://example.test/hook", {"From": "+970599123456", "Body": "#حضور"}
        sig = self._sig(url, params)
        assert verify_twilio_signature(url=url, params=params, headers={"X-Twilio-Signature": sig}, token="tok")

    def test_tampered_body_rejected(self):
        url, params = "https://example.test/hook", {"From": "+970599123456", "Body": "#حضور"}
        sig = self._sig(url, params)
        tampered = {**params, "Body": "#درجات"}
        assert (
            verify_twilio_signature(url=url, params=tampered, headers={"X-Twilio-Signature": sig}, token="tok") is False
        )

    def test_missing_token_and_header_fail_closed(self):
        url, params = "https://example.test/hook", {"A": "1"}
        assert verify_twilio_signature(url=url, params=params, headers={}, token=None) is False
        assert verify_twilio_signature(url=url, params=params, headers={}, token="tok") is False


class TestVerificationChallenge:
    def test_valid_challenge_echoed(self, monkeypatch):
        monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", "tok123")
        assert verification_challenge_response(mode="subscribe", verify_token="tok123", challenge="ch99") == "ch99"

    def test_wrong_token_rejected(self, monkeypatch):
        monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", "tok123")
        assert verification_challenge_response(mode="subscribe", verify_token="bad", challenge="c") is None

    def test_missing_env_token_rejected(self, monkeypatch):
        monkeypatch.delenv("WHATSAPP_VERIFY_TOKEN", raising=False)
        assert verification_challenge_response(mode="subscribe", verify_token="x", challenge="c") is None

    def test_non_subscribe_mode_returns_none(self, monkeypatch):
        monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", "tok123")
        assert verification_challenge_response(mode="unsubscribe", verify_token="tok123", challenge="c") is None


# ═════════════════════════ الهوية ═════════════════════════
class TestIdentityResolution:
    def _link(self, app, *, phone: str = PHONE, active: bool = True, role: str = "parent"):
        from app.extensions import db
        from app.models.user import UserRole
        from app.models.whatsapp import WhatsAppLink
        from tests.conftest import make_school, make_user

        school_id = make_school(app)
        user_id = make_user(app, role=role, school_id=school_id)
        with app.app_context():
            db.session.execute(db.text("SELECT set_config('app.is_super_admin','1',false)"))
            db.session.add(
                WhatsAppLink(
                    user_id=user_id,
                    school_id=school_id,
                    phone=phone,
                    verified_at=datetime.now(UTC),
                    is_active=active,
                )
            )
            db.session.commit()
        return school_id, user_id, UserRole(role)

    def test_linked_phone_resolves(self, app):
        _school, user_id, role = self._link(app)
        with app.app_context():
            identity = resolve_identity(PHONE)
            assert identity is not None
            assert identity.user_id == user_id
            assert identity.phone == PHONE
            assert identity.role == role.value

    def test_alternate_format_resolves_same_account(self, app):
        _school, user_id, _role = self._link(app)
        with app.app_context():
            assert resolve_identity("00970599123456").user_id == user_id

    def test_unlinked_phone_returns_none(self, app):
        self._link(app)
        with app.app_context():
            assert resolve_identity("+970599999999") is None

    def test_inactive_link_returns_none(self, app):
        self._link(app, active=False)
        with app.app_context():
            assert resolve_identity(PHONE) is None

    def test_invalid_phone_returns_none_without_query(self, app):
        self._link(app)
        with app.app_context():
            with QueryCounter(_engine()) as qc:
                assert resolve_identity("not-a-number") is None
            assert qc.count == 0, "رقم غير صالح لا يستهلك استعلاماً"

    def test_resolution_is_single_query(self, app):
        """O(1): ربط الرقم استعلام واحد مهما زاد عدد الحسابات."""
        self._link(app)
        for extra in range(5):
            self._link(app, phone=f"+97059900000{extra}")
        with app.app_context():
            with QueryCounter(_engine()) as qc:
                resolve_identity(PHONE)
            assert qc.count <= 1, f"resolve_identity استهلكت {qc.count} استعلامات (السقف 1)"


def _engine():
    from app.extensions import db

    return db.engine


# ═════════════════════════ الأوامر ═════════════════════════
class TestCommandParsing:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("#حضور", ("حضور", [])),
            ("#درجات alice", ("درجات", ["alice"])),
            ("#Help", ("help", [])),
            ("  #اشتراك  ", ("اشتراك", [])),
        ],
    )
    def test_valid_commands_parsed(self, text, expected):
        assert parse_command(text) == expected

    @pytest.mark.parametrize("text", [None, "", "   ", "حضور", "#", "  ", "no hash here"])
    def test_non_commands_return_none(self, text):
        assert parse_command(text) is None


class TestCommandRouting:
    def _identity(self, role="parent") -> WhatsAppIdentity:
        return WhatsAppIdentity(user_id=1, school_id=1, phone=PHONE, role=role)

    def test_unknown_command_returns_help(self):
        reply = route_command("#غير_معرف", self._identity())
        assert "غير معروف" in reply and HELP_TEXT.splitlines()[0] in reply

    def test_plain_text_gets_guidance(self):
        assert "مساعدة" in route_command("مرحبا", self._identity())

    def test_unlinked_number_gets_no_data(self):
        """fail-closed: لا أمر يُنفَّذ بلا هوية."""
        assert route_command("#حضور", None) == UNLINKED_REPLY
        assert route_command("#درجات", None) == UNLINKED_REPLY

    def test_help_command_works_for_linked_user(self):
        assert route_command("#مساعدة", self._identity()) == HELP_TEXT


class TestCommandHandlers:
    def _parent_with_child(self, app, *, status: str = "absent"):
        from app.extensions import db
        from app.models.attendance import Attendance
        from app.models.family import FamilyLink
        from tests.conftest import (
            make_class,
            make_class_member,
            make_grade,
            make_school,
            make_subject,
            make_user,
        )

        school_id = make_school(app)
        grade_id = make_grade(app, school_id)
        subject_id = make_subject(app)
        class_id = make_class(app, school_id, grade_id, subject_id)
        parent_id = make_user(app, role="parent", school_id=school_id)
        child_id = make_user(app, role="student", school_id=school_id)
        make_class_member(app, class_id, child_id)
        with app.app_context():
            db.session.execute(db.text("SELECT set_config('app.is_super_admin','1',false)"))
            db.session.add(FamilyLink(parent_id=parent_id, student_id=child_id, status="active"))
            db.session.add(Attendance(class_id=class_id, student_id=child_id, date=date.today(), status=status))
            db.session.commit()
        return WhatsAppIdentity(user_id=parent_id, school_id=school_id, phone=PHONE, role="parent"), child_id

    def test_attendance_command_returns_status(self, app):
        identity, _child = self._parent_with_child(app, status="absent")
        with app.app_context():
            assert "غائب" in route_command("#حضور", identity)

    def test_attendance_command_is_single_query(self, app):
        identity, _child = self._parent_with_child(app)
        with app.app_context():
            with QueryCounter(_engine()) as qc:
                route_command("#حضور", identity)
            assert qc.count <= 3, f"#حضور استهلك {qc.count} استعلامات (أبناء+حضور)"

    def test_attendance_without_records(self, app):
        identity = WhatsAppIdentity(user_id=999999, school_id=1, phone=PHONE, role="parent")
        with app.app_context():
            assert "لم يُسجَّل" in route_command("#حضور", identity) or "لا يوجد" in route_command("#حضور", identity)

    def test_parent_without_children(self, app):
        from tests.conftest import make_school, make_user

        school_id = make_school(app)
        parent_id = make_user(app, role="parent", school_id=school_id)
        identity = WhatsAppIdentity(user_id=parent_id, school_id=school_id, phone=PHONE, role="parent")
        with app.app_context():
            assert route_command("#درجات", identity) == "لا يوجد طلاب مرتبطون بحسابك."

    def test_grades_command_lists_marks(self, app):
        from app.extensions import db
        from app.models.gradebook import GradeCategory, GradeEntry, GradeItem
        from tests.conftest import (
            make_class,
            make_class_member,
            make_grade,
            make_school,
            make_subject,
            make_user,
        )

        school_id = make_school(app)
        grade_id = make_grade(app, school_id)
        class_id = make_class(app, school_id, grade_id, make_subject(app))
        parent_id = make_user(app, role="parent", school_id=school_id)
        child_id = make_user(app, role="student", school_id=school_id)
        make_class_member(app, class_id, child_id)
        with app.app_context():
            db.session.execute(db.text("SELECT set_config('app.is_super_admin','1',false)"))
            from app.models.family import FamilyLink

            db.session.add(FamilyLink(parent_id=parent_id, student_id=child_id, status="active"))
            cat = GradeCategory(class_id=class_id, name="قسم", weight=1)
            db.session.add(cat)
            db.session.flush()
            item = GradeItem(class_id=class_id, category_id=cat.id, title="بند", max_mark=100)
            db.session.add(item)
            db.session.flush()
            db.session.add(GradeEntry(student_id=child_id, grade_item_id=item.id, mark=88))
            db.session.commit()

        identity = WhatsAppIdentity(user_id=parent_id, school_id=school_id, phone=PHONE, role="parent")
        with app.app_context():
            assert "88" in route_command("#درجات", identity)

    def test_subscription_command_reports_status(self, app):
        from app.extensions import db
        from app.models.billing import Subscription, SubscriptionPlan
        from tests.conftest import make_class, make_grade, make_school, make_subject, make_user

        school_id = make_school(app)
        class_id = make_class(app, school_id, make_grade(app, school_id), make_subject(app))
        user_id = make_user(app, role="student", school_id=school_id)
        with app.app_context():
            db.session.execute(db.text("SELECT set_config('app.is_super_admin','1',false)"))
            plan = SubscriptionPlan(school_id=school_id, name="خطة", plan="annual", price=100, currency="ILS")
            db.session.add(plan)
            db.session.flush()
            db.session.add(
                Subscription(
                    user_id=user_id,
                    plan_id=plan.id,
                    class_id=class_id,
                    price=100,
                    currency="ILS",
                    status="active",
                    end_at=datetime.now(UTC),
                )
            )
            db.session.commit()

        identity = WhatsAppIdentity(user_id=user_id, school_id=school_id, phone=PHONE, role="student")
        with app.app_context():
            reply = route_command("#اشتراك", identity)
            assert "active" in reply

    def test_subscription_command_without_subscription(self, app):
        from tests.conftest import make_school, make_user

        school_id = make_school(app)
        user_id = make_user(app, role="student", school_id=school_id)
        identity = WhatsAppIdentity(user_id=user_id, school_id=school_id, phone=PHONE, role="student")
        with app.app_context():
            assert route_command("#اشتراك", identity) == "لا يوجد اشتراك مرتبط بحسابك."


# ═════════════════════════ التكرار ═════════════════════════
class TestIdempotency:
    def test_first_message_not_seen_before_processing(self, app):
        with app.app_context():
            assert already_handled("wamid.new") is False

    def test_message_marked_then_detected(self, app):
        from app.core.db import tx
        from app.extensions import db
        from app.services.whatsapp import mark_handled

        with app.app_context():
            db.session.execute(db.text("SELECT set_config('app.is_super_admin','1',false)"))

            def _add():
                mark_handled("wamid.dup", {"phone_tail": "3456"})

            tx(_add)
            assert already_handled("wamid.dup") is True
            db.session.rollback()

    def test_replay_is_noop_and_does_not_dispatch(self, app):
        from app.core.db import tx
        from app.extensions import db
        from app.services.whatsapp import mark_handled

        with app.app_context():
            db.session.execute(db.text("SELECT set_config('app.is_super_admin','1',false)"))

            def _add():
                mark_handled("wamid.replay", {"phone_tail": "3456"})

            tx(_add)
            with patch("app.services.whatsapp.dispatch_outbound") as dispatch:
                result = process_incoming_message(message_id="wamid.replay", phone=PHONE, text="#حضور")
            db.session.rollback()
        assert result["status"] == "duplicate"
        assert result["reply"] == ""
        assert dispatch.called is False, "التكرار أرسل رسالة ثانية"

    def test_message_without_id_is_rejected(self, app):
        with patch("app.services.whatsapp.dispatch_outbound") as dispatch:
            result = process_incoming_message(message_id="", phone=PHONE, text="#حضور")
        assert result["status"] == "unlinked"
        assert result["reply"] == UNLINKED_REPLY
        assert dispatch.called is False


class TestProcessIncoming:
    def test_linked_user_gets_reply_and_dispatch_is_queued(self, app):
        from app.extensions import db
        from app.models.whatsapp import WhatsAppLink
        from tests.conftest import make_school, make_user

        school_id = make_school(app)
        user_id = make_user(app, role="student", school_id=school_id)
        with app.app_context():
            db.session.execute(db.text("SELECT set_config('app.is_super_admin','1',false)"))
            db.session.add(
                WhatsAppLink(
                    user_id=user_id,
                    school_id=school_id,
                    phone=PHONE,
                    verified_at=datetime.now(UTC),
                    is_active=True,
                )
            )
            db.session.commit()
            with patch("app.services.whatsapp.dispatch_outbound") as dispatch:
                result = process_incoming_message(message_id="wamid.p1", phone=PHONE, text="#مساعدة")
            db.session.rollback()
        assert result["status"] == "processed"
        assert result["reply"] == HELP_TEXT
        assert dispatch.call_count == 1
        queued: OutboundMessage = dispatch.call_args[0][0]
        assert queued.to == PHONE
        assert queued.idempotency_key == "wamid.p1"

    def test_unlinked_sender_gets_no_data_but_is_acknowledged(self, app):
        from app.extensions import db
        from tests.conftest import make_school, make_user

        make_school(app)
        make_user(app, role="student")
        with app.app_context():
            db.session.execute(db.text("SELECT set_config('app.is_super_admin','1',false)"))
            with patch("app.services.whatsapp.dispatch_outbound") as dispatch:
                result = process_incoming_message(message_id="wamid.p2", phone=PHONE, text="#درجات")
            db.session.rollback()
        assert result["status"] == "unlinked"
        assert result["reply"] == UNLINKED_REPLY
        assert dispatch.called is True

    def test_processing_is_bounded_queries(self, app):
        from app.extensions import db
        from app.models.whatsapp import WhatsAppLink
        from tests.conftest import make_school, make_user

        school_id = make_school(app)
        user_id = make_user(app, role="student", school_id=school_id)
        with app.app_context():
            db.session.execute(db.text("SELECT set_config('app.is_super_admin','1',false)"))
            db.session.add(
                WhatsAppLink(
                    user_id=user_id,
                    school_id=school_id,
                    phone=PHONE,
                    verified_at=datetime.now(UTC),
                    is_active=True,
                )
            )
            db.session.commit()
            with patch("app.services.whatsapp.dispatch_outbound"):
                with QueryCounter(db.engine) as qc:
                    process_incoming_message(message_id="wamid.budget", phone=PHONE, text="#اشتراك")
            db.session.rollback()
        assert qc.count <= 4, f"معالجة الرسالة استهلكت {qc.count} استعلامات (السقف 4)"


# ═════════════════════════ الإرسال الصادر ═════════════════════════
class TestOutboundDispatch:
    def test_delivery_skipped_when_unconfigured(self, monkeypatch):
        monkeypatch.delenv("WHATSAPP_ACCESS_TOKEN", raising=False)
        monkeypatch.delenv("WHATSAPP_PHONE_NUMBER_ID", raising=False)
        assert deliver_outbound(OutboundMessage(to=PHONE, body="hi", idempotency_key="k")) is False

    def test_delivery_success(self, monkeypatch):
        monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "tok")
        monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "123")
        response = MagicMock(status_code=200)
        with patch("requests.post", return_value=response) as post:
            assert deliver_outbound(OutboundMessage(to=PHONE, body="hi", idempotency_key="k")) is True
        payload = post.call_args.kwargs["json"]
        assert payload["messaging_product"] == "whatsapp"
        assert payload["to"] == PHONE
        assert payload["text"]["body"] == "hi"

    def test_delivery_rejected_status(self, monkeypatch):
        monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "tok")
        monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "123")
        with patch("requests.post", return_value=MagicMock(status_code=401)):
            assert deliver_outbound(OutboundMessage(to=PHONE, body="hi", idempotency_key="k")) is False

    def test_delivery_network_error_swallowed(self, monkeypatch):
        monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "tok")
        monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "123")
        with patch("requests.post", side_effect=RuntimeError("boom")):
            assert deliver_outbound(OutboundMessage(to=PHONE, body="hi", idempotency_key="k")) is False

    def test_long_body_is_truncated(self, monkeypatch):
        monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "tok")
        monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "123")
        with patch("requests.post", return_value=MagicMock(status_code=200)) as post:
            deliver_outbound(OutboundMessage(to=PHONE, body="x" * 5000, idempotency_key="k"))
        assert len(post.call_args.kwargs["json"]["text"]["body"]) == 1000

    def test_dispatch_prefers_celery_when_available(self):
        task = MagicMock()
        with patch("app.services.whatsapp._celery_task", return_value=task):
            dispatch_outbound(OutboundMessage(to=PHONE, body="hi", idempotency_key="k"))
        task.delay.assert_called_once_with(PHONE, "hi", "k")

    def test_dispatch_falls_back_to_pool(self):
        pool = MagicMock()
        with (
            patch("app.services.whatsapp._celery_task", return_value=None),
            patch("app.services.whatsapp._OUTBOUND_POOL", pool),
        ):
            dispatch_outbound(OutboundMessage(to=PHONE, body="hi", idempotency_key="k"))
        assert pool.submit.called is True

    def test_celery_failure_falls_back_to_pool(self):
        pool = MagicMock()
        task = MagicMock()
        task.delay.side_effect = RuntimeError("broker down")
        with (
            patch("app.services.whatsapp._celery_task", return_value=task),
            patch("app.services.whatsapp._OUTBOUND_POOL", pool),
        ):
            dispatch_outbound(OutboundMessage(to=PHONE, body="hi", idempotency_key="k"))
        assert pool.submit.called is True

    def test_celery_task_lookup_returns_none_without_celery(self):
        from app.services.whatsapp import _celery_task

        # celery غير مثبّت في بيئة الاختبار عمداً
        with patch.dict("sys.modules", {"app.tasks.notifications": None}):
            assert _celery_task() is None


def test_now_iso_is_utc_isoformat():
    stamp = now_iso()
    assert stamp.endswith("+00:00") or stamp.endswith("Z")
    datetime.fromisoformat(stamp)


# ═════════════════════════ المسارات ═════════════════════════
class TestWhatsAppRoutes:
    def _client(self, app, secret: str = SECRET):
        app.config["WHATSAPP_APP_SECRET"] = secret
        return app.test_client()

    def test_challenge_echoed_when_token_matches(self, app, monkeypatch):
        monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", "tok123")
        client = self._client(app)
        resp = client.get("/api/whatsapp/webhook?hub.mode=subscribe&hub.verify_token=tok123&hub.challenge=ch1")
        assert resp.status_code == 200
        assert resp.get_data(as_text=True) == "ch1"

    def test_challenge_rejected_with_wrong_token(self, app, monkeypatch):
        monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", "tok123")
        client = self._client(app)
        resp = client.get("/api/whatsapp/webhook?hub.mode=subscribe&hub.verify_token=bad&hub.challenge=ch1")
        assert resp.status_code == 403

    def test_post_without_signature_rejected(self, app):
        client = self._client(app)
        resp = client.post("/api/whatsapp/webhook", json=_meta_payload())
        assert resp.status_code == 401
        assert "traceback" not in resp.get_data(as_text=True).lower()

    def test_post_with_bad_signature_rejected(self, app):
        client = self._client(app)
        resp = client.post(
            "/api/whatsapp/webhook",
            data=json.dumps(_meta_payload()),
            content_type="application/json",
            headers={META_SIGNATURE_HEADER: "sha256=deadbeef"},
        )
        assert resp.status_code == 401

    def test_post_without_configured_secret_rejected(self, app):
        app.config["WHATSAPP_APP_SECRET"] = ""
        client = app.test_client()
        body = json.dumps(_meta_payload())
        resp = client.post(
            "/api/whatsapp/webhook",
            data=body,
            content_type="application/json",
            headers={META_SIGNATURE_HEADER: _sign(body.encode())},
        )
        assert resp.status_code == 401

    def test_signed_event_is_processed(self, app):
        client = self._client(app)
        body = json.dumps(_meta_payload(text="#مساعدة")).encode()
        with patch("app.services.whatsapp.dispatch_outbound"):
            resp = client.post(
                "/api/whatsapp/webhook",
                data=body,
                content_type="application/json",
                headers={META_SIGNATURE_HEADER: _sign(body)},
            )
        assert resp.status_code == 200
        assert resp.get_json()["handled"] == 1

    def test_signed_replay_is_acknowledged_once(self, app):
        client = self._client(app)
        body = json.dumps(_meta_payload(message_id="wamid.replay2")).encode()
        headers = {META_SIGNATURE_HEADER: _sign(body)}
        with patch("app.services.whatsapp.dispatch_outbound") as dispatch:
            first = client.post("/api/whatsapp/webhook", data=body, content_type="application/json", headers=headers)
            second = client.post("/api/whatsapp/webhook", data=body, content_type="application/json", headers=headers)
        assert first.status_code == 200 and second.status_code == 200
        assert dispatch.call_count == 1, "التكرار أرسل رداً ثانياً"

    def test_oversized_body_rejected(self, app):
        client = self._client(app)
        body = b"x" * (MAX_BODY_BYTES + 10)
        resp = client.post(
            "/api/whatsapp/webhook",
            data=body,
            content_type="application/json",
            headers={META_SIGNATURE_HEADER: _sign(body)},
        )
        assert resp.status_code == 413

    def test_response_is_fast_under_200ms(self, app):
        """الاستجابة لا تنتظر الإرسال الصادر — أقل من 200ms."""
        client = self._client(app)
        body = json.dumps(_meta_payload(message_id="wamid.fast")).encode()
        headers = {META_SIGNATURE_HEADER: _sign(body)}
        with patch("app.services.whatsapp.dispatch_outbound"):
            # تسخين: أول طلب يمرّ بـ create_app/ترجمة لا زمن المقاس
            client.post("/api/whatsapp/webhook", data=body, content_type="application/json", headers=headers)
            second_body = json.dumps(_meta_payload(message_id="wamid.fast2")).encode()
            second_headers = {META_SIGNATURE_HEADER: _sign(second_body)}
            start = datetime.now(UTC)
            resp = client.post(
                "/api/whatsapp/webhook",
                data=second_body,
                content_type="application/json",
                headers=second_headers,
            )
            elapsed_ms = (datetime.now(UTC) - start).total_seconds() * 1000
        assert resp.status_code == 200
        assert elapsed_ms < 200, f"الاستجابة استغرقت {elapsed_ms:.0f}ms (الحد 200ms)"

    def test_malformed_payload_is_handled_gracefully(self, app):
        """JSON تالف لكن توقيعه صحيح ⇒ 200 بلا معالجة ولا انهيار."""
        client = self._client(app)
        body = b"{not-json"
        resp = client.post(
            "/api/whatsapp/webhook",
            data=body,
            content_type="application/json",
            headers={META_SIGNATURE_HEADER: _sign(body)},
        )
        assert resp.status_code == 200
        assert resp.get_json()["handled"] == 0

    def test_payload_with_garbage_types_is_ignored(self, app):
        client = self._client(app)
        payload = {"entry": ["x", {"changes": "y"}, {"changes": [{"value": "z"}]}], "object": 1}
        body = json.dumps(payload).encode()
        resp = client.post(
            "/api/whatsapp/webhook",
            data=body,
            content_type="application/json",
            headers={META_SIGNATURE_HEADER: _sign(body)},
        )
        assert resp.status_code == 200
        assert resp.get_json()["handled"] == 0

    def test_status_messages_without_text_are_counted(self, app):
        client = self._client(app)
        payload = _meta_payload()
        payload["entry"][0]["changes"][0]["value"]["messages"][0] = {"id": "wamid.status", "from": PHONE}
        body = json.dumps(payload).encode()
        with patch("app.services.whatsapp.dispatch_outbound"):
            resp = client.post(
                "/api/whatsapp/webhook",
                data=body,
                content_type="application/json",
                headers={META_SIGNATURE_HEADER: _sign(body)},
            )
        assert resp.get_json()["handled"] == 1

    @pytest.mark.parametrize(
        ("message", "expected_text"),
        [
            ({"button": {"text": "#حضور"}}, "#حضور"),
            ({"interactive": {"button_reply": {"title": "#درجات"}}}, "#درجات"),
            ({"interactive": {"list_reply": {"title": "#اشتراك"}}}, "#اشتراك"),
            ({"text": {"body": "#مساعدة"}}, "#مساعدة"),
            ({"text": {"non_object": 1}}, None),
            ({"button": {}}, None),
            ({"interactive": {}}, None),
            ({}, None),
        ],
    )
    def test_message_text_extraction_covers_all_types(self, app, message, expected_text):
        from app.modules.whatsapp.routes import _message_text

        with app.app_context():
            assert _message_text(message) == expected_text


class TestLegacyAliasRoute:
    """المسار القديم صار تفويضاً — لا يقبل حركة بلا توقيع."""

    def test_legacy_rejects_unsigned(self, app):
        client = app.test_client()
        resp = client.post("/api/payments/webhook/whatsapp", json=_meta_payload())
        assert resp.status_code == 401

    def test_legacy_accepts_signed(self, app):
        app.config["WHATSAPP_APP_SECRET"] = SECRET
        client = app.test_client()
        body = json.dumps(_meta_payload(message_id="wamid.legacy")).encode()
        with patch("app.services.whatsapp.dispatch_outbound"):
            resp = client.post(
                "/api/payments/webhook/whatsapp",
                data=body,
                content_type="application/json",
                headers={META_SIGNATURE_HEADER: _sign(body)},
            )
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "processed"

    def test_legacy_challenge_flow(self, app, monkeypatch):
        monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", "tok123")
        client = app.test_client()
        resp = client.post("/api/payments/webhook/whatsapp?hub.verify_token=tok123&hub.challenge=ch99")
        assert resp.status_code == 200
        assert resp.get_data(as_text=True) == "ch99"

    def test_legacy_challenge_wrong_token(self, app, monkeypatch):
        monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", "tok123")
        client = app.test_client()
        resp = client.post("/api/payments/webhook/whatsapp?hub.verify_token=wrong&hub.challenge=c1")
        assert resp.status_code == 403


class TestStudentIdentityPaths:
    """طالب (لا ولي أمر): المعرّف هو نفسه، فيقرأ صفوفه فقط."""

    def _student(self, app):
        from tests.conftest import make_school, make_user

        school_id = make_school(app)
        user_id = make_user(app, role="student", school_id=school_id)
        return WhatsAppIdentity(user_id=user_id, school_id=school_id, phone=PHONE, role="student")

    def test_children_ids_for_student_is_self(self, app):
        from app.services.whatsapp import _children_ids

        identity = self._student(app)
        with app.app_context():
            assert _children_ids(identity) == [identity.user_id]

    def test_attendance_command_without_records(self, app):
        identity = self._student(app)
        with app.app_context():
            assert route_command("#حضور", identity) == "لم يُسجَّل حضور اليوم بعد."

    def test_grades_command_without_entries(self, app):
        identity = self._student(app)
        with app.app_context():
            assert route_command("#درجات", identity) == "لا توجد درجات مسجّلة بعد."

    def test_attendance_command_lists_own_status(self, app):
        from app.extensions import db
        from tests.conftest import (
            make_class,
            make_class_member,
            make_grade,
            make_school,
            make_subject,
            make_user,
        )

        school_id = make_school(app)
        class_id = make_class(app, school_id, make_grade(app, school_id), make_subject(app))
        user_id = make_user(app, role="student", school_id=school_id)
        make_class_member(app, class_id, user_id)
        with app.app_context():
            db.session.execute(db.text("SELECT set_config('app.is_super_admin','1',false)"))
            from app.models.attendance import Attendance

            db.session.add(Attendance(class_id=class_id, student_id=user_id, date=date.today(), status="late"))
            db.session.commit()
            identity = WhatsAppIdentity(user_id=user_id, school_id=school_id, phone=PHONE, role="student")
            assert "متأخر" in route_command("#حضور", identity)
            db.session.rollback()


class TestCeleryTaskResolution:
    """مسار Celery يعمل بمهمة مُحقونة — والمحرّك لا يعتمد على الوسيط."""

    def test_celery_task_returned_when_module_available(self):
        import types

        from app.services.whatsapp import _celery_task

        fake = types.ModuleType("app.tasks.notifications")
        fake.send_whatsapp_task = MagicMock()  # type: ignore[attr-defined]
        with patch.dict("sys.modules", {"app.tasks.notifications": fake}):
            assert _celery_task() is fake.send_whatsapp_task


class TestMalformedMessageEntries:
    """حمولة تحتوي أنواعاً غير متوقعة — تُتجاهل ولا تُسقط الطلب."""

    def test_non_dict_message_entries_ignored(self, app):
        from app.modules.whatsapp.routes import _handle_events

        payload = {"entry": [{"changes": [{"value": {"messages": ["x", 5, None]}}]}]}
        with app.app_context():
            assert _handle_events(payload) == 0

    def test_entry_without_changes_ignored(self, app):
        from app.modules.whatsapp.routes import _handle_events

        with app.app_context():
            assert _handle_events({"entry": [{"id": "1"}, {"changes": [{}]}]}) == 0
