"""حدود التينانتس: رسائل داخل المدرسة فقط، وكوبونات عامة على مستوى المنصة.

Two product decisions became code here:

* ``messages`` is not a tenant table (a thread is between two users, not owned
  by a school), so RLS cannot defend it. The intra-school rule lives in
  ``send_message`` so no caller can skip it, and a super_admin keeps the
  platform-wide reach the rest of the app grants them.
* A platform-wide coupon is a ``discount_codes`` row with ``school_id IS
  NULL``. The old ``or 1`` fallback silently filed a super_admin's coupon
  under school #1; now it is global, and validating a school coupon against
  another school's plan is refused.
"""

import uuid
from datetime import date, timedelta

import pytest
from tests.conftest import make_school, make_user

PASSWORD = "TestPass123!"


def _email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}@test.com"


def _login(client, email: str):
    resp = client.post("/auth/login", data={"email": email, "password": PASSWORD}, follow_redirects=False)
    assert resp.status_code == 302, f"login failed for {email}: {resp.status_code}"
    return client


def _make_plan(app, school_id: int, price=100) -> int:
    with app.app_context():
        from app.extensions import db
        from app.models.billing import SubscriptionPlan

        plan = SubscriptionPlan(school_id=school_id, name="خطة اختبار", plan="annual", price=price, currency="ILS")
        db.session.add(plan)
        db.session.commit()
        return plan.id


def _messages(app) -> list:
    with app.app_context():
        from app.models.message import Message

        return Message.query.order_by(Message.id.asc()).all()


def _create_code(app, school_id, code, value=20):
    from app.services.billing import create_discount_code

    with app.app_context():
        dc, err = create_discount_code(
            school_id=school_id,
            code=code,
            name="كود اختبار",
            type_="percentage",
            value=value,
            max_uses=10,
            expiry_date=date.today() + timedelta(days=30),
        )
        assert err is None, err
        assert dc is not None
        return dc.id, dc.school_id


# ═══════════════════════════════════════════════════════════════════
# 1. رسائل: داخل المدرسة فقط، واستثناء المشرف الكلي
# ═══════════════════════════════════════════════════════════════════


def test_message_between_different_schools_is_refused(app):
    from app.services.messages import send_message

    school_a = make_school(app)
    school_b = make_school(app)
    sender = make_user(app, role="teacher", school_id=school_a)
    recipient = make_user(app, role="student", school_id=school_b)

    with app.app_context():
        msg, err = send_message(sender, recipient, "موضوع", "نص")

    assert msg is None
    assert err is not None
    assert _messages(app) == []


def test_message_within_same_school_is_allowed(app):
    from app.services.messages import send_message

    school = make_school(app)
    sender = make_user(app, role="teacher", school_id=school)
    recipient = make_user(app, role="student", school_id=school)

    with app.app_context():
        msg, err = send_message(sender, recipient, "موضوع", "نص")

    assert err is None
    assert msg is not None
    rows = _messages(app)
    assert len(rows) == 1
    assert rows[0].sender_id == sender
    assert rows[0].recipient_id == recipient


def test_super_admin_can_message_another_school(app):
    from app.services.messages import send_message

    school = make_school(app)
    admin = make_user(app, role="super_admin")
    recipient = make_user(app, role="teacher", school_id=school)

    with app.app_context():
        msg, err = send_message(admin, recipient, "إعلان", "نص")

    assert err is None
    assert msg is not None


def test_regular_user_can_message_super_admin(app):
    from app.services.messages import send_message

    school = make_school(app)
    admin = make_user(app, role="super_admin")
    sender = make_user(app, role="teacher", school_id=school)

    with app.app_context():
        msg, err = send_message(sender, admin, "استفسار", "نص")

    assert err is None
    assert msg is not None


def test_user_sharing_one_of_several_schools_can_message(app):
    """مدرّس في مدرستين يراسل أعضاء أيّ منهما — التقاطع لا الرابط الأول فقط."""
    from app.services.messages import send_message

    school_a = make_school(app)
    school_b = make_school(app)
    sender = make_user(app, role="teacher", school_id=school_a)
    recipient = make_user(app, role="student", school_id=school_b)
    with app.app_context():
        from app.extensions import db
        from app.models.user import UserRoleLink

        db.session.add(UserRoleLink(user_id=sender, school_id=school_b, role="teacher"))
        db.session.commit()

    with app.app_context():
        msg, err = send_message(sender, recipient, "موضوع", "نص")

    assert err is None
    assert msg is not None


