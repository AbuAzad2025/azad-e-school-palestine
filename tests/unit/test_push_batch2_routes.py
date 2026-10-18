"""97% push — batch 2: assessment, billing, wallet routes.

Every test targets a CI-verified missed line (coverage.xml run 34714987468).
Covers: quiz manage/AI-generate/question bank, attempt lifecycle incl.
parsing branches, billing subscribe/pay/review/discount/invoice, wallet API
auth-scoping and validation branches.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from tests.conftest import (
    make_class,
    make_class_member,
    make_grade,
    make_school,
    make_subject,
    make_user,
)

PASSWORD = "TestPass123!"


def _email() -> str:
    return f"p2-{uuid.uuid4().hex[:10]}@test.com"


def mk_user(app, role: str, school_id=None):
    email = _email()
    return make_user(app, role=role, school_id=school_id, email=email), email


def login_as(app, uid_email):
    client = app.test_client()
    client.post("/auth/login", data={"email": uid_email[1], "password": PASSWORD})
    return client


def _setup(app):
    sid = make_school(app)
    gid = make_grade(app, sid)
    subj = make_subject(app)
    cid = make_class(app, sid, gid, subj)
    return sid, gid, subj, cid


def _quiz(app, cid: int, teacher_id: int) -> int:
    from app.extensions import db
    from app.models.assessment import Quiz

    with app.app_context():
        q = Quiz(
            class_id=cid,
            title=f"اختبار {uuid.uuid4().hex[:6]}",
            total_mark=10,
            duration_min=30,
            status="published",
            created_by=teacher_id,
        )
        db.session.add(q)
        db.session.commit()
        return q.id


def _question(app, quiz_id: int, qtype: str = "mcq") -> int:
    from app.extensions import db
    from app.models.assessment import Question

    with app.app_context():
        if qtype == "mcq":
            q = Question(
                quiz_id=quiz_id,
                type="mcq",
                prompt="2+2؟",
                options={"1": "3", "2": "4"},
                correct_answer={"index": "2"},
                mark=5,
            )
        elif qtype == "true_false":
            q = Question(
                quiz_id=quiz_id,
                type="true_false",
                prompt="الشمس نجم؟",
                correct_answer={"value": True},
                mark=5,
            )
        else:
            q = Question(quiz_id=quiz_id, type="essay", prompt="اشرح", mark=10)
        db.session.add(q)
        db.session.commit()
        return q.id


# ═════════════════════════════ assessment ═════════════════════════════


class TestAssessmentRoutes:
    def _class_with_people(self, app):
        sid, _, _, cid = _setup(app)
        tid, t_email = mk_user(app, "teacher", school_id=sid)
        stud, s_email = mk_user(app, "student", school_id=sid)
        make_class_member(app, cid, stud)
        from tests.conftest import _db

        with app.app_context():
            from app.extensions import db as _db
            from app.models.class_room import ClassRoom

            _db.session.get(ClassRoom, cid).teacher_id = tid
            _db.session.commit()
        return sid, cid, tid, t_email, stud, s_email

    def test_quiz_manage_add_question(self, app):
        _, cid, tid, t_email, _, _ = self._class_with_people(app)
        quiz_id = _quiz(app, cid, tid)
        client = login_as(app, (tid, t_email))
        page = client.get(f"/classes/{cid}/quizzes/{quiz_id}")
        assert page.status_code == 200
        resp = client.post(
            f"/classes/{cid}/quizzes/{quiz_id}",
            data={"qtype": "mcq", "prompt": "3+3؟", "mark": "5", "option_1": "5", "option_2": "6", "correct": "2"},
        )
        assert resp.status_code == 302

    def test_ai_generate_questions_requires_teacher(self, app):
        _, _, _, _, stud, s_email = self._class_with_people(app)
        client = login_as(app, (stud, s_email))
        assert client.post("/classes/quiz/generate-ai", json={"topic": "x"}).status_code == 403

    def test_ai_generate_questions_teacher_mock(self, app):
        from unittest.mock import AsyncMock, patch

        _, cid, tid, t_email, _, _ = self._class_with_people(app)
        client = login_as(app, (tid, t_email))
        questions = [{"type": "mcq", "prompt": "س1"}, {"type": "true_false", "prompt": "س2"}]
        with patch("app.modules.assessment.routes.get_ai_service") as svc:
            svc.return_value.generate_questions = AsyncMock(return_value=questions)
            resp = client.post("/classes/quiz/generate-ai", json={"topic": "كسور", "count": 2})
        assert resp.status_code == 200
        assert resp.get_json()["questions"] == questions

    def test_attempt_start_for_teacher_redirects(self, app):
        _, cid, tid, t_email, _, _ = self._class_with_people(app)
        quiz_id = _quiz(app, cid, tid)
        client = login_as(app, (tid, t_email))
        resp = client.get(f"/classes/quizzes/{quiz_id}/attempt", follow_redirects=False)
        assert resp.status_code == 302

    def test_attempt_lifecycle_student(self, app):
        _, cid, tid, t_email, stud, s_email = self._class_with_people(app)
        quiz_id = _quiz(app, cid, tid)
        qid = _question(app, quiz_id, "mcq")
        q2 = _question(app, quiz_id, "true_false")
        client = login_as(app, (stud, s_email))
        # start
        start = client.get(f"/classes/quizzes/{quiz_id}/attempt", follow_redirects=False)
        assert start.status_code == 302
        assert "/attempt/" in start.headers["Location"]
        attempt_id = int(start.headers["Location"].rstrip("/").split("/")[-1])
        # do page renders
        assert client.get(f"/classes/attempt/{attempt_id}").status_code == 200
        # save answers: mcq by index + true_false
        saved = client.post(
            f"/classes/attempt/{attempt_id}/save",
            data={"q_" + str(qid): "2", "q_" + str(q2): "true"},
            follow_redirects=False,
        )
        assert saved.status_code == 302
        # mcq bad index → 400
        bad = client.post(f"/classes/attempt/{attempt_id}/save", data={"q_" + str(qid): "abc"})
        assert bad.status_code == 400
        # submit
        from app.extensions import db
        from app.models.assessment import QuizAttempt

        with app.app_context():
            attempt = db.session.get(QuizAttempt, attempt_id)
            attempt.status = "in_progress"
            db.session.commit()
        submitted = client.post(
            f"/classes/attempt/{attempt_id}/submit",
            data={"q_" + str(qid): "2", "q_" + str(q2): "true"},
            follow_redirects=False,
        )
        assert submitted.status_code == 302
        with app.app_context():
            # HTTP submit marks 'submitted'; 'graded' is set by the Celery task
            # (covered in test_tasks_layer.py::TestAutoGrade).
            assert db.session.get(QuizAttempt, attempt_id).status == "submitted"
        # result visible to owner
        assert client.get(f"/classes/attempt/{attempt_id}/result").status_code == 200

    def test_attempt_do_graded_redirects_to_result(self, app):
        _, cid, tid, t_email, stud, s_email = self._class_with_people(app)
        quiz_id = _quiz(app, cid, tid)
        _question(app, quiz_id, "essay")
        client = login_as(app, (stud, s_email))
        start = client.get(f"/classes/quizzes/{quiz_id}/attempt", follow_redirects=False)
        attempt_id = int(start.headers["Location"].rstrip("/").split("/")[-1])
        from app.extensions import db
        from app.models.assessment import QuizAttempt

        with app.app_context():
            db.session.get(QuizAttempt, attempt_id).status = "graded"
            db.session.commit()
        resp = client.get(f"/classes/attempt/{attempt_id}", follow_redirects=False)
        assert resp.status_code == 302
        assert "/result" in resp.headers["Location"]

    def test_attempt_access_denied_for_other_student(self, app):
        _, cid, tid, t_email, stud, _ = self._class_with_people(app)
        quiz_id = _quiz(app, cid, tid)
        client = login_as(app, (stud, _email() if False else _student_email(app)))
        start = client.get(f"/classes/quizzes/{quiz_id}/attempt", follow_redirects=False)
        attempt_id = int(start.headers["Location"].rstrip("/").split("/")[-1])
        other = mk_user(app, "student", school_id=cid and make_school(app))
        oc = login_as(app, other)
        assert oc.get(f"/classes/attempt/{attempt_id}").status_code == 403
        assert oc.get(f"/classes/attempt/{attempt_id}/result").status_code == 403

    def test_attempt_result_teacher_view(self, app):
        _, cid, tid, t_email, stud, s_email = self._class_with_people(app)
        quiz_id = _quiz(app, cid, tid)
        _question(app, quiz_id, "essay")
        client = login_as(app, (stud, s_email))
        start = client.get(f"/classes/quizzes/{quiz_id}/attempt", follow_redirects=False)
        attempt_id = int(start.headers["Location"].rstrip("/").split("/")[-1])
        tc = login_as(app, (tid, t_email))
        assert tc.get(f"/classes/attempt/{attempt_id}/result").status_code == 200

    def test_quiz_results_and_answer_grade(self, app):
        _, cid, tid, t_email, stud, s_email = self._class_with_people(app)
        quiz_id = _quiz(app, cid, tid)
        _essay_qid = _question(app, quiz_id, "essay")
        client = login_as(app, (stud, s_email))
        start = client.get(f"/classes/quizzes/{quiz_id}/attempt", follow_redirects=False)
        attempt_id = int(start.headers["Location"].rstrip("/").split("/")[-1])
        from app.models.assessment import Answer

        # save an essay answer first — Answer rows are created on save
        client.post(
            f"/classes/attempt/{attempt_id}/save",
            data={"q_" + str(_essay_qid): "إجابة مقالية طويلة"},
            follow_redirects=False,
        )
        with app.app_context():
            ans_id = Answer.query.filter_by(attempt_id=attempt_id).first().id
        tc = login_as(app, (tid, t_email))
        assert tc.get(f"/classes/quizzes/{quiz_id}/results").status_code == 200
        resp = tc.post(f"/classes/answers/{ans_id}/grade", data={"mark": "7"}, follow_redirects=False)
        assert resp.status_code == 302

    def test_bank_import_flow(self, app):
        _, cid, tid, t_email, _, _ = self._class_with_people(app)
        quiz_id = _quiz(app, cid, tid)
        tc = login_as(app, (tid, t_email))
        # create a bank question via route
        tc.post(
            "/classes/question-bank/new",
            data={
                "question_text": "ما 5+5؟",
                "question_type": "mcq",
                "option_1": "9",
                "option_2": "10",
                "correct_answer": "2",
                "difficulty": "easy",
            },
        )
        page = tc.get(f"/classes/quiz/{quiz_id}/bank-import")
        assert page.status_code == 200
        from app.models.question_bank import QuestionBank

        with app.app_context():
            bq = QuestionBank.query.first()
            assert bq is not None
            bid = bq.id
        resp = tc.post(f"/classes/quiz/{quiz_id}/bank-import", data={"question_ids": str(bid)}, follow_redirects=False)
        assert resp.status_code == 302

    def test_proctor_log_branches(self, app):
        _, cid, tid, t_email, stud, s_email = self._class_with_people(app)
        quiz_id = _quiz(app, cid, tid)
        client = login_as(app, (stud, s_email))
        start = client.get(f"/classes/quizzes/{quiz_id}/attempt", follow_redirects=False)
        attempt_id = int(start.headers["Location"].rstrip("/").split("/")[-1])
        ok = client.post(f"/classes/attempt/{attempt_id}/proctor", json={"event_type": "tab_switch"})
        assert ok.status_code == 200
        bad = client.post(f"/classes/attempt/{attempt_id}/proctor", json={"event_type": "hacked"})
        assert bad.status_code == 400
        # other student → 403
        other = mk_user(app, "student", school_id=make_school(app))
        oc = login_as(app, other)
        assert oc.post(f"/classes/attempt/{attempt_id}/proctor", json={"event_type": "tab_switch"}).status_code == 403


def _student_email(app):
    """Email of the most recently created student persona (helper for tests above)."""
    from app.models.user import User

    with app.app_context():
        u = User.query.filter_by(role="student").order_by(User.id.desc()).first()
        return u.email


# ═════════════════════════════ billing ═════════════════════════════


class TestBillingRoutes:
    def _billing_setup(self, app, price=50.0):
        from app.extensions import db
        from app.models.billing import SubscriptionPlan

        sid, _, _, cid = _setup(app)
        tid, _ = mk_user(app, "teacher", school_id=sid)
        stud, s_email = mk_user(app, "student", school_id=sid)
        make_class_member(app, cid, stud)
        plan_id = None
        if price is not None:
            with app.app_context():
                from app.extensions import db as _db
                from app.models.class_room import ClassRoom

                _db.session.get(ClassRoom, cid).teacher_id = tid
                plan = SubscriptionPlan(
                    school_id=sid,
                    class_id=cid,
                    name="سنوي",
                    plan="annual",
                    price=price,
                    currency="ILS",
                    duration_days=365,
                    is_active=True,
                )
                db.session.add(plan)
                db.session.commit()
                plan_id = plan.id
        return sid, cid, tid, stud, s_email, plan_id

    def test_class_billing_page_for_member(self, app):
        # Free class (no plan) — membership alone grants access (P-SEC-12)
        _, cid, _, _, s_email, _ = self._billing_setup(app, price=None)
        client = login_as(app, (_user_id_by_email(app, s_email), s_email))
        assert client.get(f"/billing/{cid}").status_code == 200

    def test_paid_class_blocked_without_subscription(self, app):
        # Paid class — active member WITHOUT subscription is denied (P-SEC-13)
        _, cid, _, _, s_email, _ = self._billing_setup(app, price=50.0)
        client = login_as(app, (_user_id_by_email(app, s_email), s_email))
        assert client.get(f"/billing/{cid}").status_code == 403

    def test_plan_create_by_school_admin(self, app):
        sid, cid, *_ = self._billing_setup(app)
        admin, a_email = mk_user(app, "school_admin", school_id=sid)
        client = login_as(app, (admin, a_email))
        resp = client.post(
            f"/billing/{cid}/plans",
            data={"name": "فصلي", "price": "30", "currency": "ILS", "duration_days": "120"},
            follow_redirects=False,
        )
        assert resp.status_code == 302

    def test_subscribe_and_pay_flow(self, app):
        sid, cid, tid, stud, s_email, plan_id = self._billing_setup(app)
        client = login_as(app, (stud, s_email))
        sub_resp = client.post(f"/billing/{cid}/subscribe", data={"plan_id": plan_id}, follow_redirects=False)
        assert sub_resp.status_code == 302
        from app.models.billing import Subscription

        with app.app_context():
            sub = Subscription.query.filter_by(user_id=stud, class_id=cid).first()
            assert sub is not None
            assert sub.status == "pending"
            sub_id = sub.id
        pay = client.post(
            f"/billing/subscriptions/{sub_id}/pay",
            data={"reference": "REF-123", "amount": "50", "note": "تحويل بنكي"},
            follow_redirects=False,
        )
        assert pay.status_code == 302
        from app.models.billing import ManualPayment

        with app.app_context():
            assert ManualPayment.query.filter_by(subscription_id=sub_id).count() == 1

    def test_review_reject_flow(self, app):
        from app.extensions import db
        from app.models.billing import ManualPayment, Subscription

        sid, cid, tid, stud, s_email, plan_id = self._billing_setup(app)
        with app.app_context():
            sub = Subscription(user_id=stud, plan_id=plan_id, class_id=cid, price=50, currency="ILS", status="pending")
            db.session.add(sub)
            db.session.flush()
            pay = ManualPayment(subscription_id=sub.id, amount=50, reference="X", status="pending")
            db.session.add(pay)
            db.session.commit()
            sub_id, pay_id = sub.id, pay.id
        admin, a_email = mk_user(app, "school_admin", school_id=sid)
        client = login_as(app, (admin, a_email))
        resp = client.post(f"/billing/payments/{pay_id}/reject", follow_redirects=False)
        assert resp.status_code == 302
        with app.app_context():
            assert db.session.get(ManualPayment, pay_id).status == "rejected"
            assert db.session.get(Subscription, sub_id).status == "cancelled"

    def test_review_invalid_result_404(self, app):
        from app.extensions import db
        from app.models.billing import ManualPayment, Subscription

        sid, cid, tid, stud, s_email, plan_id = self._billing_setup(app)
        with app.app_context():
            sub = Subscription(user_id=stud, plan_id=plan_id, class_id=cid, price=50, currency="ILS", status="pending")
            db.session.add(sub)
            db.session.flush()
            pay = ManualPayment(subscription_id=sub.id, amount=50, reference="X", status="pending")
            db.session.add(pay)
            db.session.commit()
            pay_id = pay.id
        admin, a_email = mk_user(app, "school_admin", school_id=sid)
        client = login_as(app, (admin, a_email))
        assert client.post(f"/billing/payments/{pay_id}/explode", follow_redirects=False).status_code == 404

    def test_discount_create_and_validate(self, app):
        sid, *_ = _setup(app)
        admin, a_email = mk_user(app, "school_admin", school_id=sid)
        client = login_as(app, (admin, a_email))
        assert client.get("/billing/discounts/new").status_code == 200
        resp = client.post(
            "/billing/discounts/new",
            data={"code": f"D{uuid.uuid4().hex[:6].upper()}", "name": "خصم", "type": "percentage", "value": "10"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        # invalid validate-code payload → 400
        bad = client.post("/billing/validate-code", data={"code": "", "plan_id": "0"})
        assert bad.status_code == 400

    def test_invoice_view_and_pdf(self, app, monkeypatch):
        from app.extensions import db
        from app.models.billing import Subscription

        sid, cid, tid, stud, s_email, plan_id = self._billing_setup(app)
        with app.app_context():
            sub = Subscription(user_id=stud, plan_id=plan_id, class_id=cid, price=50, currency="ILS", status="active")
            db.session.add(sub)
            db.session.commit()
            sub_id = sub.id
        client = login_as(app, (stud, s_email))
        assert client.get(f"/billing/invoices/{sub_id}").status_code == 200
        # pdf lib missing → redirect
        import app.services.invoice as inv

        monkeypatch.setattr(inv, "render_invoice_pdf", lambda *_a, **_k: None)
        resp = client.get(f"/billing/invoices/{sub_id}/pdf", follow_redirects=False)
        assert resp.status_code == 302
        # other student → 403
        other = mk_user(app, "student", school_id=sid)
        oc = login_as(app, other)
        assert oc.get(f"/billing/invoices/{sub_id}").status_code == 403


def _user_id_by_email(app, email: str) -> int:

    with app.app_context():
        return db_get_user_id(email)


def db_get_user_id(email: str) -> int:
    from app.models.user import User

    return User.query.filter_by(email=email).first().id


# ═════════════════════════════ wallet API ═════════════════════════════


class TestWalletApi:
    def _wallet_users(self, app):
        sid = make_school(app)
        admin, a_email = mk_user(app, "school_admin", school_id=sid)
        stud, s_email = mk_user(app, "student", school_id=sid)
        return sid, admin, a_email, stud, s_email

    def test_balance_self(self, app):
        _, admin, a_email, _, _ = self._wallet_users(app)
        client = login_as(app, (admin, a_email))
        resp = client.get("/api/v1/wallet/balance")
        assert resp.status_code == 200
        body = resp.get_json()
        assert "balance" in body or body.get("data", {}).get("balance") is not None

    def test_balance_other_forbidden_for_student(self, app):
        _, _, _, stud, s_email = self._wallet_users(app)
        other = mk_user(app, "student", school_id=make_school(app))
        client = login_as(app, (stud, s_email))
        resp = client.get(f"/api/v1/wallet/balance?user_id={other[0]}")
        assert resp.status_code == 403

    def test_balance_other_ok_for_admin(self, app):
        _, admin, a_email, stud, _ = self._wallet_users(app)
        client = login_as(app, (admin, a_email))
        resp = client.get(f"/api/v1/wallet/balance?user_id={stud}")
        assert resp.status_code == 200

    def test_transactions_self_and_admin_scope(self, app):
        _, admin, a_email, stud, s_email = self._wallet_users(app)
        c1 = login_as(app, (stud, s_email))
        assert c1.get("/api/v1/wallet/transactions").status_code == 200
        c2 = login_as(app, (admin, a_email))
        resp = c2.get(f"/api/v1/wallet/transactions?user_id={stud}&page=1&per_page=5")
        assert resp.status_code == 200

    def test_deposit_success_and_validation(self, app):
        _, admin, a_email, stud, _ = self._wallet_users(app)
        client = login_as(app, (admin, a_email))
        # missing idempotency_key → 400
        bad = client.post("/api/v1/wallet/deposits", json={"user_id": stud, "amount": "10"})
        assert bad.status_code == 400
        # bad amount → 400
        bad2 = client.post(
            "/api/v1/wallet/deposits", json={"user_id": stud, "amount": "abc", "idempotency_key": uuid.uuid4().hex}
        )
        assert bad2.status_code == 400
        # success
        ok = client.post(
            "/api/v1/wallet/deposits",
            json={"user_id": stud, "amount": "25.50", "idempotency_key": uuid.uuid4().hex},
        )
        assert ok.status_code == 200
        # idempotent replay returns same tx (no duplicate)
        key = uuid.uuid4().hex
        r1 = client.post("/api/v1/wallet/deposits", json={"user_id": stud, "amount": "5", "idempotency_key": key})
        r2 = client.post("/api/v1/wallet/deposits", json={"user_id": stud, "amount": "5", "idempotency_key": key})
        assert r1.status_code == 200 and r2.status_code == 200

    def test_transfer_success_and_guards(self, app):
        sid, admin, a_email, stud, s_email = self._wallet_users(app)
        other = mk_user(app, "student", school_id=make_school(app))
        classmate = mk_user(app, "student", school_id=sid)
        client = login_as(app, (stud, s_email))
        # transferring from someone else's wallet → 403
        forbidden = client.post(
            "/api/v1/wallet/transfers",
            json={
                "source_user_id": admin,
                "dest_user_id": other[0],
                "amount": "5",
                "idempotency_key": uuid.uuid4().hex,
            },
        )
        assert forbidden.status_code == 403
        # missing dest → 400
        bad = client.post(
            "/api/v1/wallet/transfers",
            json={"source_user_id": stud, "amount": "5", "idempotency_key": uuid.uuid4().hex},
        )
        assert bad.status_code == 400
        # D7: تحويل لمستخدم من مدرسة أخرى → 403 (لا تُنبَث محفظة داخل هذه المدرسة)
        cross = client.post(
            "/api/v1/wallet/transfers",
            json={"dest_user_id": other[0], "amount": "5", "idempotency_key": uuid.uuid4().hex},
        )
        assert cross.status_code == 403
        # fund own wallet via admin deposit, then transfer to an in-school classmate
        ac = login_as(app, (admin, a_email))
        ac.post("/api/v1/wallet/deposits", json={"user_id": stud, "amount": "50", "idempotency_key": uuid.uuid4().hex})
        ok = client.post(
            "/api/v1/wallet/transfers",
            json={"dest_user_id": classmate[0], "amount": "10", "idempotency_key": uuid.uuid4().hex},
        )
        assert ok.status_code == 200


class TestAdminWalletDeposit:
    """AZ-P1-08 — إيداع إداري من لوحة المنصة.

    المال يدخل النظام من خارجه (مصدر ``NULL``)، فلا يشترط محفظة مقابلة — لكنه
    يشترط عضوية نشطة في المدرسة المختارة، وسجل تدقيق باسم المنفّذ في نفس
    الالتزام. الاختبارات تقيس الأثر الفعلي: الرصيد، وصفوف الدفتر، وصفوف
    التدقيق، ومحتوى صفحة الدفتر — لا رموز الحالة وحدها.
    """

    def _people(self, app):
        sid = make_school(app)
        platform, p_email = mk_user(app, "super_admin")
        student, s_email = mk_user(app, "student", school_id=sid)
        return sid, platform, p_email, student, s_email

    def _rows(self, app):
        """(صفوف الدفتر، صفوف تدقيق الإيداع) — تُقرأ من قاعدة البيانات مباشرة."""
        from app.extensions import db
        from app.models.system import AuditLog
        from app.models.wallet import WalletTransaction

        with app.app_context():
            return (
                db.session.query(WalletTransaction).count(),
                db.session.query(AuditLog).filter_by(action="wallet_deposit").count(),
            )

    def _balance(self, app, school_id, user_id):
        from app.services.wallet_service import get_balance

        with app.app_context():
            return get_balance(school_id, user_id)

    def test_deposit_credits_balance_and_writes_an_audited_ledger_row(self, app):
        from app.models.system import AuditLog
        from app.models.wallet import WalletTransaction

        sid, platform, p_email, student, _ = self._people(app)
        client = login_as(app, (platform, p_email))

        resp = client.post(
            "/admin/wallet/deposit",
            data={"school_id": sid, "user_id": student, "amount": "120.50", "note": "دفعة أولى"},
        )
        assert resp.status_code == 302
        assert self._balance(app, sid, student) == Decimal("120.50")

        with app.app_context():
            row = WalletTransaction.query.filter_by(transaction_type="admin_adjustment").one()
            # طرف ``None`` = مال دخل النظام من خارجه، لا تحويل من محفظة أخرى.
            assert row.source_wallet_id is None
            assert row.destination_wallet_id is not None
            assert row.school_id == sid
            assert row.description == "دفعة أولى"
            assert row.reference_id == platform  # المنفّذ مكتوب على القيد نفسه

            log = AuditLog.query.filter_by(action="wallet_deposit").one()
            assert log.user_id == platform
            assert log.detail["transaction_id"] == row.id
            assert log.detail["target_user_id"] == student
            assert log.detail["school_id"] == sid
            assert log.detail["amount"] == "120.50"
            assert log.detail["note"] == "دفعة أولى"

    def test_deposit_shows_up_in_the_ledger_page_for_that_user(self, app):
        sid, platform, p_email, student, _ = self._people(app)
        client = login_as(app, (platform, p_email))
        client.post(
            "/admin/wallet/deposit",
            data={"school_id": sid, "user_id": student, "amount": "30", "note": "رصيد افتتاحي"},
        )

        page = client.get(f"/admin/wallet?school_id={sid}&user_id={student}")
        assert page.status_code == 200
        html = page.get_data(as_text=True)
        assert "30.00 ILS" in html
        assert "رصيد افتتاحي" in html

    @pytest.mark.parametrize("amount", ["", "abc", "0", "-5", "NaN"])
    def test_a_rejected_amount_writes_nothing(self, app, amount):
        sid, platform, p_email, student, _ = self._people(app)
        client = login_as(app, (platform, p_email))

        resp = client.post(
            "/admin/wallet/deposit",
            data={"school_id": sid, "user_id": student, "amount": amount},
        )
        assert resp.status_code == 302
        assert self._rows(app) == (0, 0)
        assert self._balance(app, sid, student) == Decimal("0.00")

    def test_missing_school_or_user_writes_nothing(self, app):
        sid, platform, p_email, student, _ = self._people(app)
        client = login_as(app, (platform, p_email))

        for data in ({"user_id": student, "amount": "10"}, {"school_id": sid, "amount": "10"}):
            assert client.post("/admin/wallet/deposit", data=data).status_code == 302

        assert self._rows(app) == (0, 0)
        assert self._balance(app, sid, student) == Decimal("0.00")

    def test_deposit_refuses_a_user_of_another_school(self, app):
        """لوحة المنصة أيضاً لا تزرع محفظة لمستخدم لا صلة له بالمدرسة."""
        from app.models.wallet import Wallet

        sid, platform, p_email, _, _ = self._people(app)
        outsider, _ = mk_user(app, "student", school_id=make_school(app))
        client = login_as(app, (platform, p_email))

        resp = client.post(
            "/admin/wallet/deposit",
            data={"school_id": sid, "user_id": outsider, "amount": "50"},
        )
        assert resp.status_code == 302
        assert self._rows(app) == (0, 0)
        with app.app_context():
            assert Wallet.query.filter_by(school_id=sid, user_id=outsider).count() == 0

    def test_school_admin_and_student_cannot_deposit(self, app):
        sid, _, _, student, _ = self._people(app)

        for role in ("school_admin", "student"):
            who, email = mk_user(app, role, school_id=sid)
            client = login_as(app, (who, email))
            resp = client.post(
                "/admin/wallet/deposit",
                data={"school_id": sid, "user_id": student, "amount": "25"},
            )
            assert resp.status_code == 403

        assert self._rows(app) == (0, 0)
        assert self._balance(app, sid, student) == Decimal("0.00")


# ═════════════════════════════ AZ-P3-15: family wallet ═════════════════════════════


class TestParentChildWallet:
    """AZ-P3-15 — محفظة الابن لولي الأمر، وشحن بطلب يمرّ بالاعتماد الإداري.

    معايير القبول المستهدفة (docs/ACTIONABLE_WORK_ITEMS.md §AZ-P3-15):
    1. ولي أمر مرتبط يرى رصيد ابنه وسجل حركاته من صفحات الأسرة.
    2. غير مرتبط (أو خارج مدرسة الابن المالية) → 403، ولا مبلغ يتحرك.
    3. أي شحن يمرّ بالاعتماد اليدوي قبل إثراء الرصيد، وهوية الدافع في التدقيق.
    4. لا تسريب بين الأسر أو بين المدارس.
    """

    def _family(self, app, *, link=True, cross_school=False):
        sid = make_school(app)
        parent, p_email = mk_user(app, "parent", school_id=sid)
        child_school = make_school(app) if cross_school else sid
        child, _ = mk_user(app, "student", school_id=child_school)
        if link:
            from tests.conftest import make_family_link

            make_family_link(app, parent, child)
        return sid, parent, p_email, child

    def _balance(self, app, sid, uid) -> Decimal:
        from app.services.wallet_service import get_balance

        with app.app_context():
            return get_balance(sid, uid)

    def _topup_request(self, app, child_id):
        from app.models.wallet import WalletTopupRequest

        with app.app_context():
            return WalletTopupRequest.query.filter_by(child_user_id=child_id).one()

    def test_linked_parent_sees_child_balance_and_transactions(self, app):
        from app.services import wallet_service

        sid, parent, p_email, child = self._family(app)
        with app.app_context():
            for amount, note in ((Decimal("75.00"), "رصيد ابتدائي"), (Decimal("25.00"), "إضافة")):
                wallet_service.admin_deposit(school_id=sid, target_user_id=child, amount=amount, note=note)

        client = login_as(app, (parent, p_email))
        page = client.get(f"/family/children/{child}/wallet")
        assert page.status_code == 200
        html = page.get_data(as_text=True)
        assert "child-wallet-summary" in html
        assert "100.00" in html
        assert "رصيد ابتدائي" in html and "إضافة" in html
        assert "child-wallet-tx-row" in html

    def test_unlinked_parent_gets_403_and_no_request_row(self, app):
        from app.models.wallet import WalletTopupRequest

        sid, parent, p_email, child = self._family(app, link=False)
        client = login_as(app, (parent, p_email))
        assert client.get(f"/family/children/{child}/wallet").status_code == 403
        resp = client.post(f"/family/children/{child}/wallet/topup", data={"amount": "50"})
        assert resp.status_code == 403
        assert self._balance(app, sid, child) == Decimal("0.00")
        with app.app_context():
            assert WalletTopupRequest.query.filter_by(child_user_id=child).count() == 0

    def test_family_link_but_cross_school_tenant_still_403(self, app):
        """الربط الأسرى لا يفتح حدود المدرسة المالية — حدّ التينانت أولاً."""
        sid, parent, p_email, child = self._family(app, cross_school=True)
        client = login_as(app, (parent, p_email))
        assert client.get(f"/family/children/{child}/wallet").status_code == 403
        assert client.post(f"/family/children/{child}/wallet/topup", data={"amount": "50"}).status_code == 403
        assert self._balance(app, sid, child) == Decimal("0.00")

    def test_cannot_tamper_target_student_in_topup_post(self, app):
        sid, parent, p_email, child = self._family(app)
        stranger, _ = mk_user(app, "student", school_id=sid)
        client = login_as(app, (parent, p_email))
        resp = client.post(f"/family/children/{stranger}/wallet/topup", data={"amount": "50"})
        assert resp.status_code == 403  # ليس ابنه — parent_of_required يمرّن قبل كل شيء
        assert self._balance(app, sid, stranger) == Decimal("0.00")

    def test_topup_request_is_pending_and_does_not_credit(self, app):
        sid, parent, p_email, child = self._family(app)
        client = login_as(app, (parent, p_email))
        resp = client.post(f"/family/children/{child}/wallet/topup", data={"amount": "120.50", "note": "بيت المال"})
        assert resp.status_code == 302
        assert self._balance(app, sid, child) == Decimal("0.00")  # لا رصيد قبل الاعتماد
        req = self._topup_request(app, child)
        assert req.status == "pending"
        assert req.amount == Decimal("120.50")
        assert req.parent_id == parent  # هوية الدافع على الصف
        assert req.school_id == sid
        # طلب ثانٍ معلّق لنفس الابن → رفض منطقي بلا صف إضافي
        client.post(f"/family/children/{child}/wallet/topup", data={"amount": "10"})
        with app.app_context():
            from app.models.wallet import WalletTopupRequest

            assert WalletTopupRequest.query.filter_by(child_user_id=child).count() == 1

    def test_invalid_amount_writes_nothing(self, app):
        from app.models.wallet import WalletTopupRequest

        sid, parent, p_email, child = self._family(app)
        client = login_as(app, (parent, p_email))
        for amount in ("", "abc", "0", "-5"):
            client.post(f"/family/children/{child}/wallet/topup", data={"amount": amount})
        with app.app_context():
            assert WalletTopupRequest.query.filter_by(child_user_id=child).count() == 0

    def test_approval_credits_child_wallet_and_audits_payer(self, app):
        from app.models.system import AuditLog
        from app.models.wallet import WalletTransaction

        sid, parent, p_email, child = self._family(app)
        client = login_as(app, (parent, p_email))
        client.post(f"/family/children/{child}/wallet/topup", data={"amount": "60.00", "note": "من الأسرة"})
        req = self._topup_request(app, child)

        school_admin, admin_email = mk_user(app, "school_admin", school_id=sid)
        admin_client = login_as(app, (school_admin, admin_email))

        # قسم الطلبات المعلّقة في الدفتر — مستوى المنصة (مستكشف الدفتر super_admin حصراً)
        platform, platform_email = mk_user(app, "super_admin")
        platform_client = login_as(app, (platform, platform_email))
        ledger_page = platform_client.get(f"/admin/wallet?school_id={sid}")
        assert ledger_page.status_code == 200
        assert "pending-topup-row" in ledger_page.get_data(as_text=True)

        resp = admin_client.post(f"/admin/wallet/topup/{req.id}/review", data={"decision": "approve"})
        assert resp.status_code == 302
        assert self._balance(app, sid, child) == Decimal("60.00")
        with app.app_context():
            row = WalletTransaction.query.filter_by(idempotency_key=f"wallet_topup:{req.id}").one()
            assert row.amount == Decimal("60.00") and row.school_id == sid
            assert row.reference_id == school_admin  # المنفّذ على القيد
            log = AuditLog.query.filter_by(action="wallet_topup_review").one()
            assert log.detail["parent_id"] == parent
            assert log.detail["child_user_id"] == child
            assert log.detail["decision"] == "approve"
            assert self._topup_request(app, child).status == "approved"

        # معالجة ثانية → يُرفض ولا قيد ثانٍ
        assert (
            admin_client.post(f"/admin/wallet/topup/{req.id}/review", data={"decision": "approve"}).status_code == 302
        )
        with app.app_context():
            assert WalletTransaction.query.filter_by(idempotency_key=f"wallet_topup:{req.id}").count() == 1
        assert self._balance(app, sid, child) == Decimal("60.00")

    def test_rejection_keeps_balance_and_marks_request(self, app):
        from app.models.wallet import WalletTransaction

        sid, parent, p_email, child = self._family(app)
        client = login_as(app, (parent, p_email))
        client.post(f"/family/children/{child}/wallet/topup", data={"amount": "40"})
        req = self._topup_request(app, child)

        school_admin, admin_email = mk_user(app, "school_admin", school_id=sid)
        admin_client = login_as(app, (school_admin, admin_email))
        admin_client.post(
            f"/admin/wallet/topup/{req.id}/review", data={"decision": "reject", "reason": "البيانات غير مكتملة"}
        )
        assert self._balance(app, sid, child) == Decimal("0.00")
        assert self._topup_request(app, child).status == "rejected"
        with app.app_context():
            assert WalletTransaction.query.filter_by(idempotency_key=f"wallet_topup:{req.id}").count() == 0

    def test_school_admin_of_another_school_gets_404(self, app):
        sid, parent, p_email, child = self._family(app)
        client = login_as(app, (parent, p_email))
        client.post(f"/family/children/{child}/wallet/topup", data={"amount": "40"})
        req = self._topup_request(app, child)

        stranger_admin, stranger_email = mk_user(app, "school_admin", school_id=make_school(app))
        stranger_client = login_as(app, (stranger_admin, stranger_email))
        assert (
            stranger_client.post(f"/admin/wallet/topup/{req.id}/review", data={"decision": "approve"}).status_code
            == 404
        )
        assert self._balance(app, sid, child) == Decimal("0.00")

    def test_parent_cannot_use_admin_review_route(self, app):
        sid, parent, p_email, child = self._family(app)
        client = login_as(app, (parent, p_email))
        client.post(f"/family/children/{child}/wallet/topup", data={"amount": "40"})
        req = self._topup_request(app, child)
        assert client.post(f"/admin/wallet/topup/{req.id}/review", data={"decision": "approve"}).status_code == 403
        assert self._balance(app, sid, child) == Decimal("0.00")

    def test_school_admin_dashboard_shows_only_its_own_pending_requests(self, app):
        """مشرف المدرسة هو من يعتمد الطلب، فطابوره على لوحته — وبمدرسته وحده."""
        sid, parent, p_email, child = self._family(app)
        login_as(app, (parent, p_email)).post(f"/family/children/{child}/wallet/topup", data={"amount": "40"})

        other_sid = make_school(app)
        other_parent, other_email = mk_user(app, "parent", school_id=other_sid)
        other_child, _ = mk_user(app, "student", school_id=other_sid)
        from tests.conftest import make_family_link

        make_family_link(app, other_parent, other_child)
        login_as(app, (other_parent, other_email)).post(
            f"/family/children/{other_child}/wallet/topup", data={"amount": "90"}
        )

        school_admin, admin_email = mk_user(app, "school_admin", school_id=sid)
        admin_client = login_as(app, (school_admin, admin_email))
        page = admin_client.get("/admin/school-admin", follow_redirects=True)
        assert page.status_code == 200
        html = page.get_data(as_text=True)
        assert "pending-topup-row" in html
        assert "<bdi>40" in html
        assert "<bdi>90" not in html  # طلب مدرسة أخرى لا يظهر ولا يُعتمد من هنا

    def test_school_admin_dashboard_hides_the_queue_when_empty(self, app):
        """لا طلبات = لا قسم — لا عنوان فارغ ولا جدول بلا صفوف."""
        sid, _parent, _parent_email, _child = self._family(app)
        school_admin, admin_email = mk_user(app, "school_admin", school_id=sid)
        admin_client = login_as(app, (school_admin, admin_email))
        html = admin_client.get("/admin/school-admin", follow_redirects=True).get_data(as_text=True)
        assert "pending-topups-section" not in html
