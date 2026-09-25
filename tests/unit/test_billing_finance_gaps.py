"""Batch 5 — finance, invoice, billing, payments service gaps (verified misses).

- finance.py (15%): school_revenue_summary empty/populated, student_balance
  with/without subscription, accounts_receivable batch path with sorting.
- invoice.py: invoice number format, HTML invoice for real subscription,
  missing subscription → None, PDF render.
- billing.py: create_plan validation, subscribe double-active TxError,
  record_manual_payment receipt path, approve/reject double-review guard,
  expire_subscriptions, can_record_payment bounds, discount create/validate/
  apply branches.
"""

from __future__ import annotations

import io
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from tests.conftest import (
    _uid,
    make_class,
    make_grade,
    make_payment,
    make_school,
    make_subject,
    make_subscription,
    make_subscription_plan,
    make_user,
)


def _class_setup(app, sid):
    gid = make_grade(app, sid)
    return make_class(app, sid, gid, make_subject(app))


# ═══════════════════════════════════════════════════════════════════════════
# finance.py
# ═══════════════════════════════════════════════════════════════════════════


class TestFinanceSummary:
    def test_school_revenue_summary_empty(self, app):
        from app.services.finance import school_revenue_summary

        sid = make_school(app)
        with app.app_context():
            summary = school_revenue_summary(sid)
            assert summary["total_revenue"] == Decimal("0")
            assert summary["pending_amount"] == Decimal("0")
            assert summary["overdue_count"] == 0
            assert summary["active_count"] == 0

    def test_school_revenue_summary_populated(self, app):
        from app.services.finance import school_revenue_summary

        sid = make_school(app)
        with app.app_context():
            cid = _class_setup(app, sid)
            plan = make_subscription_plan(app, sid, cid, price=100.0)
            uid = make_user(app, role="student", school_id=sid)
            sub1 = make_subscription(app, uid, plan, cid, price=100.0, status="active")
            sub2 = make_subscription(app, uid, plan, cid, price=100.0, status="expired")
            make_payment(app, sub1, amount=60.0, status="approved")
            make_payment(app, sub1, amount=10.0, status="pending")
            make_payment(app, sub2, amount=5.0, status="pending")

            summary = school_revenue_summary(sid)
            assert summary["active_count"] == 1
            assert summary["overdue_count"] == 1
            assert summary["total_revenue"] == Decimal("60.0")
            assert summary["pending_amount"] == Decimal("15.0")

    def test_student_balance_without_subscription(self, app):
        from app.services.finance import student_balance

        sid = make_school(app)
        with app.app_context():
            cid = _class_setup(app, sid)
            uid = make_user(app, role="student", school_id=sid)
            result = student_balance(uid, cid)
            assert result["has_subscription"] is False
            assert result["balance"] == 0

    def test_student_balance_with_subscription(self, app):
        from app.services.finance import student_balance

        sid = make_school(app)
        with app.app_context():
            cid = _class_setup(app, sid)
            plan = make_subscription_plan(app, sid, cid)
            uid = make_user(app, role="student", school_id=sid)
            sub = make_subscription(app, uid, plan, cid, price=100.0, status="active")
            make_payment(app, sub, amount=40.0, status="approved")

            result = student_balance(uid, cid)
            assert result["has_subscription"] is True
            assert result["total_price"] == 100.0
            assert result["total_paid"] == 40.0
            assert result["balance"] == 60.0

    def test_accounts_receivable_empty_school(self, app):
        from app.services.finance import accounts_receivable

        sid = make_school(app)
        with app.app_context():
            assert accounts_receivable(sid) == []

    def test_accounts_receivable_sorts_by_balance_desc(self, app):
        from app.services.finance import accounts_receivable

        sid = make_school(app)
        with app.app_context():
            cid = _class_setup(app, sid)
            plan = make_subscription_plan(app, sid, cid)
            u1 = make_user(app, role="student", school_id=sid)
            u2 = make_user(app, role="student", school_id=sid)
            u3 = make_user(app, role="student", school_id=sid)
            sub_small = make_subscription(app, u1, plan, cid, price=100.0, status="active")
            sub_big = make_subscription(app, u2, plan, cid, price=200.0, status="pending")
            sub_paid = make_subscription(app, u3, plan, cid, price=100.0, status="active")
            make_payment(app, sub_small, amount=80.0, status="approved")  # balance 20
            make_payment(app, sub_big, amount=0, status="approved", reference="zero")
            make_payment(app, sub_paid, amount=100.0, status="approved")  # fully paid → excluded

            rows = accounts_receivable(sid)
            balances = [r["balance"] for r in rows]
            assert balances == sorted(balances, reverse=True)
            assert sub_paid not in [r["subscription_id"] for r in rows]
            assert rows[0]["subscription_id"] == sub_big  # 200 balance first
            assert rows[0]["student"] is not None  # joinedload worked