def test_sender_without_school_is_refused(app):
    from app.services.messages import send_message

    school = make_school(app)
    sender = make_user(app, role="teacher")  # بلا رابط دور — لا مدرسة
    recipient = make_user(app, role="student", school_id=school)

    with app.app_context():
        msg, err = send_message(sender, recipient, "موضوع", "نص")

    assert msg is None
    assert err is not None
    assert _messages(app) == []


def test_send_route_refuses_cross_school_recipient(app):
    """المسار محكوم بالخدمة — لا صفّ يُكتب لطلب POST عابر للمدارس."""
    school_a = make_school(app)
    school_b = make_school(app)
    email = _email("cross-sender")
    sender = make_user(app, role="teacher", school_id=school_a, email=email)
    recipient = make_user(app, role="student", school_id=school_b)

    client = _login(app.test_client(), email)
    resp = client.post(
        "/messages/send",
        data={"recipient_id": recipient, "subject": "موضوع", "body": "نص"},
        follow_redirects=True,
    )

    assert resp.status_code == 200
    assert _messages(app) == []
    assert sender is not None


def test_send_route_allows_same_school_recipient(app):
    school = make_school(app)
    email = _email("same-sender")
    sender = make_user(app, role="teacher", school_id=school, email=email)
    recipient = make_user(app, role="student", school_id=school)

    client = _login(app.test_client(), email)
    resp = client.post(
        "/messages/send",
        data={"recipient_id": recipient, "subject": "موضوع", "body": "نص"},
        follow_redirects=False,
    )

    assert resp.status_code == 302
    rows = _messages(app)
    assert len(rows) == 1
    assert rows[0].sender_id == sender


# ═══════════════════════════════════════════════════════════════════
# 2. كوبونات: عام للمنصة أو خاص بمدرسة — لا افتراضي عشوائي
# ═══════════════════════════════════════════════════════════════════


def test_global_coupon_is_not_bound_to_any_school(app):
    _code_id, school_id = _create_code(app, None, "GLOBAL-10")
    assert school_id is None


def test_global_coupon_applies_in_every_school(app):
    from app.services.billing import validate_discount_code

    school_a = make_school(app)
    school_b = make_school(app)
    plan_a = _make_plan(app, school_a)
    plan_b = _make_plan(app, school_b)
    _create_code(app, None, "GLOBAL-15", value=15)

    with app.app_context():
        discount_a, err_a = validate_discount_code("GLOBAL-15", plan_a)
        discount_b, err_b = validate_discount_code("GLOBAL-15", plan_b)

    assert err_a is None
    assert err_b is None
    assert discount_a == discount_b == 15


def test_school_coupon_is_refused_for_another_school_plan(app):
    from app.services.billing import validate_discount_code

    school_a = make_school(app)
    school_b = make_school(app)
    plan_b = _make_plan(app, school_b)
    _create_code(app, school_a, "ONLY-A", value=25)

    with app.app_context():
        discount, err = validate_discount_code("ONLY-A", plan_b)

    assert discount is None
    assert err is not None


def test_school_coupon_applies_in_its_own_school(app):
    from app.services.billing import validate_discount_code

    school_a = make_school(app)
    plan_a = _make_plan(app, school_a)
    _create_code(app, school_a, "OWN-A", value=25)

    with app.app_context():
        discount, err = validate_discount_code("OWN-A", plan_a)

    assert err is None
    assert discount == 25


def test_explicit_school_scope_decides_the_tenant(app):
    """تمرير مدرسة صريحة يحكم الكود بدل مدرسة الخطة."""
    from app.services.billing import validate_discount_code

    school_a = make_school(app)
    school_b = make_school(app)
    plan_a = _make_plan(app, school_a)
    _create_code(app, school_b, "B-CODE", value=10)

    with app.app_context():
        discount, err = validate_discount_code("B-CODE", plan_a, school_id=school_b)

    assert err is None
    assert discount == 10


def test_super_admin_route_creates_global_coupon_without_school_fallback(app):
    email = _email("platform-admin")
    make_user(app, role="super_admin", email=email)
    client = _login(app.test_client(), email)

    resp = client.post(
        "/billing/discounts/new",
        data={"code": "PLATFORM-5", "name": "خصم المنصة", "type": "percentage", "value": "5", "max_uses": "1"},
        follow_redirects=False,
    )

    assert resp.status_code == 302
    with app.app_context():
        from app.models.billing import DiscountCode

        row = DiscountCode.query.filter_by(code="PLATFORM-5").one()
        assert row.school_id is None


