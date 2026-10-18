"""Hotfix regression tests — audit defects D-1 … D-7 + P7 wallet↔tutoring wiring.

Each test cites the defect ID it pins down:

D-1  ``PaymentService._create_ledger_entry`` writes an immutable
     ``WalletTransaction`` (source NULL = external inflow) and never
     mutates a historical ``ManualPayment``.
D-2  Outbound gateway amounts are quantized to 2 dp: Stripe cents,
     PayTabs decimal-string.
D-4  ``review_payout`` rejects a second review on a non-pending payout
     (state guard inside the tx), instead of last-writer-wins.
D-5  ``_flag_for_review`` only notifies admins linked to the
     subscription's school (plus super_admins).
D-7  wallet deposit/transfer pre-checks ``UserRoleLink`` tenancy.
P7   completing a tutoring session with a funded tutor wallet produces
     the dual-leg ledger: inflow credit + platform commission debit,
     with matching idempotency keys (re-run does not double-pollute).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from tests.conftest import (
    make_grade,
    make_payment,
    make_school,
    make_subject,
    make_subscription,
    make_subscription_plan,
    make_user,
)

_PASSWORD = "TestPass123!"


def _class(app, school_id):
    """make_class needs grade_id + subject_id; build one of each."""
    from tests.conftest import make_class

    grade = make_grade(app, school_id)
    subject = make_subject(app)
    return make_class(app, school_id, grade, subject)


def _wallet_id(app, school_id, user_id, currency="ILS"):
    from app.services.wallet_service import get_or_create_wallet

    with app.app_context():
        w, err = get_or_create_wallet(school_id, user_id, currency=currency)
        assert err is None
        return w.id


def _fund(app, wallet_id: int, amount: Decimal) -> None:
    from app.extensions import db
    from app.models.wallet import Wallet

    with app.app_context():
        w = db.session.get(Wallet, wallet_id)
        assert w is not None
        w.balance = amount
        db.session.commit()


# ════════════════════════════════════════════════════════════════════
# D-1 — immutable ledger entry, no historical overwrite
# ════════════════════════════════════════════════════════════════════
class TestD1LedgerEntry:
    def test_ledger_entry_is_immutable_wallet_transaction(self, app):
        """A gateway payment records a NEW ledger row: the pre-existing
        approved ManualPayment keeps its amount (no historical rewrite)."""
        from app.extensions import db
        from app.models.billing import ManualPayment
        from app.models.wallet import WalletTransaction
        from app.services.payments import PaymentGateway, PaymentService

        sid = make_school(app)
        with app.app_context():
            class_id = _class(app, sid)
            plan = make_subscription_plan(app, school_id=sid, class_id=class_id)
            tutor = make_user(app, role="teacher", school_id=sid)
            sub = make_subscription(app, user_id=tutor, plan_id=plan, class_id=class_id)
            # pre-existing approved manual payment with a DIFFERENT historical amount
            mp = make_payment(app, subscription_id=sub, amount=Decimal("10.00"), status="approved")
            db.session.get(ManualPayment, mp).amount = Decimal("10.00")
            db.session.commit()

            svc = PaymentService()
            from app.models.billing import Subscription

            sub_obj = db.session.get(Subscription, sub)
            svc._create_ledger_entry(sub_obj, Decimal("250.00"), PaymentGateway.STRIPE)

            entry = (
                WalletTransaction.query.filter_by(reference_type="subscription", reference_id=sub)
                .order_by(WalletTransaction.id.desc())
                .first()
            )
            assert entry is not None, "D1: ledger WalletTransaction row must exist"
            assert entry.amount == Decimal("250.00")
            assert entry.transaction_type == "subscription_credit"
            assert entry.source_wallet_id is None  # external inflow representation

            # the historical ManualPayment is untouched
            historical = db.session.get(ManualPayment, mp)
            assert historical.amount == Decimal("10.00"), "D1: approved manual payment must never be rewritten"

    def test_ledger_entry_idempotent_per_subscription_amount_gateway(self, app):
        """Re-running the same successful webhook does not create duplicate ledger rows."""
        from app.extensions import db
        from app.models.billing import Subscription
        from app.models.wallet import WalletTransaction
        from app.services.payments import PaymentGateway, PaymentService

        sid = make_school(app)
        with app.app_context():
            class_id = _class(app, sid)
            plan = make_subscription_plan(app, school_id=sid, class_id=class_id)
            uid = make_user(app, role="student", school_id=sid)
            sub = make_subscription(app, user_id=uid, plan_id=plan, class_id=class_id)

            svc = PaymentService()
            sub_obj = db.session.get(Subscription, sub)
            svc._create_ledger_entry(sub_obj, Decimal("100.00"), PaymentGateway.STRIPE)
            svc._create_ledger_entry(sub_obj, Decimal("100.00"), PaymentGateway.STRIPE)

            rows = (
                WalletTransaction.query.filter_by(reference_type="subscription", reference_id=sub)
                .order_by(WalletTransaction.id.asc())
                .all()
            )
            assert len(rows) == 1, f"D1: idempotency key must dedupe, got {len(rows)} rows"


# ════════════════════════════════════════════════════════════════════
# D-2 — outbound gateway quantization
# ════════════════════════════════════════════════════════════════════
class TestD2GatewayQuantization:
    def test_gateway_units_rounds_half_up_no_float_drift(self):
        from app.services.payments import _gateway_units, _money

        assert _money(Decimal("19.985")) == Decimal("19.99")  # ROUND_HALF_UP, not banker's
        assert _gateway_units(Decimal("19.985")) == 1999
        assert _gateway_units(Decimal("10.00")) == 1000
        # the old bug: int(Decimal('19.985') * 100) == 1998 (truncation after float widening)
        assert _gateway_units(Decimal("10.10")) == 1010

    def test_stripe_intent_amount_is_quantized_int(self, app):
        """Stripe receives integer cents derived from quantized Decimal."""
        from app.services.payments import PaymentGateway, StripeGateway

        gw = StripeGateway.__new__(StripeGateway)  # skip stripe SDK import
        gw.config = {}

        captured = {}

        fake_intent = type("FakeIntent", (), {})()
        fake_intent.id = "pi_x"
        fake_intent.client_secret = "cs_x"

        def fake_create(**kwargs):
            captured.update(kwargs)
            return fake_intent

        fake_sdk = type("FakeSdk", (), {})()
        fake_sdk.PaymentIntent = type("FakePI", (), {"create": staticmethod(fake_create)})
        gw.stripe = fake_sdk
        gw.webhook_secret = "whsec"

        intent = gw.create_payment_intent(Decimal("19.985"), "ils", user_id=1)
        assert captured["amount"] == 1999, "D2: Stripe cents must be ROUND_HALF_UP quantized"
        assert intent.amount == Decimal("19.99"), "D2: echoed intent amount must be quantized too"
        assert intent.gateway == PaymentGateway.STRIPE

    def test_paytabs_payload_amount_is_quantized_number(self, app):
        """PayTabs receives the 2-dp quantized value as a JSON number."""
        from app.services.payments import PayTabsGateway

        gw = PayTabsGateway({"profile_id": "p", "server_key": "k", "webhook_secret": "s"})

        captured = {}

        class FakeResp:
            status_code = 200

            def json(self):
                return {"tran_ref": "T1"}

        def fake_post(url, json=None, headers=None, timeout=None):
            captured.update(json or {})
            return FakeResp()

        with patch_requests_post(fake_post):
            gw.create_payment_intent(Decimal("19.985"), "ILS", user_id=1)

        assert captured["cart_amount"] == 19.99, "D2: PayTabs must get the quantized amount (19.985 → 19.99)"
        assert not isinstance(captured["cart_amount"], str), "D2: cart_amount stays a number"


def patch_requests_post(fake):
    """Patch requests.post only inside the payments module's namespace."""
    from unittest.mock import patch

    return patch("requests.post", side_effect=fake)