# ═══════════════════════════════════════════════════════════════════════════
# invoice.py
# ═══════════════════════════════════════════════════════════════════════════


class TestInvoice:
    def test_invoice_number_format(self, app):
        from app.services.invoice import generate_invoice_number

        sid = make_school(app)
        with app.app_context():
            cid = _class_setup(app, sid)
            plan = make_subscription_plan(app, sid, cid)
            uid = make_user(app, role="student", school_id=sid)
            from app.extensions import db
            from app.models.billing import Subscription

            sub = db.session.get(Subscription, make_subscription(app, uid, plan, cid, price=50.0))
            number = generate_invoice_number(sub)
            year = datetime.now(UTC).year
            assert number.startswith(f"INV-{cid}-{year}-")
            assert len(number.split("-")[-1]) == 5

    def test_generate_invoice_html_missing_subscription(self, app):
        from app.services.invoice import generate_invoice_html

        with app.test_request_context("/"):
            assert generate_invoice_html(999_999) is None

    def test_build_invoice_story_fills_elements(self, app):
        """قصة الفاتورة المشتركة تمتلئ بعناصر platypus (تستخدمها الخدمة والمهمة)."""
        from app.services.invoice import build_invoice_story
        from reportlab.platypus import Table

        sid = make_school(app)
        with app.app_context():
            cid = _class_setup(app, sid)
            plan = make_subscription_plan(app, sid, cid)
            uid = make_user(app, role="student", school_id=sid)
            sub_id = make_subscription(app, uid, plan, cid, price=100.0, status="active")
            make_payment(app, sub_id, amount=40.0, status="approved")
            make_payment(app, sub_id, amount=10.0, status="pending")
            from app.extensions import db
            from app.models.billing import Subscription

            sub = db.session.get(Subscription, sub_id)

            from app.core.pdf import blank_pdf_document

            doc, story = blank_pdf_document()
            build_invoice_story(story, sub)
        assert len(story) >= 8  # عنوان + وصف + meta + جدولا + عناوين + سجل مدفوعات
        assert any(isinstance(el, Table) for el in story)

    def test_generate_invoice_html_real_subscription(self, app):
        from app.services.invoice import generate_invoice_html

        sid = make_school(app)
        with app.app_context():
            cid = _class_setup(app, sid)
            plan = make_subscription_plan(app, sid, cid)
            uid = make_user(app, role="student", school_id=sid)
            sub = make_subscription(app, uid, plan, cid, price=100.0, status="active")
            make_payment(app, sub, amount=40.0, status="approved")

            with app.test_request_context("/"):
                html = generate_invoice_html(sub)
            assert html is not None
            assert "INV-" in html  # invoice number rendered

    def test_render_invoice_pdf_returns_bytes(self, app, tmp_path, monkeypatch):
        from app.services.invoice import render_invoice_pdf

        sid = make_school(app)
        monkeypatch.setitem(app.config, "UPLOAD_FOLDER", str(tmp_path))
        with app.app_context():
            cid = _class_setup(app, sid)
            plan = make_subscription_plan(app, sid, cid)
            uid = make_user(app, role="student", school_id=sid)
            sub = make_subscription(app, uid, plan, cid, price=100.0, status="active")
            pdf = render_invoice_pdf(sub)
        assert isinstance(pdf, bytes)
        assert bytes(pdf)[:5] == b"%PDF-"
        assert len(pdf) > 1000


