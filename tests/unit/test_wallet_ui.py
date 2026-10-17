"""AZ-P3-14 — «محفظتي»: صفحة محفظة جانبية للطالب/المعلم (كانت API حصراً).

معايير القبول المُغطّاة (docs/ACTIONABLE_WORK_ITEMS.md §AZ-P3-14):
1. طالب/معلم يريان الرصيد والسجل مع ترقيم صفحات.
2. مستخدم بلا محفظة يرى حالة فراغ صريحة لا أصفاراً.
3. لا حركات لمستخدم آخر (الاستعلام ملتصق بالجلسة؛ `user_id` من الطلب مُهمَل).
4. لا وصول/رابط لولي الأمر هنا (يُغطّى في AZ-P3-15).
"""

from __future__ import annotations

from decimal import Decimal

from tests.conftest import make_school
from tests.unit.test_push_round_i import persona

PASSWORD = "TestPass123!"


class TestWalletEmptyState:
    def test_student_without_wallet_sees_explicit_empty_state(self, app):
        sid = make_school(app)
        uid, client = persona(app, role="student", school_id=sid)
        resp = client.get("/wallet")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "wallet-empty" in body
        assert "لا توجد محفظة نشطة لحسابك بعد." in body
        # لا أصفار مضلّلة: بطاقات الملخّص لا تُعرض بلا محفظة
        assert "wallet-summary" not in body

    def test_wallet_created_after_deposit_no_longer_empty(self, app):
        sid = make_school(app)
        uid, client = persona(app, role="student", school_id=sid)
        from app.services import wallet_service

        with app.app_context():
            wallet_service.admin_deposit(
                school_id=sid,
                target_user_id=uid,
                amount=Decimal("50.00"),
                operator_id=None,
                note="تعبة أولى",
            )
        resp = client.get("/wallet")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "wallet-empty" not in body
        assert "wallet-summary" in body
        assert "تعبة أولى" in body


class TestWalletSummaryAndRows:
    def _funded_student(self, app, sid):
        from app.services import wallet_service

        uid, client = persona(app, role="student", school_id=sid)
        with app.app_context():
            # ثلاث إيداعات = ثلاث حركات وارِدة
            for amount in ("100.00", "50.00", "25.50"):
                wallet_service.admin_deposit(
                    school_id=sid,
                    target_user_id=uid,
                    amount=Decimal(amount),
                    operator_id=None,
                    note=f"تعبة {amount}",
                )
        return uid, client

    def test_balance_and_direction_labels(self, app):
        sid = make_school(app)
        uid, client = self._funded_student(app, sid)
        body = client.get("/wallet").get_data(as_text=True)
        assert "175.50" in body
        assert "وارِد" in body
        assert "إيداع إداري" in body
        assert "سجل الحركات" in body
        # كل صف عناصره مكتملة التسميات
        assert body.count("wallet-tx-row") == 3

    def test_outgoing_transfer_marked_out(self, app):
        sid = make_school(app)
        uid, client = self._funded_student(app, sid)
        teacher_id, teacher_email = None, None
        from tests.unit.test_push_round_i import mk

        teacher_id, teacher_email = mk(app, role="teacher", school_id=sid)

        from app.services import wallet_service

        with app.app_context():
            wallet_service.admin_deposit(school_id=sid, target_user_id=teacher_id, amount=Decimal("10.00"))
            transfer, err = wallet_service.process_transfer(
                school_id=sid,
                source_user_id=uid,
                dest_user_id=teacher_id,
                amount=Decimal("20.00"),
                idempotency_key=f"test-transfer-{uid}",
                description="دفع رسوم",
            )
            assert err is None, err

        body = client.get("/wallet").get_data(as_text=True)
        assert "صارِد" in body
        assert "دفع رسوم" in body
        # الرصيد بعد الصادر: 175.50 - 20 = 155.50
        assert "155.50" in body

    def test_pagination_next_and_older_page(self, app):
        sid = make_school(app)
        uid, client = self._funded_student(app, sid)
        from app.services import wallet_service

        with app.app_context():
            # 10 حركات إضافية → الإجمالي 13 > حجم الصفحة (10)
            for i in range(10):
                wallet_service.admin_deposit(
                    school_id=sid,
                    target_user_id=uid,
                    amount=Decimal(f"{i + 1}.00"),
                    operator_id=None,
                    note=f"تعبة إضافية {i}",
                )
        first = client.get("/wallet").get_data(as_text=True)
        assert "wallet-page-next" in first
        assert "wallet-page-prev" not in first
        second = client.get("/wallet", query_string={"page": 2}).get_data(as_text=True)
        assert "wallet-page-prev" in second
        assert "wallet-page-next" not in second  # آخر صفحة لا تملك تالياً
        assert second.count("wallet-tx-row") == 3  # ذيل السجل (13 صفًا: 10 + 3)
        assert "صفحة 2 من 2" in second

    def test_page_beyond_range_is_404(self, app):
        sid = make_school(app)
        uid, client = self._funded_student(app, sid)
        resp = client.get("/wallet", query_string={"page": 99})
        assert resp.status_code == 404


class TestWalletAccess:
    def test_anonymous_is_rejected(self, app):
        # بلا تسجيل دخول — 401 من role_required
        resp = app.test_client().get("/wallet")
        assert resp.status_code == 401

    def test_parent_gets_403_on_route(self, app):
        sid = make_school(app)
        uid, client = persona(app, role="parent", school_id=sid)
        resp = client.get("/wallet")
        assert resp.status_code == 403

    def test_parent_navbar_has_no_wallet_link(self, app):
        # معيار (4): لا رابط محفظة لولي الأمر في هذه الواجهة
        sid = make_school(app)
        uid, client = persona(app, role="parent", school_id=sid)
        resp = client.get("/auth/dashboard", follow_redirects=True)
        body = resp.get_data(as_text=True)
        assert "nav-my-wallet" not in body

    def test_student_and_teacher_nav_link_present(self, app):
        sid = make_school(app)
        for role in ("student", "teacher"):
            uid, client = persona(app, role=role, school_id=sid)
            resp = client.get("/auth/dashboard", follow_redirects=True)
            assert 'data-testid="nav-my-wallet"' in resp.get_data(as_text=True), role

    def test_role_forcing_user_id_param_is_ignored(self, app):
        """معيار (3): لا `user_id` من الطلب — الاستعلام دائماً للجلسة."""
        from app.services import wallet_service

        sid = make_school(app)
        attacker_uid, attacker_client = persona(app, role="student", school_id=sid)
        victim_uid, _victim = persona(app, role="student", school_id=sid)
        with app.app_context():
            wallet_service.admin_deposit(
                school_id=sid, target_user_id=victim_uid, amount=Decimal("500.00"), note="سرية"
            )
        resp = attacker_client.get("/wallet", query_string={"user_id": victim_uid})
        body = resp.get_data(as_text=True)
        assert resp.status_code == 200
        assert "سرية" not in body
        assert attacker_client.get("/wallet").get_data(as_text=True).count("wallet-tx-row") == 0

    def test_user_without_school_gets_flash_and_redirect(self, app):
        make_school(app)  # تُنشأ مدرسة لكن هذا المستخدم بلا رابط
        uid, client = persona(app, role="student", school_id=None)
        resp = client.get("/wallet", follow_redirects=True)
        body = resp.get_data(as_text=True)
        assert "لا توجد مدرسة نشطة لحسابك لعرض محفظتها." in body