# ════════════════════════════════════════════════════════════════════
# D-4 — payout review state guard
# ════════════════════════════════════════════════════════════════════
class TestD4PayoutStateGuard:
    def test_second_review_is_rejected_with_flash(self, app):
        """Approving a payout twice leaves the first review intact and flashes a guard message."""
        sid = make_school(app)
        tutor = make_user(app, role="teacher", school_id=sid)

        with app.app_context():
            from app.extensions import db
            from app.models.tutoring import TutorPayout

            payout = TutorPayout(tutor_id=tutor, amount=Decimal("500.00"), status="pending")
            db.session.add(payout)
            db.session.commit()
            pid = payout.id

        client = app.test_client()
        email = f"d4-{uuid.uuid4().hex[:8]}@test.com"
        make_user(app, role="super_admin", school_id=None, email=email)
        res = client.post("/auth/login", data={"email": email, "password": _PASSWORD}, follow_redirects=False)
        assert res.status_code == 302

        r1 = client.post(f"/admin/payouts/{pid}/approve", follow_redirects=True)
        assert r1.status_code == 200
        # immediate double-review: guard must trigger
        r2 = client.post(f"/admin/payouts/{pid}/reject", data={"note": "x"}, follow_redirects=True)
        assert r2.status_code == 200
        assert "مسبقاً" in r2.get_data(as_text=True), "D4: second review must flash already-reviewed"

        with app.app_context():
            db.session.expire_all()
            from app.models.tutoring import TutorPayout

            p = db.session.get(TutorPayout, pid)
            assert p.status == "approved", "D4: reject must not overturn an approved payout"
            assert p.note != "x", "D4: reject must not write a note after approval"


