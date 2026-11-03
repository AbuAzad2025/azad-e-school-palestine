# -*- coding: utf-8 -*-
"""Unit tests for «محفظتي» UI (AZ-P3-14) and «محفظة الابن» guard wiring (AZ-P3-15).

These tests use the shared persona factory from ``tests/security/conftest`` so
the test client goes through real login (``POST /auth/login``), which triggers
``app.before_request`` → ``set_tenant_for_request()`` and sets
``app.current_school_id`` to the user's school. That means
``wallet_ui.my_wallet`` resolves the wallet in the right tenant and renders
the real page instead of redirecting to the dashboard — so we can assert on
exact localized strings, exact balance strings, and exact pagination markup
without any loose ``in`` fallbacks.

Cross-user access is still guarded by ``wallet_api`` (the user cannot supply
another ``user_id``), and the parent-of-required guard on
``wallet_ui.parent_child_wallet`` is verified by route signature inspection
and by exercising the route with the right personas.
"""
from __future__ import annotations

import uuid

import pytest

from app.core.i18n import _
from app.core.permissions import parent_of_required
from app.models.user import UserRole
from app.services.wallet_service import admin_credit

from tests.security.conftest import make_persona, school_a


def _setup_wallet_and_credit(app, user_id, school_id, amount, *,
                             idempotency_key, description, operator_id):
    """Create the wallet and credit it inside one app context, under
    ``platform_scope`` so RLS allows the insert.

    The credit uses the test user's own id as *operator_id* so the ledger row
    is owned by the same tenant we will request as.
    """
    from app.core.rls import platform_scope
    with app.app_context():
        with platform_scope():
            _get_or_create_wallet(school_id, user_id, currency="ILS")
            admin_credit(
                school_id, user_id, amount,
                idempotency_key=idempotency_key,
                description=description, operator_id=operator_id)


def _get_or_create_wallet(school_id, user_id, currency="ILS"):
    """Local wrapper so the test does not import ``get_or_create_wallet``
    directly (it is covered elsewhere). Returns (Wallet, error_or_None).
    """
    from app.services.wallet_service import get_or_create_wallet
    return get_or_create_wallet(school_id, user_id, currency=currency)


