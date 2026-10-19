"""عقد الواجهة/الـAPI وعزل التينانتس — اختبارات تراجع للثغرات المكتشفة.

كل اختبار هنا يفشل على الشيفرة السابقة ويمرّ بعد الإصلاح:

* ``grades.appeal_detail`` و«تفاصيل» في طابور الاعتراضات: نداء ``url_for``
  لمسار غير موجود كان يجعل الصفحة 500 متى وُجد اعتراض واحد، وعمود الدرجة
  كان يقرأ خاصية غير موجودة (``current_mark``).
* ``billing.payment_file``: الإيصالات كانت تُربط بمسار غير موجود (BuildError
  في صفحة المدفوعات المعلّقة) وملفاتها غير قابلة للتنزيل أصلاً.
* ``billing.admin`` ومراجعة الدفعات: كانت غير مقيّدة بمدرسة مشرف المدرسة.
* ``wallet_api``: طلبات GET المجهولة كانت 500 (``AnonymousUserMixin.id``).
* شريط تنقّل الإدارة: مشرف المدرسة كان يرى روابط تردّ 403.
* ``subscribe`` من وليّ الأمر: كان يسمح بتمرير ``class_id`` لصفّ لا صلة
  بابنه به (تجاوز ``can_pay_class``).
* ``class_assign_teacher``: كان يقبل معلماً من مدرسة أخرى بمعرّفه.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

import pytest
from app.extensions import db
from app.models.billing import ManualPayment, PaymentReceipt, Subscription
from app.models.class_room import ClassRoom
from app.models.gradebook import Assignment, GradeAppeal, Submission
from app.models.wallet import WalletTopupRequest

from tests.conftest import (
    make_class,
    make_class_member,
    make_family_link,
    make_grade,
    make_payment,
    make_school,
    make_subject,
    make_subscription,
    make_subscription_plan,
    make_user,
)


TEMPLATES = Path(__file__).resolve().parents[2] / "app" / "templates"


def test_every_url_for_in_templates_resolves_to_a_route(app):
    """عقد الـUI/API: أي ``url_for`` في قالب يجب أن يشير إلى endpoint موجود.

    BuildError لا يُكتشف إلا عند عرض الصفحة، واختباراتُ التغطية كانت تقبل
    500؛ هذا الفحص الثابت يمنع تكرار فئة العطل كلها (مساران ميتان أُصلحا
    هنا: grades.appeal_detail و billing.payment_file).
    """
    endpoints = {rule.endpoint for rule in app.url_map.iter_rules()}
    pattern = re.compile(r"""url_for\(\s*['\"]([^'\"]+)['\"]""")
    missing: dict[str, list[str]] = {}
    for template in TEMPLATES.rglob("*.html"):
        for name in pattern.findall(template.read_text(encoding="utf-8")):
            if name not in endpoints:
                missing.setdefault(name, []).append(template.name)
    assert not missing, f"url_for إلى endpoints غير موجودة: {missing}"


def _client_for(app, user_id: int):
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
    return client


def _tenant(app, tag: str) -> dict:
    """مدرسة + صفّ + معلم + طالب عضو — بعلامات مميّزة لكل تينانت."""
    school_id = make_school(app, name_ar=f"مدرسة عقد {tag}")
    grade_id = make_grade(app, school_id)
    subject_id = make_subject(app)
    teacher_id = make_user(app, role="teacher", school_id=school_id)
    class_id = make_class(app, school_id, grade_id, subject_id, teacher_id=teacher_id)
    student_id = make_user(app, role="student", school_id=school_id)
    make_class_member(app, class_id, student_id)
    admin_id = make_user(app, role="school_admin", school_id=school_id)
    return {
        "tag": tag,
        "school": school_id,
        "teacher": teacher_id,
        "student": student_id,
        "admin": admin_id,
        "class": class_id,
    }


def _appeal_fixture(app, tenant: dict) -> int:
    with app.app_context():
        assignment = Assignment(
            class_id=tenant["class"],
            title=f"واجب {tenant['tag']}-CONTRACT",
            max_mark=20,
            created_by=tenant["teacher"],
        )
        db.session.add(assignment)
        db.session.flush()
        submission = Submission(assignment_id=assignment.id, student_id=tenant["student"], mark=12)
        db.session.add(submission)
        db.session.flush()
        appeal = GradeAppeal(
            submission_id=submission.id,
            student_id=tenant["student"],
            reason=f"سبب اعتراض {tenant['tag']}-CONTRACT",
        )
        db.session.add(appeal)
        db.session.commit()
        return appeal.id


def _pending_payment_fixture(app, tenant: dict) -> tuple[int, int, str, str]:
    with app.app_context():
        plan_id = make_subscription_plan(app, tenant["school"], class_id=tenant["class"])
        sub_id = make_subscription(app, tenant["student"], plan_id, tenant["class"], status="pending")
        ref = f"PAY-{tenant['tag']}-{uuid.uuid4().hex[:6]}"
        payment_id = make_payment(app, sub_id, reference=ref, amount=120, status="pending")

        stored = f"receipts/{uuid.uuid4().hex}.pdf"
        target = Path(app.config["UPLOAD_FOLDER"]) / stored
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"%PDF-1.4 contract test")

        db.session.add(
            PaymentReceipt(
                manual_payment_id=payment_id,
                stored_name=stored,
                original_name=f"{tenant['tag']}.pdf",
                mime="application/pdf",
                size_bytes=20,
            )
        )
        db.session.commit()
        return payment_id, sub_id, stored, ref