# ═══════════════════════════════════════════════════════════════════════════
# billing.py
# ═══════════════════════════════════════════════════════════════════════════


class TestPlanLifecycle:
    def test_create_plan_validation(self, app):
        from app.services.billing import create_plan

        sid = make_school(app)
        with app.app_context():
            assert create_plan(sid, "", "annual", 100)[0] is None
            assert create_plan(sid, "خطة", "weekly", 100)[1] is not None
            plan, err = create_plan(sid, "خطة أ", "first_term", "75.50", duration_days=90)
            assert err is None
            assert plan.price == Decimal("75.50")
            assert plan.duration_days == 90

    def test_list_plans_class_filter(self, app):
        from app.services.billing import list_plans

        sid = make_school(app)
        with app.app_context():
            cid = _class_setup(app, sid)
            make_subscription_plan(app, sid, cid, price=90.0)
            make_subscription_plan(app, sid, None, price=110.0)  # school-wide plan
            plans = list_plans(class_id=cid)
            assert all(p.is_active for p in plans)
            assert len(plans) == 2  # class + school-wide
            prices = [p.price for p in plans]
            assert prices == sorted(prices)  # ordered by price asc

    def test_subscribe_duplicate_active_raises_txerror(self, app):
        from app.services.billing import subscribe

        sid = make_school(app)
        with app.app_context():
            cid = _class_setup(app, sid)
            plan = make_subscription_plan(app, sid, cid)
            uid = make_user(app, role="student", school_id=sid)
            from app.extensions import db
            from app.models.billing import SubscriptionPlan

            plan_obj = db.session.get(SubscriptionPlan, plan)
            sub, err = subscribe(uid, plan_obj, cid)
            assert err is None and sub.status == "pending"

            # activate the first subscription then try again
            sub.status = "active"
            db.session.commit()

            sub2, err2 = subscribe(uid, plan_obj, cid)
            assert sub2 is None
            assert "اشتراك نشط" in err2


class TestPaymentRecording:
    def _sub(self, app):
        sid = make_school(app)
        with app.app_context():
            cid = _class_setup(app, sid)
            plan = make_subscription_plan(app, sid, cid)
            uid = make_user(app, role="student", school_id=sid)
            from app.extensions import db
            from app.models.billing import Subscription

            sub_id = make_subscription(app, uid, plan, cid, price=100.0, status="pending")
            return db.session.get(Subscription, sub_id)

    def test_record_manual_payment_validation(self, app):
        from app.services.billing import record_manual_payment

        with app.app_context():
            sub = self._sub(app)
            payment, err = record_manual_payment(sub, "", 0)
            assert payment is None and err is not None
            payment2, err2 = record_manual_payment(sub, "ref-ok", -5)
            assert payment2 is None and err2 is not None

    def test_record_manual_payment_with_receipt(self, app):

        from app.services import billing as billing_mod
        from app.services.billing import record_manual_payment

        with app.app_context():
            sub = self._sub(app)
            receipt = io.BytesIO(b"%PDF-fake")
            receipt.filename = "r.pdf"
            receipt.mimetype = "application/pdf"
            receipt.content_length = 10
            with patch.object(billing_mod, "save_upload", return_value=f"{_uid()}.pdf"):
                payment, err = record_manual_payment(sub, "ref-1", 50.0, note="ملاحظة", receipt_file=receipt)
            assert err is None
            assert payment.amount == Decimal("50.00")
            assert len(payment.receipts) == 1
            assert payment.receipts[0].original_name == "r.pdf"

    def test_can_record_payment_bounds(self, app):
        from app.services.billing import can_record_payment

        sid = make_school(app)
        with app.app_context():
            cid = _class_setup(app, sid)
            plan = make_subscription_plan(app, sid, cid)
            uid = make_user(app, role="student", school_id=sid)
            sub = make_subscription(app, uid, plan, cid, price=100.0, status="active")
            make_payment(app, sub, amount=30.0, status="approved")  # balance 70

            ok, msg = can_record_payment(sub, 70)
            assert ok is True and msg == ""
            ok2, msg2 = can_record_payment(sub, 70.01)
            assert ok2 is False and "يتجاوز" in msg2
            ok3, msg3 = can_record_payment(sub, 0)
            assert ok3 is False and "أكبر من صفر" in msg3

    def test_subscription_balance_missing_subscription(self, app):
        from decimal import Decimal

        from app.services.billing import subscription_balance

        with app.app_context():
            assert subscription_balance(987_654) == Decimal("0.00")

    def test_subscription_payment_summary_missing(self, app):
        from app.services.billing import subscription_payment_summary

        with app.app_context():
            assert subscription_payment_summary(987_654) == {}


