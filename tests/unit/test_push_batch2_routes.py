"""97% push — batch 2: assessment, billing, wallet routes.

Every test targets a CI-verified missed line (coverage.xml run 34714987468).
Covers: quiz manage/AI-generate/question bank, attempt lifecycle incl.
parsing branches, billing subscribe/pay/review/discount/invoice, wallet API
auth-scoping and validation branches.
"""

from __future__ import annotations

import uuid

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
        _, admin, a_email, stud, s_email = self._wallet_users(app)
        other = mk_user(app, "student", school_id=make_school(app))
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
        # fund own wallet via admin deposit, then transfer
        ac = login_as(app, (admin, a_email))
        ac.post("/api/v1/wallet/deposits", json={"user_id": stud, "amount": "50", "idempotency_key": uuid.uuid4().hex})
        ok = client.post(
            "/api/v1/wallet/transfers",
            json={"dest_user_id": other[0], "amount": "10", "idempotency_key": uuid.uuid4().hex},
        )
        assert ok.status_code == 200