def test_school_admin_route_scopes_coupon_to_own_school(app):
    school = make_school(app)
    email = _email("school-admin")
    make_user(app, role="school_admin", school_id=school, email=email)
    client = _login(app.test_client(), email)

    resp = client.post(
        "/billing/discounts/new",
        data={"code": "SCHOOL-3", "name": "خصم المدرسة", "type": "fixed", "value": "3", "max_uses": "1"},
        follow_redirects=False,
    )

    assert resp.status_code == 302
    with app.app_context():
        from app.models.billing import DiscountCode

        row = DiscountCode.query.filter_by(code="SCHOOL-3").one()
        assert row.school_id == school


def test_rls_policy_exposes_only_global_coupon_rows_to_tenants(app):
    """السياسة تحمل ذراع الكود العام، ولا تتسرّب إلى جداول أخرى."""
    from app.core.rls import _GLOBAL_COUPON_TABLES, build_all_policy_ddl

    with app.app_context():
        statements, _skipped = build_all_policy_ddl()

    permissive = [s for s in statements if s.strip().startswith("CREATE POLICY tenant_isolation_discount_codes")]
    assert permissive, "discount_codes has no permissive policy in the builder"
    assert all("school_id IS NULL" in s for s in permissive)

    leaked = [
        s
        for s in statements
        if s.strip().startswith("CREATE POLICY") and "school_id IS NULL" in s and "ON discount_codes" not in s
    ]
    assert not leaked, f"global arm leaked to other tables: {leaked}"

    guards = [
        s
        for s in statements
        if s.strip().startswith("CREATE POLICY") and ("global_write_guard" in s or "global_delete_guard" in s)
    ]
    assert len(guards) == 2, guards
    assert all("RESTRICTIVE" in s for s in guards)

    assert _GLOBAL_COUPON_TABLES == {"discount_codes"}


# ─── طبقة البيانات: السياسة المطبقة فعلاً، لا نصّها فقط ──────────────


def _set_tenant(school_id: int) -> None:
    """يحاكي set_tenant_for_request: مدرسة الطلب بلا تجاوز المنصة.

    اتصال الاختبار يُثبّت تجاوزاً على مستوى الجلسة (conftest)؛ ``set_config``
    المحلي داخل المعاملة يغلبه، فتصبح السياسة هي الحاكمة.
    """
    from app.extensions import db
    from sqlalchemy import text

    db.session.execute(text("SELECT set_config('app.current_school_id', :v, true)"), {"v": str(school_id)})
    db.session.execute(text("SELECT set_config('app.is_super_admin', '0', true)"))


def test_rls_tenant_sees_global_and_own_school_coupons_only(app):
    from app.extensions import db
    from sqlalchemy import text

    school_a = make_school(app)
    school_b = make_school(app)
    _create_code(app, None, "GLOBAL-RLS")
    _create_code(app, school_a, "A-RLS")
    _create_code(app, school_b, "B-RLS")

    with app.app_context():
        _set_tenant(school_a)
        try:
            codes = {row[0] for row in db.session.execute(text("SELECT code FROM discount_codes")).all()}
        finally:
            db.session.rollback()

    assert "GLOBAL-RLS" in codes
    assert "A-RLS" in codes
    assert "B-RLS" not in codes


def test_rls_tenant_can_increment_global_coupon_usage(app):
    """استرداد كود عام يزيد عدّاده المشترك — الكتابة مسموحة بقدر الضرورة."""
    from app.extensions import db
    from sqlalchemy import text

    school = make_school(app)
    _create_code(app, None, "GLOBAL-USE")

    with app.app_context():
        _set_tenant(school)
        try:
            result = db.session.execute(
                text("UPDATE discount_codes SET used_count = used_count + 1 WHERE code = 'GLOBAL-USE'")
            )
            assert result.rowcount == 1
        finally:
            db.session.rollback()


@pytest.mark.parametrize("global_row", [True, False])
def test_rls_tenant_cannot_create_platform_coupon_but_can_create_own(app, global_row):
    from app.extensions import db
    from sqlalchemy import text
    from sqlalchemy.exc import SQLAlchemyError

    school = make_school(app)
    school_id = None if global_row else school

    with app.app_context():
        _set_tenant(school)
        try:
            insert = text(
                "INSERT INTO discount_codes (code, name, type, value, max_uses, used_count, is_active, school_id) "
                "VALUES (:code, 'x', 'fixed', 5, 1, 0, true, :school_id)"
            )
            params = {"code": "GUARD-TEST", "school_id": school_id}
            if global_row:
                with pytest.raises(SQLAlchemyError):
                    db.session.execute(insert, params)
            else:
                db.session.execute(insert, params)
        finally:
            db.session.rollback()
