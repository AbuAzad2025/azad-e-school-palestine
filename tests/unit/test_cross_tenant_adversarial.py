"""اختبار اختراق عدائي لعزل المستأجرين (Cross-Tenant Adversarial).

الغرض: إثبات أن مستخدم مدرسة (A) لا يقرأ ولا يعدّل ولا يحذف بيانات مدرسة (B)
بحقن المعرّفات في المسارات، ولا باستعلام «غير مُقيَّد» على مستوى ORM/SQL.
الدفاع طبقتان، وكلتاهما مُختبَرة هنا:

  1. طبقة التطبيق: ``role_required`` وحروسه المركّبة (class_access_required،
     class_teach_required، parent_of_required) وفحوص ``tenant_scope`` /
     ``assert_*_access`` — تجيب 403 أو 404 بلا أي بيانات أجنبية.
  2. طبقة قاعدة البيانات: سياسات RLS (``USING`` للقراءة و``WITH CHECK``
     للكتابة) — تُسقط حتى الاستعلام الخام الذي لا يذكر ``school_id``.

معيار النجاح لكل محاولة: رمز 403/404 (أو 200 بقائمة فارغة في مسارات القوائم)،
و«صفر بايت» من بيانات المستأجر الآخر في الجسم. لذلك يحمل كل مستأجر في هذا
الملف علامات مميّزة (أسماء المدرسة/الصف/الدرس/الطالب ومقادير مالية خاصة به
وحده) نفتّش عنها في كل ردّ عابر للتينانتس.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import sqlalchemy
from app.extensions import db
from app.models.billing import ManualPayment, Subscription, SubscriptionPlan
from app.models.class_room import ClassMember, ClassRoom
from app.models.content import Lesson
from app.models.family import FamilyLink
from app.models.school import Grade, School, Subject
from app.models.user import User, UserApprovalStatus, UserRole, UserRoleLink
from app.models.wallet import Wallet, WalletTransaction
from sqlalchemy import text

PASSWORD = "TestPass123!"

# مقادير مالية لكل تينانت: رقم مميّز يعني أن ظهوره في ردّ الآخر تسرّب مؤكّد
# (لا يشتبه مع مبلغ التينانت المهاجم نفسه).
_AMOUNTS: dict[str, dict[str, str]] = {
    "a": {"plan": "1234.00", "wallet": "1122.00"},
    "b": {"plan": "5678.00", "wallet": "4321.00"},
}


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def _build_tenant(app, tag: str) -> dict:
    """مستأجر كامل: مدرسة/صف/درس/اشتراك/فاتورة/محفظة/دفتر + أربعة أدوار."""
    marker = f"{tag.upper()}-SECRET"
    amounts = _AMOUNTS[tag]
    ids: dict = {"tag": tag, "marker": marker, "amounts": amounts, "users": {}, "emails": {}}

    with app.app_context():
        from app.core.security import hash_password

        school = School(
            name_ar=f"مدرسة {marker}",
            name_en=f"{marker} Academy",
            domain=f"{tag}-{_uid()}.adversarial.test",
            join_code=f"ADV-{_uid()[:6]}",
        )
        db.session.add(school)
        db.session.flush()
        ids["school"] = school.id

        subject = Subject(name_ar=f"مادة {marker}")
        db.session.add(subject)
        db.session.flush()
        ids["subject"] = subject.id

        grade = Grade(school_id=school.id, grade_level=1, name_ar=f"صف {marker}", stage="primary")
        db.session.add(grade)
        db.session.flush()
        ids["grade"] = grade.id

        for role, key in (
            (UserRole.school_admin, "admin"),
            (UserRole.teacher, "teacher"),
            (UserRole.student, "student"),
            (UserRole.parent, "parent"),
        ):
            user = User(
                email=f"{key}-{tag}-{_uid()}@adversarial.test",
                name_ar=f"{marker} {key}",
                role=role,
                password_hash=hash_password(PASSWORD),
                approval_status=UserApprovalStatus.approved,
                is_active=True,
                is_verified=True,
            )
            db.session.add(user)
            db.session.flush()
            db.session.add(UserRoleLink(user_id=user.id, school_id=school.id, role=role, is_active=True))
            ids["users"][key] = user.id
            ids["emails"][key] = user.email

        class_room = ClassRoom(
            school_id=school.id,
            subject_id=subject.id,
            grade_id=grade.id,
            teacher_id=ids["users"]["teacher"],
            name=f"{marker} Class",
            join_code=f"ADV{tag.upper()}{_uid()[:5]}",
            is_active=True,
            currency="ILS",
        )
        db.session.add(class_room)
        db.session.flush()
        ids["class"] = class_room.id

        db.session.add(ClassMember(class_id=class_room.id, user_id=ids["users"]["student"], status="active"))

        lesson = Lesson(class_id=class_room.id, title=f"{marker} Lesson", status="published", sort_order=1)
        db.session.add(lesson)
        db.session.flush()
        ids["lesson"] = lesson.id

        plan = SubscriptionPlan(
            school_id=school.id,
            class_id=class_room.id,
            name=f"{marker} Plan",
            plan="annual",
            price=Decimal(amounts["plan"]),
            currency="ILS",
            is_active=True,
        )
        db.session.add(plan)
        db.session.flush()
        ids["plan"] = plan.id

        subscription = Subscription(
            user_id=ids["users"]["student"],
            plan_id=plan.id,
            class_id=class_room.id,
            price=Decimal(amounts["plan"]),
            currency="ILS",
            status="active",
        )
        db.session.add(subscription)
        db.session.flush()
        ids["subscription"] = subscription.id

        payment = ManualPayment(
            subscription_id=subscription.id,
            reference=f"ADV-{_uid()}",
            amount=Decimal(amounts["plan"]),
            status="approved",
        )
        wallet = Wallet(
            school_id=school.id,
            user_id=ids["users"]["student"],
            balance=Decimal(amounts["wallet"]),
            currency="ILS",
        )
        db.session.add_all([payment, wallet])
        db.session.flush()
        ids["payment"] = payment.id
        ids["wallet"] = wallet.id

        ledger = WalletTransaction(
            school_id=school.id,
            destination_wallet_id=wallet.id,
            amount=Decimal(amounts["wallet"]),
            currency="ILS",
            transaction_type="admin_adjustment",
            transaction_hash=uuid.uuid4().hex * 2,
            idempotency_key=f"adv-{tag}-{_uid()}",
            description=f"{marker} ledger",
        )
        db.session.add(ledger)
        db.session.flush()
        ids["ledger"] = ledger.id

        db.session.add(
            FamilyLink(parent_id=ids["users"]["parent"], student_id=ids["users"]["student"], status="active")
        )
        db.session.commit()

    return ids


@pytest.fixture
def tenants(app):
    """مستأجران كاملان (A و B) لا يرى أحدهما الآخر — لاختبار واحد فقط.

    دالة لا مصنعاً بعيد المدى: ``_clean_db`` في conftest يفرّغ الجداول بعد كل
    اختبار، فبيانات مشتركة على مدى الملف كانت ستختفي في منتصفه.
    """
    return {"a": _build_tenant(app, "a"), "b": _build_tenant(app, "b")}


def _client_for(app, user_id: int):
    """جلسة مصادَقة لمستخدم موجود (بلا كلمة مرور — أسرع من مسار الدخول)."""
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
    return client


def _body(resp) -> str:
    return resp.get_data(as_text=True)


def _victim_tokens(victim: dict) -> tuple[str, ...]:
    """علامات المستأجر الضحية التي لا يجوز أن تظهر في أي ردّ للآخر."""
    return (
        victim["marker"],
        victim["emails"]["student"],
        victim["emails"]["teacher"],
        victim["amounts"]["plan"],
        victim["amounts"]["wallet"],
    )


# ═══════════════════════════════════════════════════════════════════════════
# السيناريو A — حقن المعرّفات المباشرة (قراءة/تعديل/حذف)
# ═══════════════════════════════════════════════════════════════════════════
class TestScenarioAReadIsolation:
    """محاولات قراءة بيانات المستأجر الآخر بمعرّف مباشر في المسار."""

    def test_foreign_user_profile_is_refused(self, app, tenants):
        a, b = tenants["a"], tenants["b"]
        client = _client_for(app, a["users"]["student"])
        resp = client.get(f"/api/v1/users/{b['users']['student']}", headers={"Accept": "application/json"})
        assert resp.status_code == 403, resp.status_code
        assert b["emails"]["student"] not in _body(resp)

    def test_same_tenant_user_profile_is_allowed(self, app, tenants):
        """ضابط موجب: الحرس لا يرفض الجار في المدرسة نفسها."""
        a = tenants["a"]
        client = _client_for(app, a["users"]["admin"])
        resp = client.get(f"/api/v1/users/{a['users']['student']}", headers={"Accept": "application/json"})
        assert resp.status_code == 200
        assert resp.get_json()["data"]["email"] == a["emails"]["student"]

    def test_foreign_class_is_refused(self, app, tenants):
        a, b = tenants["a"], tenants["b"]
        client = _client_for(app, a["users"]["student"])
        resp = client.get(f"/api/v1/classes/{b['class']}", headers={"Accept": "application/json"})
        assert resp.status_code in (403, 404), resp.status_code
        assert b["marker"] not in _body(resp)

    def test_same_tenant_class_is_allowed(self, app, tenants):
        a = tenants["a"]
        client = _client_for(app, a["users"]["student"])
        resp = client.get(f"/api/v1/classes/{a['class']}", headers={"Accept": "application/json"})
        assert resp.status_code == 200
        assert resp.get_json()["data"]["id"] == a["class"]

    def test_foreign_lesson_is_refused(self, app, tenants):
        a, b = tenants["a"], tenants["b"]
        client = _client_for(app, a["users"]["student"])
        resp = client.get(f"/api/v1/lessons/{b['lesson']}", headers={"Accept": "application/json"})
        assert resp.status_code in (403, 404), resp.status_code
        assert b["marker"] not in _body(resp)

    def test_foreign_school_is_refused(self, app, tenants):
        a, b = tenants["a"], tenants["b"]
        client = _client_for(app, a["users"]["admin"])
        resp = client.get(f"/api/v1/schools/{b['school']}", headers={"Accept": "application/json"})
        assert resp.status_code == 403, resp.status_code
        assert b["marker"] not in _body(resp)

    def test_foreign_invoice_page_is_refused(self, app, tenants):
        a, b = tenants["a"], tenants["b"]
        client = _client_for(app, a["users"]["student"])
        resp = client.get(f"/billing/invoices/{b['subscription']}")
        assert resp.status_code in (403, 404), resp.status_code
        body = _body(resp)
        assert b["amounts"]["plan"] not in body
        assert b["marker"] not in body

    def test_foreign_invoice_pdf_is_refused(self, app, tenants):
        a, b = tenants["a"], tenants["b"]
        client = _client_for(app, a["users"]["student"])
        resp = client.get(f"/billing/invoices/{b['subscription']}/pdf")
        assert resp.status_code in (403, 404), resp.status_code
        assert "pdf" not in (resp.headers.get("Content-Type") or "").lower()

    def test_foreign_report_card_is_refused(self, app, tenants):
        a, b = tenants["a"], tenants["b"]
        client = _client_for(app, a["users"]["teacher"])
        resp = client.get(f"/grades/{b['class']}/report-card/{b['users']['student']}")
        assert resp.status_code in (403, 404), resp.status_code
        assert b["marker"] not in _body(resp)

    def test_foreign_student_progress_is_refused(self, app, tenants):
        a, b = tenants["a"], tenants["b"]
        client = _client_for(app, a["users"]["teacher"])
        resp = client.get(f"/progress/class/{b['class']}/student/{b['users']['student']}")
        assert resp.status_code in (403, 404), resp.status_code
        assert b["marker"] not in _body(resp)

    def test_foreign_class_export_is_refused(self, app, tenants):
        a, b = tenants["a"], tenants["b"]
        client = _client_for(app, a["users"]["teacher"])
        resp = client.get(f"/export/{b['class']}/students")
        assert resp.status_code in (403, 404), resp.status_code
        assert "spreadsheet" not in (resp.headers.get("Content-Type") or "")

    def test_parent_cannot_read_another_tenants_child(self, app, tenants):
        a, b = tenants["a"], tenants["b"]
        client = _client_for(app, a["users"]["parent"])
        resp = client.get(f"/family/children/{b['users']['student']}/progress")
        assert resp.status_code == 403, resp.status_code
        assert b["marker"] not in _body(resp)

    def test_parent_can_read_own_child(self, app, tenants):
        """ضابط موجب: الرابط الأسري النشط يمرّ."""
        a = tenants["a"]
        client = _client_for(app, a["users"]["parent"])
        resp = client.get(f"/family/children/{a['users']['student']}/progress")
        assert resp.status_code == 200

    def test_wallet_balance_probe_never_returns_foreign_balance(self, app, tenants):
        """أدمن A يسأل رصيد طالب B بحقن school_id — لا يرى رصيد B أبداً."""
        a, b = tenants["a"], tenants["b"]
        client = _client_for(app, a["users"]["admin"])
        resp = client.get(
            f"/api/v1/wallet/balance?user_id={b['users']['student']}&school_id={b['school']}",
            headers={"Accept": "application/json"},
        )
        assert resp.status_code in (200, 403, 404), resp.status_code
        assert b["amounts"]["wallet"] not in _body(resp)

    def test_wallet_transaction_history_probe_is_scoped(self, app, tenants):
        """نفس الحقن على دفتر الحركات: قائمة فارغة أو رفض، بلا أي حركة لـ B."""
        a, b = tenants["a"], tenants["b"]
        client = _client_for(app, a["users"]["admin"])
        resp = client.get(
            f"/api/v1/wallet/transactions?user_id={b['users']['student']}&school_id={b['school']}",
            headers={"Accept": "application/json"},
        )
        assert resp.status_code in (200, 403, 404), resp.status_code
        assert b["amounts"]["wallet"] not in _body(resp)
        assert b["marker"] not in _body(resp)
        if resp.status_code == 200:
            assert resp.get_json()["data"] == [], "سجل محفظة عابر للتينانتس أُعيد غير فارغ"

    def test_foreign_class_billing_page_is_refused(self, app, tenants):
        a, b = tenants["a"], tenants["b"]
        client = _client_for(app, a["users"]["student"])
        resp = client.get(f"/billing/{b['class']}")
        assert resp.status_code in (403, 404), resp.status_code
        assert b["marker"] not in _body(resp)


class TestScenarioAWriteIsolation:
    """محاولات تعديل/إنشاء على بيانات المستأجر الآخر — والفشل متحقَّق في القاعدة."""

    def _count(self, app, model, **filters) -> int:
        with app.app_context():
            return model.query.filter_by(**filters).count()

    def test_subscribe_to_foreign_class_writes_nothing(self, app, tenants):
        a, b = tenants["a"], tenants["b"]
        client = _client_for(app, a["users"]["student"])
        resp = client.post(f"/billing/{b['class']}/subscribe", data={"plan_id": str(b["plan"])})
        assert resp.status_code in (403, 404), resp.status_code
        assert self._count(app, Subscription, user_id=a["users"]["student"], class_id=b["class"]) == 0

    def test_plan_creation_on_foreign_class_writes_nothing(self, app, tenants):
        a, b = tenants["a"], tenants["b"]
        before = self._count(app, SubscriptionPlan, class_id=b["class"])
        client = _client_for(app, a["users"]["teacher"])
        resp = client.post(
            f"/billing/{b['class']}/plans",
            data={"name": "ADV plan", "plan": "annual", "price": "9.99", "currency": "ILS"},
        )
        assert resp.status_code in (403, 404), resp.status_code
        assert self._count(app, SubscriptionPlan, class_id=b["class"]) == before

    def test_transfer_to_foreign_user_is_refused_and_balance_intact(self, app, tenants):
        a, b = tenants["a"], tenants["b"]
        client = _client_for(app, a["users"]["student"])
        resp = client.post(
            "/api/v1/wallet/transfers",
            json={
                "dest_user_id": b["users"]["student"],
                "amount": "10.00",
                "idempotency_key": str(uuid.uuid4()),
            },
        )
        assert resp.status_code == 403, resp.status_code
        with app.app_context():
            wallet = db.session.get(Wallet, b["wallet"])
            assert str(wallet.balance) == b["amounts"]["wallet"]

    def test_admin_deposit_into_foreign_wallet_writes_nothing(self, app, tenants):
        a, b = tenants["a"], tenants["b"]
        ledger_before = self._count(app, WalletTransaction, school_id=b["school"])
        client = _client_for(app, a["users"]["admin"])
        resp = client.post(
            "/api/v1/wallet/deposits",
            json={
                "user_id": b["users"]["student"],
                "amount": "10.00",
                "idempotency_key": str(uuid.uuid4()),
            },
        )
        assert resp.status_code == 403, resp.status_code
        assert self._count(app, WalletTransaction, school_id=b["school"]) == ledger_before
        with app.app_context():
            wallet = db.session.get(Wallet, b["wallet"])
            assert str(wallet.balance) == b["amounts"]["wallet"]

    def test_foreign_payment_submission_is_refused(self, app, tenants):
        a, b = tenants["a"], tenants["b"]
        client = _client_for(app, a["users"]["student"])
        resp = client.post(
            f"/billing/subscriptions/{b['subscription']}/pay",
            data={"reference": "ADV-REF", "amount": "10.00"},
        )
        assert resp.status_code in (403, 404), resp.status_code
        assert self._count(app, ManualPayment, reference="ADV-REF") == 0


# ═══════════════════════════════════════════════════════════════════════════
# السيناريو B — مسح شامل: صفر بايت من بيانات المستأجر الآخر (الاتجاهان)
# ═══════════════════════════════════════════════════════════════════════════
# (وصف، شخصية المهاجم، الطريقة، المسار، الرموز المقبولة، فحص نطاق القوائم)
# فحص النطاق: "empty" قائمة يجب أن تكون فارغة، "own" عناصر القائمة يجب أن
# تكون كلها داخل نطاق المهاجم، None لا فحص (ليست مسار قائمة).
_PROBES: list[tuple[str, str, str, str, tuple[int, ...], str | None]] = [
    ("user-profile", "student", "GET", "/api/v1/users/{v[users][student]}", (403,), None),
    ("user-colleague", "admin", "GET", "/api/v1/users/{v[users][teacher]}", (403,), None),
    ("class-detail", "student", "GET", "/api/v1/classes/{v[class]}", (403, 404), None),
    ("lesson-detail", "student", "GET", "/api/v1/lessons/{v[lesson]}", (403, 404), None),
    ("school-detail", "admin", "GET", "/api/v1/schools/{v[school]}", (403,), None),
    ("invoice", "student", "GET", "/billing/invoices/{v[subscription]}", (403, 404), None),
    ("invoice-pdf", "student", "GET", "/billing/invoices/{v[subscription]}/pdf", (403, 404), None),
    ("class-billing", "student", "GET", "/billing/{v[class]}", (403, 404), None),
    ("report-card", "teacher", "GET", "/grades/{v[class]}/report-card/{v[users][student]}", (403, 404), None),
    (
        "report-card-pdf",
        "teacher",
        "GET",
        "/grades/{v[class]}/report-card/{v[users][student]}/pdf",
        (403, 404),
        None,
    ),
    ("student-progress", "teacher", "GET", "/progress/class/{v[class]}/student/{v[users][student]}", (403, 404), None),
    ("class-overview", "teacher", "GET", "/progress/class/{v[class]}", (403, 404), None),
    ("students-export", "teacher", "GET", "/export/{v[class]}/students", (403, 404), None),
    ("child-progress", "parent", "GET", "/family/children/{v[users][student]}/progress", (403,), None),
    ("child-grades", "parent", "GET", "/family/children/{v[users][student]}/grades", (403,), None),
    (
        "wallet-balance",
        "admin",
        "GET",
        "/api/v1/wallet/balance?user_id={v[users][student]}&school_id={v[school]}",
        (200, 403, 404),
        None,
    ),
    (
        "wallet-transactions",
        "admin",
        "GET",
        "/api/v1/wallet/transactions?user_id={v[users][student]}&school_id={v[school]}",
        (200, 403, 404),
        "empty",
    ),
    # مسارات قوائم في تينانت المهاجم: 200 مقبول، لكن كل عنصر يجب أن يكون من نطاقه
    ("lessons-list", "student", "GET", "/api/v1/lessons", (200,), "own-lessons"),
    ("classes-list", "student", "GET", "/api/v1/classes", (200,), "own-classes"),
    ("users-list", "admin", "GET", "/api/v1/users", (200,), "own-users"),
]


def _scope_violations(name: str, scope_check: str, attacker: dict, victim: dict, resp) -> list[str]:
    """يفحص أن كل ما عاد في قائمة يخصّ المهاجم لا الضحية.

    قوائم ``/api/v1/classes`` و``/lessons`` و``users`` مسارات شرعية تُعيد
    صفوف صاحب الطلب، فلا يصحّ اشتراط كونها فارغة — الشرط الصحيح أن لا يحمل
    أي عنصر منها معرّفاً أو بريداً من نطاق الضحية.
    """
    items = (resp.get_json() or {}).get("data") or []
    problems: list[str] = []

    if scope_check == "empty":
        if items:
            problems.append(f"{name}: قائمة عابرة للتينانتس أُعيدت غير فارغة")
        return problems

    if scope_check == "own-classes":
        foreign = [i for i in items if i.get("school_id") != attacker["school"]]
        if foreign:
            problems.append(f"{name}: عناصر من مدارس أخرى ({foreign[:2]})")
    elif scope_check == "own-lessons":
        foreign = [i for i in items if i.get("class_id") != attacker["class"]]
        if foreign:
            problems.append(f"{name}: دروس صفوف أخرى ({foreign[:2]})")
    elif scope_check == "own-users":
        victim_emails = set(victim["emails"].values())
        foreign = [i for i in items if i.get("email") in victim_emails]
        if foreign:
            problems.append(f"{name}: مستخدمو المستأجر الآخر ({foreign[:2]})")
    else:  # pragma: no cover — فحص مكتوب خطأً
        problems.append(f"{name}: فحص نطاق غير معروف {scope_check!r}")
    return problems


class TestScenarioBNoForeignDataLeaves:
    """مسح شامل: لا ردّ واحد يحمل بيانات المستأجر الآخر في أي اتجاه."""

    def test_cross_tenant_sweep_in_both_directions(self, app, tenants):
        """مسح كل المسارات العابرة في الاتجاهين، وتقرير تراكمي بكل تسرّب."""
        violations: list[str] = []

        for attacker_tag, victim_tag in (("a", "b"), ("b", "a")):
            attacker, victim = tenants[attacker_tag], tenants[victim_tag]

            for name, persona, method, path_tpl, allowed, scope_check in _PROBES:
                url = path_tpl.format(v=victim)
                client = _client_for(app, attacker["users"][persona])
                resp = client.open(url, method=method, headers={"Accept": "application/json"})
                body = _body(resp)

                if resp.status_code not in allowed:
                    violations.append(f"{attacker_tag}->{victim_tag} {name}: status {resp.status_code} خارج {allowed}")
                for token in _victim_tokens(victim):
                    if token in body:
                        violations.append(f"{attacker_tag}->{victim_tag} {name}: تسرّب العلامة {token!r}")
                if scope_check and resp.status_code == 200:
                    violations += _scope_violations(name, scope_check, attacker, victim, resp)

        assert not violations, "تسرّبات عابرة للتينانتس:\n" + "\n".join(violations)

    def test_no_technical_detail_in_any_refusal(self, app, tenants):
        """بند التطهير: حتى ردود الرفض لا تحمل أي أثر SQL/محرّك."""
        a, b = tenants["a"], tenants["b"]
        client = _client_for(app, a["users"]["student"])
        leaks = ("psycopg", "sqlalchemy", "SELECT ", "Traceback", "violates", "does not exist")
        for path in (
            f"/api/v1/classes/{b['class']}",
            f"/api/v1/lessons/{b['lesson']}",
            f"/api/v1/users/{b['users']['student']}",
            f"/billing/invoices/{b['subscription']}",
        ):
            body = _body(client.get(path, headers={"Accept": "application/json"}))
            for token in leaks:
                assert token not in body, f"{path} كشف تفصيلاً تقنياً: {token!r}"


# ═══════════════════════════════════════════════════════════════════════════
# السيناريو C — طبقة البيانات: RLS + تقييد ORM
# ═══════════════════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def rls_ready(app):
    """يطبّق سياسات RLS مرة واحدة للملف (DDL مستوى مخطط، لا بيانات)."""
    with app.app_context():
        from app.core.rls import enable_all_rls_policies

        enable_all_rls_policies()
    yield


def _set_local_tenant(school_id: int, user_id: int) -> None:
    """يضبط متغيرات الطلب نفسها (SET LOCAL) — كما يفعل set_tenant_for_request."""
    db.session.execute(text("SELECT set_config('app.current_user_id', :v, true)"), {"v": str(user_id)})
    db.session.execute(text("SELECT set_config('app.current_school_id', :v, true)"), {"v": str(school_id)})
    db.session.execute(text("SELECT set_config('app.is_super_admin', '0', true)"))


def _as_tenant(app, school_id: int, user_id: int, sql: str, params: dict | None = None):
    """ينفّذ عبارة واحدة بسياق تينانت (القراءة/الكتابة كالمسار الحقيقي)."""
    with app.app_context():
        _set_local_tenant(school_id, user_id)
        try:
            return db.session.execute(text(sql), params or {}).all()
        finally:
            db.session.rollback()


def _try_write_as_tenant(app, school_id: int, user_id: int, sql: str, params: dict | None = None):
    """ينفّذ كتابة ويعيد (نجحت؟، نوع الخطأ، الصفوف المتأثرة)."""
    with app.app_context():
        _set_local_tenant(school_id, user_id)
        try:
            result = db.session.execute(text(sql), params or {})
            return True, None, result.rowcount
        except sqlalchemy.exc.SQLAlchemyError as exc:
            db.session.rollback()
            return False, type(exc).__name__, 0
        finally:
            db.session.rollback()


class TestScenarioCOrmScoping:
    @pytest.mark.usefixtures("rls_ready")
    def test_scope_by_school_refuses_model_without_tenant_column(self):
        """درسORM: نموذج بلا school_id لا يمكن «تقييده» — رفض صريح لا صمت."""
        from app.core.tenancy import scope_by_school

        with pytest.raises(ValueError, match="لا عزل تينانتس"):
            scope_by_school(School, 1)

    @pytest.mark.usefixtures("rls_ready")
    def test_tenant_scope_aborts_for_foreign_school(self, app, tenants):
        """``tenant_scope`` يرفض 403 على مدرسة ليست مدرسة المستخدم."""
        from app.core.tenancy import tenant_scope
        from flask_login import login_user
        from werkzeug.exceptions import Forbidden

        a, b = tenants["a"], tenants["b"]
        with app.test_request_context("/"):
            with app.app_context():
                user = db.session.get(User, a["users"]["student"])
                login_user(user)
            with pytest.raises(Forbidden):
                tenant_scope(ClassRoom, b["school"])

    @pytest.mark.usefixtures("rls_ready")
    def test_unscoped_orm_queries_are_filtered_by_rls(self, app, tenants):
        """استعلام ORM بلا أي شرط تينانت: يرى صفوف مدرسته فقط."""
        a, b = tenants["a"], tenants["b"]
        with app.app_context():
            _set_local_tenant(a["school"], a["users"]["student"])
            try:
                assert ClassRoom.query.filter_by(id=b["class"]).first() is None
                assert Lesson.query.filter_by(id=b["lesson"]).first() is None
                assert ClassRoom.query.filter_by(id=a["class"]).first() is not None
            finally:
                db.session.rollback()

    @pytest.mark.usefixtures("rls_ready")
    def test_request_context_publishes_the_tenant_to_the_database(self, app, tenants):
        """``set_tenant_for_request`` ينشر مدرسة الطلب فعلاً في متغيرات القاعدة."""
        from app.core.tenancy import set_tenant_for_request
        from flask_login import login_user

        a = tenants["a"]
        with app.test_request_context("/"):
            with app.app_context():
                login_user(db.session.get(User, a["users"]["student"]))
            set_tenant_for_request()
            row = db.session.execute(
                text(
                    "SELECT current_setting('app.current_school_id', true), "
                    "current_setting('app.is_super_admin', true), "
                    "current_setting('app.current_user_id', true)"
                )
            ).one()
            assert row[0] == str(a["school"])
            assert row[1] == "0"
            assert row[2] == str(a["users"]["student"])


class TestScenarioCDataLayerIsolation:
    @pytest.mark.usefixtures("rls_ready")
    def test_unscoped_raw_sql_cannot_read_foreign_rows(self, app, tenants):
        """حتى ``SELECT count(*) FROM classes`` بلا WHERE لا يرى إلا مدرسته."""
        a, b = tenants["a"], tenants["b"]
        own = _as_tenant(app, a["school"], a["users"]["student"], "SELECT count(*) FROM classes")
        targeted = _as_tenant(
            app,
            a["school"],
            a["users"]["student"],
            "SELECT count(*) FROM classes WHERE id = :cid",
            {"cid": b["class"]},
        )
        victim_view = _as_tenant(
            app,
            b["school"],
            b["users"]["student"],
            "SELECT count(*) FROM classes WHERE id = :cid",
            {"cid": b["class"]},
        )
        assert own[0][0] == 1, "مدرسته نفسها محجوبة — سياسة مفرطة"
        assert targeted[0][0] == 0, "قراءة خامة عبر التينانتس لم تُحجب"
        assert victim_view[0][0] == 1, "المالك لا يرى صفّه — سياسة مفرطة"

    @pytest.mark.parametrize(
        "table, id_key",
        [
            ("lessons", "lesson"),
            ("class_members", "class"),
            ("subscriptions", "subscription"),
            ("subscription_plans", "plan"),
            ("wallets", "wallet"),
            ("wallet_transactions", "ledger"),
        ],
    )
    @pytest.mark.usefixtures("rls_ready")
    def test_financial_and_content_rows_are_tenant_scoped(self, app, tenants, table, id_key):
        """جداول المال والمحتوى: صف المستأجر الآخر غير مرئي بالقراءة الخامة."""
        a, b = tenants["a"], tenants["b"]
        row_id = b["class"] if id_key == "class" else b[id_key]
        column = "class_id" if table == "class_members" else "id"
        seen = _as_tenant(
            app,
            a["school"],
            a["users"]["student"],
            f"SELECT count(*) FROM {table} WHERE {column} = :rid",  # noqa: S608 — اسم جدول/عمود ثابت
            {"rid": row_id},
        )
        assert seen[0][0] == 0, f"{table}: صف عابر للتينانتس مرئي"

    @pytest.mark.usefixtures("rls_ready")
    def test_cross_tenant_insert_is_rejected_by_with_check(self, app, tenants):
        """``WITH CHECK`` يسدّ الكتابة: لا صف يُنشأ داخل مدرسة أخرى."""
        a, b = tenants["a"], tenants["b"]
        before = _as_tenant(
            app,
            b["school"],
            b["users"]["student"],
            "SELECT count(*) FROM classes WHERE school_id = :sid",
            {"sid": b["school"]},
        )[0][0]

        ok, error, _rowcount = _try_write_as_tenant(
            app,
            a["school"],
            a["users"]["student"],
            "INSERT INTO classes (school_id, subject_id, grade_id, name, join_code, is_active, currency) "
            "VALUES (:sid, :sub, :grade, :name, :jc, true, 'ILS')",
            {
                "sid": b["school"],
                "sub": b["subject"],
                "grade": b["grade"],
                "name": "ADV cross-tenant class",
                "jc": f"ADVX{_uid()}",
            },
        )
        assert ok is False, "أُقحم صف في مدرسة أخرى"
        assert error is not None

        after = _as_tenant(
            app,
            b["school"],
            b["users"]["student"],
            "SELECT count(*) FROM classes WHERE school_id = :sid",
            {"sid": b["school"]},
        )[0][0]
        assert after == before, "تغيّر عدد صفوف المدرسة الضحية"

    @pytest.mark.usefixtures("rls_ready")
    def test_cross_tenant_update_and_delete_affect_zero_rows(self, app, tenants):
        """التعديل والحذف عبر التينانتس لا يصيبان صفاً واحداً."""
        a, b = tenants["a"], tenants["b"]

        ok_update, _err, updated = _try_write_as_tenant(
            app,
            a["school"],
            a["users"]["student"],
            "UPDATE classes SET name = 'ADV overwritten' WHERE id = :cid",
            {"cid": b["class"]},
        )
        ok_delete, _err2, deleted = _try_write_as_tenant(
            app,
            a["school"],
            a["users"]["student"],
            "DELETE FROM classes WHERE id = :cid",
            {"cid": b["class"]},
        )
        assert updated == 0, "تعديل عابر للتينانتس أصاب صفاً"
        assert deleted == 0, "حذف عابر للتينانتس أصاب صفاً"
        assert ok_update and ok_delete  # RLS تصفّي بصمت — لا خطأ، بل صفر صفوف

        # الصف سليم كما كان (تُقرأ بمشرف النظام الذي يرى كل شيء)
        with app.app_context():
            db.session.execute(text("SELECT set_config('app.is_super_admin', '1', true)"))
            try:
                row = db.session.execute(text("SELECT name FROM classes WHERE id = :cid"), {"cid": b["class"]}).one()
            finally:
                db.session.rollback()
        assert row[0] == f"{b['marker']} Class"