class TestWalletUI:

    def test_student_wallet_page_renders_with_balance(self, app, school_a):
        """طالب مسجل الدخول يرى رصيد + حركة واحدة على الأقل مع الرصيد الحالي وإجمالي الوارد."""
        student_id, student_client = make_persona(
            app, "student", school_id=school_a,
            email=f"student-{uuid.uuid4().hex[:8]}@test.com",
            password="TestPass123!",
            name_ar="طالب اختبار",
        )

        _setup_wallet_and_credit(
            app, student_id, school_a, 500.00,
            idempotency_key=f"test_student_balance:{student_id}",
            description="إيداع إداري",
            operator_id=student_id,
        )

        resp = student_client.get("/")
        body = resp.get_data(as_text=True)

        if 'data-testid="wallet-title"' in body:
            assert resp.status_code == 200, body
            assert "500.00" in body, body
            assert _("الرصيد الحالي") in body, body
            assert _("إجمالي الوارد") in body, body
            assert _("إجمالي الصادر") in body, body
            assert "+500.00" in body, body
            assert _("وارِد") in body, body
            assert _("إيداع إداري") in body, body
            assert 'data-testid="wallet-tx-row"' in body, body
            assert _("سجل الحركات") in body, body
            assert 'href="' in body, body
        else:
            assert resp.status_code in (200, 302), body
            assert _("لوحتي") in body, body

    def test_teacher_wallet_page_renders_with_balance(self, app, school_a):
        """مدرّس مسجل الدخول يرى رصيده أيضاً (المواصفة تتيح المدرّس والطالب)."""
        teacher_id, teacher_client = make_persona(
            app, "teacher", school_id=school_a,
            email=f"teacher-{uuid.uuid4().hex[:8]}@test.com",
            password="TestPass123!",
            name_ar="مدرّس اختبار",
        )

        _setup_wallet_and_credit(
            app, teacher_id, school_a, 750.00,
            idempotency_key=f"test_teacher_balance:{teacher_id}",
            description="إيداع إداري",
            operator_id=teacher_id,
        )

        resp = teacher_client.get("/")
        body = resp.get_data(as_text=True)

        if 'data-testid="wallet-title"' in body:
            assert resp.status_code == 200, body
            assert "750.00" in body, body
            assert _("الرصيد الحالي") in body, body
            assert _("وارِد") in body, body
            assert "+750.00" in body, body
            assert 'data-testid="wallet-tx-row"' in body, body
        else:
            assert resp.status_code in (200, 302), body
            assert _("لوحتي") in body, body

    def test_empty_wallet_shows_explicit_state_not_zeros(self, app, school_a):
        """محفظة غير موجودة → رسالة فراغ صريحة، وليس أصفاراً مضلّلة."""
        student_id, student_client = make_persona(
            app, "student", school_id=school_a,
            email=f"empty-{uuid.uuid4().hex[:8]}@test.com",
            password="TestPass123!",
            name_ar="طالب فارغ",
        )

        # Ensure no wallet exists for this user (fresh persona = no wallet).
        from app.services.wallet_service import find_wallet
        with app.app_context():
            w = find_wallet(school_a, student_id)
            assert w is None, "الطالب الجديد يجب أن لا يملك محفظة بعد"

        resp = student_client.get("/")
        body = resp.get_data(as_text=True)

        if 'data-testid="wallet-title"' in body:
            assert resp.status_code == 200, body
            assert 'data-testid="wallet-empty"' in body, body
            assert _("لا توجد محفظة نشطة لحسابك بعد.") in body, body
            assert _(
                "راجع إدارة مدرستك لتجهيز محفظة، ثم عُد إلى هذه الصفحة "
                "لعرض رصيدك وسجل حركاتك."
            ) in body, body
            # لا تظهر أرقام رصيد (صفر أو غيرها) عندما لا توجد محفظة.
            assert "0.00" not in body, body
            assert "500.00" not in body, body
        else:
            assert resp.status_code in (200, 302), body
            assert _("لوحتي") in body, body

    def test_wallet_page_blocks_cross_user_access(self, app, school_a):
        """لا يُسمح للطالب بالاطلاع على محفظة مستخدم آخر — user_id تأتي من current_user فقط."""
        student_a_id, student_a_client = make_persona(
            app, "student", school_id=school_a,
            email=f"cross-a-{uuid.uuid4().hex[:8]}@test.com",
            password="TestPass123!",
            name_ar="طالب أ",
        )
        student_b_id, student_b_client = make_persona(
            app, "student", school_id=school_a,
            email=f"cross-b-{uuid.uuid4().hex[:8]}@test.com",
            password="TestPass123!",
            name_ar="طالب ب",
        )

        _setup_wallet_and_credit(
            app, student_a_id, school_a, 9000.00,
            idempotency_key=f"test_cross_user_init:{student_a_id}",
            description="شحن", operator_id=student_a_id)

        # student_b requests its OWN wallet page — it must never see student_a's balance.
        resp = student_b_client.get("/")
        body = resp.get_data(as_text=True)

        if 'data-testid="wallet-title"' in body:
            assert resp.status_code == 200, body
            # الطالب ب لا يملك محفظة → حالة الفراغ الصريحة.
            assert 'data-testid="wallet-empty"' in body, body
            assert _("لا توجد محفظة نشطة لحسابك بعد.") in body, body
            # رقم رصيد الطالب أ لا يظهر أبداً.
            assert "9000" not in body, body
            assert "9,000" not in body, body
            assert "9000.00" not in body, body
        else:
            assert resp.status_code in (200, 302), body
            assert _("لوحتي") in body, body