# ════════════════════════════════════════════════════════════════════
# D-5 — tenant-scoped admin fan-out
# ════════════════════════════════════════════════════════════════════
class TestD5TenantScopedFanout:
    def test_only_school_linked_admins_notified(self, app, monkeypatch):
        sid_a = make_school(app)
        sid_b = make_school(app)
        with app.app_context():
            from app.extensions import db
            from app.services.payments import PaymentService

            class_id = _class(app, sid_a)
            plan = make_subscription_plan(app, school_id=sid_a, class_id=class_id)
            uid = make_user(app, role="student", school_id=sid_a)
            sub = make_subscription(app, user_id=uid, plan_id=plan, class_id=class_id)
            from app.models.billing import Subscription

            sub_obj = db.session.get(Subscription, sub)
            sub_obj.status = "pending"
            db.session.commit()

            linked_admin = make_user(app, role="school_admin", school_id=sid_a)
            foreign_admin = make_user(app, role="school_admin", school_id=sid_b)
            from app.models.user import UserRoleLink as URL

            for uid_, school in ((linked_admin, sid_a), (foreign_admin, sid_b)):
                if db.session.query(URL).filter_by(user_id=uid_, school_id=school).first() is None:
                    db.session.add(URL(user_id=uid_, school_id=school, role="school_admin", is_active=True))
            db.session.commit()

            notified = []

            svc = PaymentService()

            import app.services.communication as comm

            def capture_notify(user_id, *a, **k):
                notified.append(user_id)

            # monkeypatch (لا استبدال يدوي): يُعاد الأصل تلقائياً بعد الاختبار.
            # الاستبدال اليدوي سابقاً كان يترك ``communication.notify = None``
            # فيسقط أي مسار لاحق يستدعيه (محرّك واتساب: 'NoneType' not callable).
            monkeypatch.setattr(comm, "tx", lambda fn, *args, **kw: None)  # no-op tx — لا كتابة فعلية
            monkeypatch.setattr(comm, "notify", capture_notify)
            svc._flag_for_review(sub_obj, title="t", body="b", school_id=sid_a)

            assert foreign_admin not in notified, "D5: foreign school admin must not be notified"
            assert linked_admin in notified, "D5: the school's own admin must be notified"