class TestApproveRejectExpire:
    def _pending_payment(self, app):
        sid = make_school(app)
        with app.app_context():
            cid = _class_setup(app, sid)
            plan = make_subscription_plan(app, sid, cid)
            uid = make_user(app, role="student", school_id=sid)
            sub_id = make_subscription(app, uid, plan, cid, price=100.0, status="pending")
            pay_id = make_payment(app, sub_id, amount=100.0, status="pending")
            from app.extensions import db
            from app.models.billing import ManualPayment

            return db.session.get(ManualPayment, pay_id)

    def test_approve_payment_activates_and_creates_membership(self, app):
        from app.extensions import db
        from app.models.billing import ManualPayment
        from app.models.class_room import ClassMember
        from app.services.billing import approve_payment

        with app.app_context():
            payment = self._pending_payment(app)
            sub = approve_payment(payment, reviewer_id=None)
            assert sub.status == "active"
            assert sub.start_at is not None and sub.end_at is not None
            member = ClassMember.query.filter_by(class_id=sub.class_id, user_id=sub.user_id, status="active").first()
            assert member is not None

            # Double-approve must raise TxError
            fresh = db.session.get(ManualPayment, payment.id)
            fresh.status = "approved"
            db.session.commit()
            from app.core.db import TxError

            with pytest.raises(TxError):
                approve_payment(fresh)

    def test_reject_payment_cancels_pending_subscription(self, app):
        from app.core.db import TxError
        from app.extensions import db
        from app.models.billing import ManualPayment
        from app.services.billing import reject_payment

        with app.app_context():
            payment = self._pending_payment(app)
            sub_id = payment.subscription_id
            reject_payment(payment, reviewer_id=None)
            from app.models.billing import Subscription

            assert db.session.get(Subscription, sub_id).status == "cancelled"

            # Double-reject must raise TxError
            fresh = db.session.get(ManualPayment, payment.id)
            fresh.status = "rejected"
            db.session.commit()
            with pytest.raises(TxError):
                reject_payment(fresh)

    def test_expire_subscriptions(self, app):
        from app.services.billing import expire_subscriptions

        sid = make_school(app)
        with app.app_context():
            cid = _class_setup(app, sid)
            plan = make_subscription_plan(app, sid, cid)
            uid = make_user(app, role="student", school_id=sid)
            from app.extensions import db
            from app.models.billing import Subscription

            expired_id = make_subscription(app, uid, plan, cid, price=100.0, status="active")
            active_id = make_subscription(app, uid, plan, cid, price=100.0, status="pending")
            db.session.get(Subscription, expired_id).end_at = datetime.now(UTC) - timedelta(days=1)
            db.session.commit()

            count = expire_subscriptions()
            assert count >= 1
            assert db.session.get(Subscription, expired_id).status == "expired"
            assert db.session.get(Subscription, active_id).status == "pending"