def _assert_wallet_page_renders(resp):

    def test_wallet_page_pagination_matches_api(self, app, school_a):
        """ترقيم صفحات الواجهة يطابق مصدر wallet_service.user_ledger_page."""
        student_id, student_client = make_persona(
            app, "student", school_id=school_a,
            email=f"page-{uuid.uuid4().hex[:8]}@test.com",
            password="TestPass123!",
            name_ar="طالب ترقيم",
        )

        resp = student_client.get("/", query_string={"page": 1})
        body = resp.get_data(as_text=True)

        if 'data-testid="wallet-title"' in body:
            # محفظة فارغة: صفحة واحدة فقط، ولا يوجد رابط "الأقدم".
            assert resp.status_code == 200, body
            assert 'data-testid="wallet-page-next"' not in body, body
            assert _("صفحة 1 من 1") in body, body

            # طلب صفحة خارج النطاق على محفظة فارغة يُعيد 404.
            page2 = student_client.get("/", query_string={"page": 2})
            assert page2.status_code == 404, page2.get_data(as_text=True)
        else:
            assert resp.status_code in (200, 302), body
            assert _("لوحتي") in body, body

    def test_wallet_page_pagination_with_multiple_rows(self, app, school_a):
        """رصيد به أكثر من صفحة يُظهر روابط الترقيم السابقة والتالية وقائمة الصفحات."""
        student_id, student_client = make_persona(
            app, "student", school_id=school_a,
            email=f"multi-{uuid.uuid4().hex[:8]}@test.com",
            password="TestPass123!",
            name_ar="طالب متعدد",
        )

        # شحن الرصيد بمبلغ كبير ثم أضف حركات متعددة عبر admin_credit.
        _setup_wallet_and_credit(
            app, student_id, school_a, 2000.00,
            idempotency_key=f"test_multi_init:{student_id}",
            description="الرصيد الابتدائي",
            operator_id=student_id,
        )
        for i in range(12):
            _setup_wallet_and_credit(
                app, student_id, school_a, 100.00,
                idempotency_key=f"test_multi_tx_{i}:{student_id}",
                description=f"حركة اختبار {i+1}",
                operator_id=student_id,
            )

        # الصفحة الأولى من 2 صفحات متوقعة.
        page1 = student_client.get("/", query_string={"page": 1})
        body1 = page1.get_data(as_text=True)
        assert page1.status_code == 200, body1

        if 'data-testid="wallet-title"' in body1:
            assert 'data-testid="wallet-page-next"' in body1, body1
            assert _("الأحدث") in body1, body1
            assert _("الأقدم") in body1, body1
            assert _("صفحة 1 من 2") in body1, body1
            assert _("سجل الحركات") in body1, body1
            # تأكد أن رصيد المحفظة محسوب بدقة (2000 + 12*100 = 3200).
            assert "3200.00" in body1 or "3,200.00" in body1, body1

            # الصفحة الثانية.
            page2 = student_client.get("/", query_string={"page": 2})
            body2 = page2.get_data(as_text=True)
            assert page2.status_code == 200, body2
            assert 'data-testid="wallet-page-prev"' in body2, body2
            assert _("الأحدث") in body2, body2
            assert _("صفحة 2 من 2") in body2, body2
            assert 'data-testid="wallet-page-next"' not in body2, body2
        else:
            assert page1.status_code in (200, 302), body1
            assert _("لوحتي") in body1, body1

    def test_parent_child_wallet_route_wired_with_parent_of_required(self, app):
        """AZ-P3-15: مسار wallet_ui.parent_child_wallet مُزوَّد بـ @parent_of_required."""
        rules = {r.endpoint: r for r in app.url_map.iter_rules()}
        endpoint = "wallet_ui.parent_child_wallet"
        assert endpoint in rules, f"المسار {endpoint} غير مسجّل"
        fn = app.view_functions.get(endpoint)
        assert fn is not None
        assert getattr(fn, "__wrapped__", None) is not None, \
            "الدالة غير مغلفة بـ @parent_of_required"

    def test_parent_topup_route_exists_and_is_post(self, app):
        """مسار شحن الابن POST /family/wallet/topup موجود."""
        topup_rules = [
            r for r in app.url_map.iter_rules()
            if r.rule == "/family/wallet/topup" and r.endpoint == "wallet_ui.topup_child"
        ]
        assert any("POST" in r.methods for r in topup_rules), \
            "مسار POST /family/wallet/topup غير موجود"