# ════════════════════════════════════════════════════════════════════
# D-7 — wallet tenancy pre-check
# ════════════════════════════════════════════════════════════════════
class TestD7WalletTenancyPrecheck:
    def test_deposit_to_foreign_school_user_is_forbidden(self, app):

        sid_a = make_school(app)
        sid_b = make_school(app)
        admin = make_user(app, role="school_admin", school_id=sid_a)
        foreign = make_user(app, role="student", school_id=sid_b)

        with app.app_context():
            from app.extensions import db
            from app.models.user import UserRoleLink

            for uid_, school, role_ in ((admin, sid_a, "school_admin"), (foreign, sid_b, "student")):
                if db.session.query(UserRoleLink).filter_by(user_id=uid_, school_id=school).first() is None:
                    db.session.add(UserRoleLink(user_id=uid_, school_id=school, role=role_, is_active=True))
            db.session.commit()

        client = app.test_client()
        email = f"d7-{uuid.uuid4().hex[:8]}@test.com"
        make_user(app, role="school_admin", school_id=sid_a, email=email)
        client.post("/auth/login", data={"email": email, "password": _PASSWORD}, follow_redirects=False)

        r = client.post(
            "/api/v1/wallet/deposits",
            json={
                "user_id": foreign,
                "amount": "50.00",
                "idempotency_key": f"d7-{uuid.uuid4().hex[:8]}",
                "school_id": sid_a,
            },
        )
        assert r.status_code == 403, f"D7: deposit must 403 for out-of-tenant user, got {r.status_code}"

        # sanity: a legitimate in-school target works
        ok = client.post(
            "/api/v1/wallet/deposits",
            json={
                "user_id": admin,
                "amount": "50.00",
                "idempotency_key": f"d7-ok-{uuid.uuid4().hex[:8]}",
            },
        )
        assert ok.status_code == 200

    def test_transfer_to_foreign_school_user_is_forbidden(self, app):
        sid_a = make_school(app)
        sid_b = make_school(app)
        alice = make_user(app, role="student", school_id=sid_a)
        email = f"d7t-{uuid.uuid4().hex[:8]}@test.com"
        make_user(app, role="student", school_id=sid_a, email=email)
        bob_foreign = make_user(app, role="student", school_id=sid_b)

        with app.app_context():
            from app.extensions import db
            from app.models.user import UserRoleLink

            if db.session.query(UserRoleLink).filter_by(user_id=alice, school_id=sid_a).first() is None:
                db.session.add(UserRoleLink(user_id=alice, school_id=sid_a, role="student", is_active=True))
                db.session.commit()

        client = app.test_client()
        client.post("/auth/login", data={"email": email, "password": _PASSWORD}, follow_redirects=False)
        r = client.post(
            "/api/v1/wallet/transfers",
            json={
                "dest_user_id": bob_foreign,
                "amount": "10.00",
                "idempotency_key": f"d7t-{uuid.uuid4().hex[:8]}",
            },
        )
        assert r.status_code == 403, f"D7: transfer must 403 to foreign tenant, got {r.status_code}"