class TestAppealContract:
    def test_queue_with_appeal_renders_and_links_to_existing_route(self, app):
        tenant = _tenant(app, "A")
        appeal_id = _appeal_fixture(app, tenant)
        client = _client_for(app, tenant["teacher"])

        resp = client.get(f"/classes/{tenant['class']}/appeals")
        assert resp.status_code == 200, resp.status_code
        body = resp.get_data(as_text=True)
        assert f"/classes/appeals/{appeal_id}" in body
        # الدرجة الحالية تُقرأ من التسليم لا من خاصية غير موجودة.
        assert "12" in body

    def test_teacher_can_open_and_review_appeal(self, app):
        tenant = _tenant(app, "A")
        appeal_id = _appeal_fixture(app, tenant)
        client = _client_for(app, tenant["teacher"])

        detail = client.get(f"/classes/appeals/{appeal_id}")
        assert detail.status_code == 200
        assert "سبب اعتراض A-CONTRACT" in detail.get_data(as_text=True)

        review = client.post(
            f"/classes/appeals/{appeal_id}/review",
            data={"action": "approved", "response": "صُحّحت الدرجة"},
            follow_redirects=False,
        )
        assert review.status_code == 302
        with app.app_context():
            appeal = db.session.get(GradeAppeal, appeal_id)
            assert appeal.status == "approved"
            assert appeal.teacher_response == "صُحّحت الدرجة"

    def test_owner_student_reads_appeal_but_foreign_teacher_is_refused(self, app):
        a, b = _tenant(app, "A"), _tenant(app, "B")
        appeal_id = _appeal_fixture(app, a)

        owner = _client_for(app, a["student"])
        assert owner.get(f"/classes/appeals/{appeal_id}").status_code == 200

        foreign = _client_for(app, b["teacher"])
        assert foreign.get(f"/classes/appeals/{appeal_id}").status_code in (403, 404)

        peer = make_user(app, role="student", school_id=a["school"])
        assert _client_for(app, peer).get(f"/classes/appeals/{appeal_id}").status_code == 403


class TestPaymentReceiptContract:
    def test_pending_page_with_receipt_renders_and_file_downloads(self, app):
        tenant = _tenant(app, "A")
        admin_id = make_user(app, role="super_admin")
        _, _, stored, _ref = _pending_payment_fixture(app, tenant)
        client = _client_for(app, admin_id)

        page = client.get("/admin/payments/pending")
        assert page.status_code == 200, page.status_code
        body = page.get_data(as_text=True)
        assert f"/billing/payments/receipts/{stored}" in body

        download = client.get(f"/billing/payments/receipts/{stored}")
        assert download.status_code == 200
        assert download.data == b"%PDF-1.4 contract test"
        assert "attachment" in download.headers["Content-Disposition"]

    def test_receipt_is_tenant_and_owner_scoped(self, app):
        a, b = _tenant(app, "A"), _tenant(app, "B")
        _, _, stored, _ref = _pending_payment_fixture(app, a)
        url = f"/billing/payments/receipts/{stored}"

        assert _client_for(app, a["student"]).get(url).status_code == 200
        assert _client_for(app, a["admin"]).get(url).status_code == 200
        # RLS يخفي صفّ الإيصال قبل المقارنة أحياناً → 404 مقبول أيضاً؛ المهم
        # ألا يخرج أي بايت من الإيصال الأجنبي.
        assert _client_for(app, b["admin"]).get(url).status_code in (403, 404)
        assert _client_for(app, b["student"]).get(url).status_code in (403, 404)
        assert _client_for(app, make_user(app, role="super_admin")).get(url).status_code == 200
        assert _client_for(app, a["admin"]).get("/billing/payments/receipts/nope.pdf").status_code == 404

    def test_school_admin_pending_queue_and_review_are_scoped(self, app):
        a, b = _tenant(app, "A"), _tenant(app, "B")
        _a_payment, _a_sub, _a_stored, a_ref = _pending_payment_fixture(app, a)
        b_payment, _b_sub, _b_stored, _b_ref = _pending_payment_fixture(app, b)
        client = _client_for(app, a["admin"])

        page = client.get("/billing/admin")
        assert page.status_code == 200
        body = page.get_data(as_text=True)
        assert a_ref in body
        assert f"PAY-B-" not in body, "دفعة مدرسة أخرى ظهرت لمشرف المدرسة"

        foreign_review = client.post(f"/billing/payments/{b_payment}/approve", follow_redirects=False)
        # RLS يخفي الصفّ قبل المقارنة في بعض البيئات → 404، وإلا فالحارس 403.
        assert foreign_review.status_code in (403, 404)
        with app.app_context():
            assert db.session.get(ManualPayment, b_payment).status == "pending"