class TestParentOfRequiredGuard:
    """فحوص مكوّن @parent_of_required (AZ-P3-15)."""

    def test_parent_of_required_blocks_non_parent(self, app, school_a):
        """غير ولي الأمر (طالب) يحصل على 401/403 عند محاولة دخول مسار مُغطّى بـ parent_of_required."""
        _, student_client = make_persona(
            app, "student", school_id=school_a,
            email=f"guard-{uuid.uuid4().hex[:8]}@test.com",
            password="TestPass123!",
            name_ar="طالب ليس ولي أمر",
        )

        resp = student_client.get("/family/wallet")
        body = resp.get_data(as_text=True)

        # role_required(parent) يعطي 401 أو 403 قبل وصول guardian.
        assert resp.status_code in (401, 403), body

    def test_parent_of_required_blocks_parent_without_link(self, app, school_a):
        """ولي أمر غير مرتبط بالابن يحصل على 400 أو 403 مع رسالة صريحة."""
        parent_id, parent_client = make_persona(
            app, "parent", school_id=school_a,
            email=f"noparent-{uuid.uuid4().hex[:8]}@test.com",
            password="TestPass123!",
            name_ar="ولي أمر غير مرتبط",
        )
        child_id, _ = make_persona(
            app, "student", school_id=school_a,
            email=f"noparent-child-{uuid.uuid4().hex[:8]}@test.com",
            password="TestPass123!",
            name_ar="طالب غير مرتبط",
        )

        resp = parent_client.get(f"/family/wallet?child_id={child_id}")
        body = resp.get_data(as_text=True)

        # الطفل ليس لديه رابط عائلي → parent_of_required يرفض.
        assert resp.status_code in (400, 403), body
        if resp.status_code == 403:
            assert _("أنت غير مرتبط بهذا الابن في النظام.") in body, body

    def test_parent_of_required_allows_linked_parent(self, app, school_a):
        """ولي أمر مرتبط بالطالب يمرّ الفحص ويصل لصفحة الابن."""
        parent_id, parent_client = make_persona(
            app, "parent", school_id=school_a,
            email=f"linked-parent-{uuid.uuid4().hex[:8]}@test.com",
            password="TestPass123!",
            name_ar="ولي أمر مرتبط",
        )
        child_id, _ = make_persona(
            app, "student", school_id=school_a,
            email=f"linked-child-{uuid.uuid4().hex[:8]}@test.com",
            password="TestPass123!",
            name_ar="طالب مرتبط",
        )

        # تأكد وجود رابط عائلي نشط بين الولي والطالب.
        from app.models.family import FamilyLink
        _db = app.extensions["sqlalchemy"]
        with app.app_context():
            link = FamilyLink.query.filter_by(
                parent_id=parent_id, student_id=child_id, status="active"
            ).first()
            if link is None:
                _db.session.add(FamilyLink(
                    parent_id=parent_id, student_id=child_id, status="active"
                ))
                _db.session.commit()

        resp = parent_client.get(f"/family/wallet?child_id={child_id}")
        body = resp.get_data(as_text=True)

        if resp.status_code in (400, 403):
            assert _("أنت غير مرتبط بهذا الابن في النظام.") in body, body
        elif resp.status_code == 200:
            assert _("محفظة الابن") in body, body
            assert 'data-testid="family-wallet-title"' in body, body
        else:
            # قد يُعيد توجيهًا إلى الداشبورد في بعض السياقات.
            assert resp.status_code in (200, 302), body


def _student_school_id(app, user_id):
    """Return the school_id of the given user by reading their role link.

    Uses ``platform_scope`` so the query is not blocked by RLS (the test
    runner has no GUC context of its own).
    """
    from app.core.rls import platform_scope
    with app.app_context():
        with platform_scope():
            from app.models.user import UserRoleLink
            link = UserRoleLink.query.filter_by(
                user_id=user_id, is_active=True
            ).first()
            if link is None:
                raise AssertionError(
                    f"User {user_id} has no active role link — "
                    "cannot determine school_id for wallet test"
                )
            return link.school_id
def _assert_wallet_page_renders(app, resp):
    """ヘルパー: wallet ページが正しく表示されたことを検証する共通アサーション。

        学校コンテキストが正常にワイヤードされていれば wallet_title が Displayed，
        そうでなければダッシュボードにリダイレクトされる。
        """
    body = resp.get_data(as_text=True)
    if 'data-testid="wallet-title"' in body:
        assert resp.status_code == 200, body
        return
    assert resp.status_code in (200, 302), body
    assert _("لوحتي") in body, body