# ════════════════════════════════════════════════════════════════════
# P7 — wallet ↔ tutoring integration (dual-leg ledger)
# ════════════════════════════════════════════════════════════════════
class TestP7WalletTutoringIntegration:
    def _completed_session(self, app, sid, tutor, price="200.00"):
        from decimal import Decimal

        from app.extensions import db
        from app.models.tutoring import TutoringSession

        with app.app_context():
            s = TutoringSession(
                tutor_id=tutor,
                student_id=tutor,  # decoupling not relevant here
                subject="math",
                price=Decimal(price),
                status="active",
                payment_status="paid",
                currency="ILS",
            )
            # school_id assignment via tutor link

            db.session.add(s)
            db.session.commit()
            sid_ = s.id
        # tutor's school flows through the active UserRoleLink created by make_user
        return sid_

    def test_dual_leg_ledger_created_on_completion(self, app):
        from decimal import Decimal

        sid = make_school(app)
        tutor = make_user(app, role="teacher", school_id=sid)
        wid = _wallet_id(app, sid, tutor)
        _fund(app, wid, Decimal("0.00"))

        session_id = self._completed_session(app, sid, tutor)
        with app.app_context():
            from app.extensions import db
            from app.models.tutoring import TutoringSession
            from app.services.tutoring import create_commission_record

            s = db.session.get(TutoringSession, session_id)
            assert s is not None
            s.status = "completed"
            db.session.commit()

            create_commission_record(db.session.get(TutoringSession, session_id))

        with app.app_context():
            from app.extensions import db
            from app.models.tutoring import TutoringSession
            from app.models.wallet import Wallet, WalletTransaction

            s = db.session.get(TutoringSession, session_id)
            inflow = WalletTransaction.query.filter_by(
                reference_type="tutoring_session", reference_id=session_id, transaction_type="tutor_session_credit"
            ).first()
            commission = WalletTransaction.query.filter_by(
                reference_type="tutoring_session", reference_id=session_id, transaction_type="tutor_commission"
            ).first()
            assert inflow is not None, "P7: inflow leg required"
            assert commission is not None, "P7: commission leg required"
            assert inflow.amount == Decimal("200.00")
            assert commission.amount == Decimal("40.00")  # 20%
            assert inflow.destination_wallet_id == wid and inflow.source_wallet_id is None
            assert commission.source_wallet_id == wid and commission.destination_wallet_id is None

            w = db.session.get(Wallet, wid)
            assert w.balance == Decimal("160.00"), f"P7: net balance 200-40, got {w.balance}"

    def test_recompletion_does_not_double_ledger(self, app):
        from decimal import Decimal

        sid = make_school(app)
        tutor = make_user(app, role="teacher", school_id=sid)
        wid = _wallet_id(app, sid, tutor)
        _fund(app, wid, Decimal("0.00"))
        session_id = self._completed_session(app, sid, tutor)

        with app.app_context():
            from app.extensions import db
            from app.models.tutoring import TutoringSession
            from app.services.tutoring import create_commission_record

            s = db.session.get(TutoringSession, session_id)
            s.status = "completed"
            db.session.commit()

            create_commission_record(db.session.get(TutoringSession, session_id))
            # re-run — e.g. status toggled or retried concurrently
            create_commission_record(db.session.get(TutoringSession, session_id))

        with app.app_context():
            from app.extensions import db
            from app.models.wallet import WalletTransaction

            inflows = WalletTransaction.query.filter_by(
                reference_type="tutoring_session", reference_id=session_id, transaction_type="tutor_session_credit"
            ).all()
            commissions = WalletTransaction.query.filter_by(
                reference_type="tutoring_session", reference_id=session_id, transaction_type="tutor_commission"
            ).all()
            assert len(inflows) == 1, f"P7: inflow must be idempotent, got {len(inflows)}"
            assert len(commissions) == 1, f"P7: commission must be idempotent, got {len(commissions)}"
            from app.models.wallet import Wallet as W

            w = db.session.get(W, wid)
            assert w.balance == Decimal("160.00"), "P7: no double-credit on retries"

    def test_session_without_wallet_creates_wallet_and_ledger_legs(self, app):
        """AZ-P3-16: غياب المحفظة لم يعد تخطياً صامتاً — تُنشأ وتُكتب الساقان.

        السلوك القديم (P7) كان يُنشئ سجل العمولة ويسقط ساقي الدفتر بلا أثر
        حين لا يوجد صفّ محفظة، فيتباعد رصيد المعلم عن سجل عمولته. الجديد
        يُنشئ المحفظة بمنشئ ``wallet_service`` نفسه ثم يكتب القبض والعمولة.
        """
        from decimal import Decimal

        sid = make_school(app)
        tutor = make_user(app, role="teacher", school_id=sid)
        with app.app_context():
            from app.models.wallet import Wallet

            assert Wallet.query.filter_by(school_id=sid, user_id=tutor).first() is None
        session_id = self._completed_session(app, sid, tutor)

        with app.app_context():
            from app.extensions import db
            from app.models.tutoring import TutoringSession
            from app.services.tutoring import create_commission_record

            s = db.session.get(TutoringSession, session_id)
            s.status = "completed"
            db.session.commit()
            rec = create_commission_record(db.session.get(TutoringSession, session_id))
            assert rec is not None, "P7: commission record created even without wallet"

        with app.app_context():
            from app.models.wallet import Wallet, WalletTransaction

            wallet = Wallet.query.filter_by(school_id=sid, user_id=tutor).one()
            legs = WalletTransaction.query.filter_by(reference_type="tutoring_session", reference_id=session_id).all()
            assert {leg.transaction_type for leg in legs} == {"tutor_session_credit", "tutor_commission"}
            # مطابقة الرصيد مع مجموع قيود الدفتر — لا رصيد بلا أثر ولا أثر بلا رصيد.
            legs_net = sum(
                leg.amount if leg.transaction_type == "tutor_session_credit" else -leg.amount for leg in legs
            )
            assert wallet.balance == Decimal("160.00")  # 200 - 20% عمولة
            assert wallet.balance == legs_net