class TestAuthGuardContract:
    @pytest.mark.parametrize("path", ["/api/v1/wallet/balance", "/api/v1/wallet/transactions"])
    def test_anonymous_wallet_get_is_401_not_500(self, client, path):
        resp = client.get(path, headers={"Accept": "application/json"})
        assert resp.status_code == 401, resp.status_code


class TestAdminNavPermissionParity:
    def test_school_admin_dashboard_has_no_super_admin_links_and_those_routes_refuse(self, app):
        tenant = _tenant(app, "A")
        client = _client_for(app, tenant["admin"])
        resp = client.get("/admin/school-admin")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        for forbidden in ("/admin/users", "/admin/payments/pending", "/admin/schools", "/admin/settings"):
            assert forbidden not in body, f"رابط غير مسموح ظاهر لمشرف المدرسة: {forbidden}"
            # والرابط المحذوف من الواجهة يرفضه الحارس أيضاً.
            assert client.get(forbidden).status_code == 403

    def test_super_admin_still_sees_management_links(self, app):
        admin_id = make_user(app, role="super_admin")
        resp = _client_for(app, admin_id).get("/admin/")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        for link in ("/admin/users", "/admin/payments/pending", "/admin/settings"):
            assert link in body


class TestCrossTenantWriteGuards:
    def test_parent_cannot_subscribe_child_to_unrelated_class(self, app):
        a, b = _tenant(app, "A"), _tenant(app, "B")
        parent_id = make_user(app, role="parent", school_id=a["school"])
        child_id = make_user(app, role="student", school_id=a["school"])
        make_family_link(app, parent_id, child_id)
        plan_id = make_subscription_plan(app, b["school"], class_id=b["class"])

        resp = _client_for(app, parent_id).post(
            f"/billing/{b['class']}/subscribe",
            data={"plan_id": str(plan_id), "student_id": str(child_id)},
            follow_redirects=False,
        )
        assert resp.status_code == 403
        with app.app_context():
            assert Subscription.query.filter_by(user_id=child_id, class_id=b["class"]).count() == 0

    def test_parent_can_subscribe_child_already_in_the_class(self, app):
        """ضابط موجب: حاجز الوالد لا يمنع الدفع المشروع عن ابنه العضو."""
        tenant = _tenant(app, "A")
        parent_id = make_user(app, role="parent", school_id=tenant["school"])
        make_family_link(app, parent_id, tenant["student"])
        plan_id = make_subscription_plan(app, tenant["school"], class_id=tenant["class"])

        resp = _client_for(app, parent_id).post(
            f"/billing/{tenant['class']}/subscribe",
            data={"plan_id": str(plan_id), "student_id": str(tenant["student"])},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        with app.app_context():
            sub = Subscription.query.filter_by(user_id=tenant["student"], class_id=tenant["class"]).one()
            assert sub.payer_id == parent_id

    def test_school_admin_topup_approval_returns_to_an_allowed_page(self, app):
        """بعد الاعتماد كان التحويل إلى /admin/wallet المحظور على مشرف المدرسة."""
        from decimal import Decimal

        tenant = _tenant(app, "A")
        parent_id = make_user(app, role="parent", school_id=tenant["school"])
        make_family_link(app, parent_id, tenant["student"])
        with app.app_context():
            req = WalletTopupRequest(
                school_id=tenant["school"],
                parent_id=parent_id,
                child_user_id=tenant["student"],
                amount=Decimal("50.00"),
                currency="ILS",
                status="pending",
            )
            db.session.add(req)
            db.session.commit()
            req_id = req.id

        client = _client_for(app, tenant["admin"])
        resp = client.post(
            f"/admin/wallet/topup/{req_id}/review",
            data={"decision": "approve"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/admin/school-admin")
        assert client.get(resp.headers["Location"]).status_code == 200
        with app.app_context():
            assert db.session.get(WalletTopupRequest, req_id).status == "approved"

    def test_school_admin_school_list_is_scoped(self, app):
        _tenant(app, "A")
        _tenant(app, "B")
        a = _tenant(app, "A2")
        body = _client_for(app, a["admin"]).get("/schools/").get_data(as_text=True)
        assert "مدرسة عقد A2" in body
        assert "مدرسة عقد B" not in body, "قائمة المدارس سرّبت مدرسة أخرى"

    def test_assign_teacher_rejects_teacher_from_another_school(self, app):
        a, b = _tenant(app, "A"), _tenant(app, "B")
        client = _client_for(app, a["admin"])

        foreign = client.post(
            f"/schools/class/{a['class']}/teacher",
            data={"teacher_id": str(b["teacher"])},
            follow_redirects=False,
        )
        assert foreign.status_code == 302
        with app.app_context():
            assert db.session.get(ClassRoom, a["class"]).teacher_id == a["teacher"]

        own_teacher = make_user(app, role="teacher", school_id=a["school"])
        own = client.post(
            f"/schools/class/{a['class']}/teacher",
            data={"teacher_id": str(own_teacher)},
            follow_redirects=False,
        )
        assert own.status_code == 302
        with app.app_context():
            assert db.session.get(ClassRoom, a["class"]).teacher_id == own_teacher
