"""Batch 5 (جزء ثانٍ) — بقايا billing: list_subscriptions filters، has_active_subscription،
approvePayment → رفع member غير نشط، invoice ImportError.

المصادر تحقق يدوي: billing.py:104-115 (فلاتر list_subscriptions)، 212-213
(elif عضو غير نشط → تفعيل)، 276-277 (has_active_subscription)، 393
(الخطة غير موجودة في validate)، 422-440 (قيمة الخصم تتجاوز السعر).
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

from tests.conftest import (
    make_class,
    make_grade,
    make_school,
    make_subject,
    make_subscription,
    make_subscription_plan,
    make_user,
)


def _setup(app):
    sid = make_school(app)
    gid = make_grade(app, sid)
    cid = make_class(app, sid, gid, make_subject(app))
    plan = make_subscription_plan(app, sid, cid, price=100.0)
    uid = make_user(app, role="student", school_id=sid)
    return sid, cid, plan, uid


class TestListSubscriptionsFilters:
    def test_all_filters_combined(self, app):
        from app.services.billing import list_subscriptions

        sid, cid, plan, uid = _setup(app)
        with app.app_context():
            sub1 = make_subscription(app, uid, plan, cid, price=100.0, status="active")
            make_subscription(app, uid, plan, cid, price=90.0, status="pending")
            make_subscription(app, uid, plan, cid, price=80.0, status="expired")

            # بلا فلاتر → كل الثلاثة
            assert len(list_subscriptions()) == 3
            # فلتر user
            by_user = list_subscriptions(user_id=uid)
            assert len(by_user) == 3
            # فلتر class
            by_class = list_subscriptions(class_id=cid)
            assert len(by_class) == 3
            # فلتر status
            active_only = list_subscriptions(status="active")
            assert len(active_only) == 1
            assert active_only[0].id == sub1
            # فلاتر مركّبة
            combo = list_subscriptions(user_id=uid, class_id=cid, status="pending")
            assert len(combo) == 1
            # joinedload يعمل — لا N+1
            assert combo[0].user.id == uid
            assert combo[0].plan.id == plan
            # ترتيب تنازلي حسب created_at
            all_subs = list_subscriptions()
            created = [s.created_at for s in all_subs]
            assert created == sorted(created, key=lambda x: (x is None, x), reverse=True)

    def test_empty_result(self, app):
        from app.services.billing import list_subscriptions

        with app.app_context():
            assert list_subscriptions(user_id=987_654) == []


class TestApproveMemberReactivation:
    def test_approve_reactivates_inactive_member(self, app):
        from app.extensions import db
        from app.models.billing import ManualPayment, Subscription
        from app.models.class_room import ClassMember
        from app.services.billing import approve_payment
        from tests.conftest import make_payment

        sid, cid, plan, uid = _setup(app)
        with app.app_context():
            sub_id = make_subscription(app, uid, plan, cid, price=100.0, status="pending")
            # عضو موجود لكن غير نشط — ننشئه يدوياً لأن make_subscription لا ينشئه
            # (قيد check يسمح فقط active/removed/pending)
            db.session.add(ClassMember(class_id=cid, user_id=uid, status="removed"))
            db.session.commit()

            pay_id = make_payment(app, sub_id, amount=100.0, status="pending")
            approve_payment(db.session.get(ManualPayment, pay_id))

            member = ClassMember.query.filter_by(class_id=cid, user_id=uid).first()
            assert member.status == "active"
            assert db.session.get(Subscription, sub_id).status == "active"


class TestHasActiveSubscription:
    def test_true_false_and_missing(self, app):
        from app.services.billing import has_active_subscription

        sid, cid, plan, uid = _setup(app)
        with app.app_context():
            assert has_active_subscription(uid, cid) is False
            make_subscription(app, uid, plan, cid, price=100.0, status="active")
            assert has_active_subscription(uid, cid) is True
            # user غير موجود إطلاقاً
            assert has_active_subscription(987_654, cid) is False


class TestValidateMissingPlan:
    def test_validate_discount_missing_plan(self, app):
        from app.services.billing import create_discount_code, validate_discount_code

        sid = make_school(app)
        with app.app_context():
            create_discount_code(sid, "MISSPLAN", "م", "fixed", 10)
            _, err = validate_discount_code("MISSPLAN", 987_654)
            assert "الخطة غير موجودة" in err


class TestApplyDiscountOverPrice:
    def test_discount_exceeds_subscription_price(self, app):
        """sub.price أصغر من الخصم → new_price سالب → TxError وتراجع tx."""
        from app.extensions import db
        from app.models.billing import Subscription
        from app.services.billing import apply_discount_code, create_discount_code

        sid, cid, plan, uid = _setup(app)
        with app.app_context():
            sub_id = make_subscription(app, uid, plan, cid, price=100.0, status="active")
            # سعر الاشتراك خُفّض سابقاً (خصم سابق مثلاً) إلى 30
            db.session.get(Subscription, sub_id).price = Decimal("30.00")
            db.session.commit()

            create_discount_code(sid, "HUGE", "ضخم", "fixed", 45)  # ≤ سعر الخطة فلا يُقصّ
            applied, err = apply_discount_code(sub_id, "HUGE")
            assert applied is None
            assert "تتجاوز" in err
            # السعر لم يتغير (tx rollback)
            assert db.session.get(Subscription, sub_id).price == Decimal("30.00")


class TestInvoiceImportError:
    def test_render_pdf_import_error_returns_none(self, app):
        import builtins

        from app.services.invoice import render_invoice_pdf
        from tests.conftest import make_subscription

        sid, cid, plan, uid = _setup(app)
        with app.app_context():
            sub_id = make_subscription(app, uid, plan, cid, price=80.0, status="active")
            real_import = builtins.__import__

            def fake_import(name, *args, **kwargs):
                if name == "xhtml2pdf":
                    raise ImportError("forced for test")
                return real_import(name, *args, **kwargs)

            with app.test_request_context("/"):
                with patch.object(builtins, "__import__", fake_import):
                    assert render_invoice_pdf(sub_id) is None