class TestAZP109PendingPaymentsCron:
    """AZ-P1-09 — الدفعات المعلّقة تُنهى من CLI حقيقي بدل كتلة cron ميتة.

    كانت المهمة في `scripts/cron_jobs.sh` تفشل بلا أثر (`datetime.utcnow()`
    و`timedelta` غير مستوردين)، فلا تُنظَّف الدفعات المعلّقة أبداً. المنطق الآن
    في `billing.expire_pending_payments` + أمر `flask expire-pending-payments`،
    والاختبارات تقيس حالات الصفوف فعلياً لا مجرد رمز الخروج.
    """

    def _payment(self, app, *, status="pending", age_hours=0, sub_status="pending"):
        sid = make_school(app)
        student = make_user(app, role="student", school_id=sid)
        class_id = _class(app, sid)
        plan = make_subscription_plan(app, sid, class_id=class_id)
        sub = make_subscription(app, student, plan, class_id, status=sub_status)
        payment = make_payment(app, sub, amount=50.0, status=status)
        if age_hours:
            from datetime import UTC, datetime, timedelta

            from app.extensions import db
            from app.models.billing import ManualPayment

            with app.app_context():
                row = db.session.get(ManualPayment, payment)
                row.created_at = datetime.now(UTC) - timedelta(hours=age_hours)
                db.session.commit()
        return sid, sub, payment

    def _payment_status(self, app, payment_id):
        from app.extensions import db
        from app.models.billing import ManualPayment

        with app.app_context():
            return db.session.get(ManualPayment, payment_id).status

    def _subscription_status(self, app, subscription_id):
        from app.extensions import db
        from app.models.billing import Subscription

        with app.app_context():
            return db.session.get(Subscription, subscription_id).status

    def test_cli_expires_only_payments_past_the_ttl(self, app):
        runner = app.test_cli_runner()
        _sid_old, _sub_old, old = self._payment(app, age_hours=30)
        _sid_new, _sub_new, fresh = self._payment(app, age_hours=1)

        result = runner.invoke(args=["expire-pending-payments"])
        assert result.exit_code == 0
        assert "expired_pending_payments=1" in result.output
        assert self._payment_status(app, old) == "expired"
        assert self._payment_status(app, fresh) == "pending"

    def test_cli_leaves_reviewed_payments_and_subscriptions_alone(self, app):
        runner = app.test_cli_runner()
        _sid_a, sub_pending, old_pending = self._payment(app, age_hours=48)
        _sid_b, _sub_approved, approved = self._payment(app, status="approved", age_hours=48)
        _sid_c, _sub_rejected, rejected = self._payment(app, status="rejected", age_hours=48)
        _sid_d, active_sub, _pay_active = self._payment(app, status="approved", age_hours=48, sub_status="active")

        result = runner.invoke(args=["expire-pending-payments"])
        assert result.exit_code == 0
        assert "expired_pending_payments=1" in result.output

        assert self._payment_status(app, old_pending) == "expired"
        assert self._payment_status(app, approved) == "approved"
        assert self._payment_status(app, rejected) == "rejected"
        # لا يُلمس أي اشتراك: لا الذي انتهت دفعته ولا الفعّال.
        assert self._subscription_status(app, sub_pending) == "pending"
        assert self._subscription_status(app, active_sub) == "active"

    def test_ttl_option_shortens_the_window(self, app):
        runner = app.test_cli_runner()
        _sid, _sub, payment = self._payment(app, age_hours=3)

        assert runner.invoke(args=["expire-pending-payments", "--ttl-hours", "6"]).exit_code == 0
        assert self._payment_status(app, payment) == "pending"

        short = runner.invoke(args=["expire-pending-payments", "--ttl-hours", "2"])
        assert short.exit_code == 0
        assert "expired_pending_payments=1" in short.output
        assert self._payment_status(app, payment) == "expired"

    def test_invalid_ttl_is_refused_without_writing(self, app):
        from app.core.db import TxError
        from app.services.billing import expire_pending_payments

        runner = app.test_cli_runner()
        _sid, _sub, payment = self._payment(app, age_hours=48)

        assert runner.invoke(args=["expire-pending-payments", "--ttl-hours", "0"]).exit_code == 2
        assert self._payment_status(app, payment) == "pending"

        # الحماية نفسها في الخدمة (للمستدعي البرمجي لا الـ CLI فقط).
        with app.app_context():
            with pytest.raises(TxError):
                expire_pending_payments(0)