class TestDiscountCodes:
    def test_create_discount_code_validation(self, app):
        from app.services.billing import create_discount_code

        sid = make_school(app)
        with app.app_context():
            assert create_discount_code(sid, "", "اسم", "fixed", 10)[1] is not None
            assert create_discount_code(sid, "X1", "", "fixed", 10)[1] is not None
            assert create_discount_code(sid, "X2", "اسم", "coupon", 10)[1] is not None
            assert create_discount_code(sid, "X3", "اسم", "fixed", -5)[1] is not None
            assert create_discount_code(sid, "X4", "اسم", "fixed", 10, max_uses=0)[1] is not None
            past = date.today() - timedelta(days=1)
            assert create_discount_code(sid, "X5", "اسم", "fixed", 10, expiry_date=past)[1] is not None

            dc, err = create_discount_code(sid, " GOOD ", "خصم", "percentage", 10, applicable_plan_ids=[1, 2])
            assert err is None
            assert dc.code == "GOOD"
            assert dc.value == Decimal("10.00")

            dup, dup_err = create_discount_code(sid, "GOOD", "مكرر", "fixed", 5)
            assert dup is None and "موجود مسبقاً" in dup_err

    def test_validate_discount_code_all_rejections(self, app):
        from app.services.billing import create_discount_code, validate_discount_code

        sid = make_school(app)
        with app.app_context():
            cid = _class_setup(app, sid)
            plan = make_subscription_plan(app, sid, cid, price=100.0)

            assert validate_discount_code("", plan)[1] is not None
            assert validate_discount_code("NOPE", plan)[1] is not None

            dc, _ = create_discount_code(sid, "INACTIVE", "م", "fixed", 10)
            dc.is_active = False
            from app.extensions import db

            db.session.commit()
            assert "غير مفعل" in validate_discount_code("INACTIVE", plan)[1]

            expired, _ = create_discount_code(sid, "OLDCODE", "م", "fixed", 10, expiry_date=date.today())
            expired.expiry_date = date.today() - timedelta(days=1)
            db.session.commit()
            assert "منتهي" in validate_discount_code("OLDCODE", plan)[1]

            create_discount_code(sid, "MAXED", "م", "fixed", 10, max_uses=1)
            from app.models.billing import DiscountCode

            row = DiscountCode.query.filter_by(code="MAXED").first()
            row.used_count = 1
            db.session.commit()
            assert "استنفاد" in validate_discount_code("MAXED", plan)[1]

            create_discount_code(sid, "PLANLOCK", "م", "fixed", 10, applicable_plan_ids=[plan])
            other_plan = make_subscription_plan(app, sid, cid, price=80.0)
            assert "لهذه الخطة" in validate_discount_code("PLANLOCK", other_plan)[1]
            assert validate_discount_code("PLANLOCK", plan)[1] is None  # applicable

            assert validate_discount_code("GOODCODE", 999_999)[1] is not None  # missing plan

    def test_validate_and_apply_percentage_and_fixed(self, app):
        from decimal import Decimal

        from app.extensions import db
        from app.models.billing import DiscountCode, Subscription
        from app.services.billing import (
            apply_discount_code,
            create_discount_code,
            validate_discount_code,
        )

        sid = make_school(app)
        with app.app_context():
            cid = _class_setup(app, sid)
            plan = make_subscription_plan(app, sid, cid, price=100.0)
            uid = make_user(app, role="student", school_id=sid)
            sub_id = make_subscription(app, uid, plan, cid, price=100.0, status="active")

            # percentage capped at plan price
            create_discount_code(sid, "P20", "عشرون", "percentage", 20)
            discount, err = validate_discount_code("P20", plan)
            assert err is None and discount == Decimal("20.00")

            # fixed larger than price → capped
            create_discount_code(sid, "BIG", "كبير", "fixed", 500)
            big, err2 = validate_discount_code("BIG", plan)
            assert err2 is None and big == Decimal("100.00")  # capped at plan price

            # apply to real subscription
            applied, apply_err = apply_discount_code(sub_id, "P20")
            assert apply_err is None and applied == Decimal("20.00")
            assert db.session.get(Subscription, sub_id).price == Decimal("80.00")

            # exhausted → rowcount guard
            row = DiscountCode.query.filter_by(code="P20").first()
            row.used_count = row.max_uses
            db.session.commit()
            _, exhausted_err = apply_discount_code(sub_id, "P20")
            assert "استنفاد" in exhausted_err

            # unknown subscription
            assert apply_discount_code(987_654, "P20")[1] is not None
            assert apply_discount_code(sub_id, "")[1] is not None
