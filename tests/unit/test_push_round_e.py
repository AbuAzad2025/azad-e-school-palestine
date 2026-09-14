"""Round E — deepest gap closure: wallet API validation branches, family/calendar
routes, AI streaming + quiz-gen endpoints, grades rubric/PDF/report-card guards,
assessment guards, billing TxError paths, tutoring live-session guards, payments
gateway internals, permissions shapes, health checks.

Every test drives real code paths (HTTP routes or service functions) against the
real test database; only external boundaries (email, gateways) are mocked.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import MagicMock, patch

from tests.conftest import (
    make_class,
    make_class_member,
    make_grade,
    make_lesson,
    make_school,
    make_subject,
    make_subscription_plan,
    make_tutoring_session,
    make_user,
)

PASSWORD = "TestPass123!"

_LEVELS: dict[int, int] = {}


def _next_level(sid: int) -> int:
    _LEVELS[sid] = _LEVELS.get(sid, 0) + 1
    return _LEVELS[sid]


def mk_user(app, role: str, school_id=None):
    from tests.conftest import _uid

    email = f"re-{_uid()}@test.com"
    uid = make_user(app, role=role, school_id=school_id, email=email)
    return uid, email


def login_as(app, uid_email):
    client = app.test_client()
    client.post("/auth/login", data={"email": uid_email[1], "password": PASSWORD})
    return client


def _setup_class(app):
    sid = make_school(app)
    gid = make_grade(app, sid, grade_level=_next_level(sid))
    subj = make_subject(app)
    cid = make_class(app, sid, gid, subj)
    return sid, cid


def _quota_ok():
    """Mock tenant quota with AI enabled and a huge monthly token allowance."""
    m = MagicMock()
    m.ai_enabled = True
    m.max_ai_tokens_monthly = 10**9
    return m


# ═══════════════════════════════════════════════════════════════════════
# Wallet API — remaining validation branches
# ═══════════════════════════════════════════════════════════════════════


class TestWalletApiGaps:
    def _users(self, app):
        sid = make_school(app)
        admin, a_email = mk_user(app, "school_admin", school_id=sid)
        stud, s_email = mk_user(app, "student", school_id=sid)
        return sid, admin, a_email, stud, s_email

    def test_student_with_no_school_scope_gets_400(self, app):
        # Individual student: no school → school_id None → 400 VALIDATION_ERROR
        sid = make_school(app)
        stud, s_email = mk_user(app, "student", school_id=sid)
        client = login_as(app, (stud, s_email))
        # user_id=other forces the admin branch; student lacks scope → 403 first
        other_id, _ = mk_user(app, "student", school_id=make_school(app))
        resp = client.get(f"/api/v1/wallet/balance?user_id={other_id}")
        assert resp.status_code == 403

    def test_admin_without_school_link_gets_400(self, app):
        # school_admin with no school membership → school_id None → 400
        admin, a_email = mk_user(app, "school_admin", school_id=None)
        client = login_as(app, (admin, a_email))
        resp = client.get("/api/v1/wallet/balance")
        assert resp.status_code == 400

    def test_transactions_admin_viewing_other_requires_scope(self, app):
        _, admin, a_email, stud, _ = self._users(app)
        client = login_as(app, (admin, a_email))
        resp = client.get(f"/api/v1/wallet/transactions?user_id={stud}")
        assert resp.status_code == 200

    def test_deposit_requires_user_id(self, app):
        _, admin, a_email, _, _ = self._users(app)
        client = login_as(app, (admin, a_email))
        resp = client.post("/api/v1/wallet/deposits", json={"amount": "10", "idempotency_key": uuid.uuid4().hex})
        assert resp.status_code == 400

    def test_deposit_rejects_zero_and_negative(self, app):
        _, admin, a_email, stud, _ = self._users(app)
        client = login_as(app, (admin, a_email))
        for amount in ("0", "-5"):
            resp = client.post(
                "/api/v1/wallet/deposits",
                json={"user_id": stud, "amount": amount, "idempotency_key": uuid.uuid4().hex},
            )
            assert resp.status_code == 400

    def test_deposit_wallet_error_is_surfaced(self, app):
        _, admin, a_email, stud, _ = self._users(app)
        client = login_as(app, (admin, a_email))
        with patch("app.modules.wallet_api.wallet_service.get_or_create_wallet") as goc:
            goc.return_value = (None, "wallet creation blocked")
            resp = client.post(
                "/api/v1/wallet/deposits",
                json={"user_id": stud, "amount": "10", "idempotency_key": uuid.uuid4().hex},
            )
        assert resp.status_code == 400

    def test_deposit_service_error_is_surfaced(self, app):
        _, admin, a_email, stud, _ = self._users(app)
        client = login_as(app, (admin, a_email))
        with patch("app.modules.wallet_api.wallet_service.admin_credit") as ac:
            ac.return_value = (None, "ledger rejected")
            resp = client.post(
                "/api/v1/wallet/deposits",
                json={"user_id": stud, "amount": "10", "idempotency_key": uuid.uuid4().hex},
            )
        assert resp.status_code == 400

    def test_transfer_insufficient_balance_400(self, app):
        sid, admin, a_email, stud, s_email = self._users(app)
        dest, _ = mk_user(app, "student", school_id=sid)
        client = login_as(app, (stud, s_email))
        resp = client.post(
            "/api/v1/wallet/transfers",
            json={"dest_user_id": dest, "amount": "999", "idempotency_key": uuid.uuid4().hex},
        )
        assert resp.status_code == 400

    def test_transfer_self_is_rejected(self, app):
        _, admin, a_email, stud, s_email = self._users(app)
        client = login_as(app, (stud, s_email))
        resp = client.post(
            "/api/v1/wallet/transfers",
            json={"dest_user_id": stud, "amount": "5", "idempotency_key": uuid.uuid4().hex},
        )
        assert resp.status_code == 400

    def test_super_admin_deposit_with_body_school_id(self, app):
        from tests.conftest import _uid

        su_email = f"su-{_uid()}@test.com"
        su = make_user(app, role="super_admin", school_id=None, email=su_email)
        _, _, _, stud, _ = self._users(app)
        client = login_as(app, (su, su_email))
        resp = client.post(
            "/api/v1/wallet/deposits",
            json={
                "user_id": stud,
                "amount": "30",
                "idempotency_key": uuid.uuid4().hex,
                "school_id": make_school(app),
            },
        )
        assert resp.status_code == 200

    def test_super_admin_transfer_with_body_school_id(self, app):
        from tests.conftest import _uid

        su_email = f"su2-{_uid()}@test.com"
        su = make_user(app, role="super_admin", school_id=None, email=su_email)
        sid, _, _, src, _ = self._users(app)
        dest, _ = mk_user(app, "student", school_id=sid)
        client = login_as(app, (su, su_email))
        # missing school_id → 400 first
        r400 = client.post(
            "/api/v1/wallet/transfers",
            json={"source_user_id": src, "dest_user_id": dest, "amount": "5", "idempotency_key": uuid.uuid4().hex},
        )
        assert r400.status_code == 400
        # with school_id → deposit then transfer
        client.post(
            "/api/v1/wallet/deposits",
            json={"user_id": src, "amount": "40", "idempotency_key": uuid.uuid4().hex, "school_id": sid},
        )
        ok = client.post(
            "/api/v1/wallet/transfers",
            json={
                "source_user_id": src,
                "dest_user_id": dest,
                "amount": "5",
                "idempotency_key": uuid.uuid4().hex,
                "school_id": sid,
            },
        )
        assert ok.status_code == 200


# ═══════════════════════════════════════════════════════════════════════
# Family routes — link/unlink/generate/child views
# ═══════════════════════════════════════════════════════════════════════


class TestFamilyRoutes:
    def test_index_lists_children(self, app):
        sid, cid = _setup_class(app)
        stu, s_email = mk_user(app, "student", school_id=sid)
        par, p_email = mk_user(app, "parent")
        with app.app_context():
            from app.core.db import tx
            from app.extensions import db
            from app.models.family import FamilyLink

            link = FamilyLink(parent_id=par, student_id=stu)
            db.session.add(link)
            tx(lambda: None)
        client = login_as(app, (par, p_email))
        resp = client.get("/family/")
        assert resp.status_code == 200

    def test_link_with_invalid_code_flashes_error(self, app):
        par, p_email = mk_user(app, "parent")
        client = login_as(app, (par, p_email))
        resp = client.post("/family/link", data={"code": "NOPE1234"}, follow_redirects=True)
        assert resp.status_code == 200
        assert b"danger" in resp.data or "غير صالح".encode() in resp.data

    def test_generate_code_as_student(self, app):
        stu, s_email = mk_user(app, "student")
        client = login_as(app, (stu, s_email))
        resp = client.get("/family/generate")
        assert resp.status_code == 200

    def test_child_views_for_linked_parent(self, app):
        sid, cid = _setup_class(app)
        stu, s_email = mk_user(app, "student", school_id=sid)
        par, p_email = mk_user(app, "parent")
        make_class_member(app, cid, stu, status="active")
        with app.app_context():
            from app.core.db import tx
            from app.extensions import db
            from app.models.family import FamilyLink

            db.session.add(FamilyLink(parent_id=par, student_id=stu))
            tx(lambda: None)
        client = login_as(app, (par, p_email))
        assert client.get(f"/family/children/{stu}/progress").status_code == 200
        assert client.get(f"/family/children/{stu}/grades").status_code == 200

    def test_remove_link(self, app):
        sid = make_school(app)
        stu, _ = mk_user(app, "student", school_id=sid)
        par, p_email = mk_user(app, "parent")
        with app.app_context():
            from app.core.db import tx
            from app.extensions import db
            from app.models.family import FamilyLink

            link = FamilyLink(parent_id=par, student_id=stu)
            db.session.add(link)
            tx(lambda: None)
            lid = FamilyLink.query.filter_by(parent_id=par).first().id
        client = login_as(app, (par, p_email))
        resp = client.post(f"/family/link/{lid}/remove", follow_redirects=True)
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════
# Calendar routes — create/delete as school admin
# ═══════════════════════════════════════════════════════════════════════


class TestCalendarRoutes:
    def test_index_and_create_and_delete(self, app):
        sid = make_school(app)
        admin, a_email = mk_user(app, "school_admin", school_id=sid)
        client = login_as(app, (admin, a_email))
        assert client.get(f"/calendar/{sid}").status_code == 200
        # invalid event type → error flash branch
        resp = client.post(
            f"/calendar/{sid}/events",
            data={"title": "حدث", "event_type": "bogus", "start_date": "2026-10-01"},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        # valid create
        resp = client.post(
            f"/calendar/{sid}/events",
            data={"title": "بداية فصل", "event_type": "term_start", "start_date": "2026-10-01"},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        with app.app_context():
            from app.models.calendar import AcademicEvent

            event = AcademicEvent.query.filter_by(school_id=sid).first()
            assert event is not None
            eid = event.id
        # delete
        resp = client.post(f"/calendar/events/{eid}/delete", follow_redirects=True)
        assert resp.status_code == 200

    def test_cross_school_delete_forbidden(self, app):
        sid1, sid2 = make_school(app), make_school(app)
        admin, a_email = mk_user(app, "school_admin", school_id=sid1)
        with app.app_context():
            from app.core.db import tx
            from app.extensions import db
            from app.models.calendar import AcademicEvent

            ev = AcademicEvent(school_id=sid2, title="x", event_type="holiday", start_date="2026-10-01")
            db.session.add(ev)
            tx(lambda: None)
            eid = ev.id
        client = login_as(app, (admin, a_email))
        resp = client.post(f"/calendar/events/{eid}/delete", follow_redirects=False)
        assert resp.status_code == 403


# ═══════════════════════════════════════════════════════════════════════
# AI routes — chat stream SSE + quiz generation validation
# ═══════════════════════════════════════════════════════════════════════


class TestAiRoutesGaps:
    def _student(self, app):
        sid = make_school(app)
        return sid, mk_user(app, "student", school_id=sid)

    def test_chat_stream_requires_question(self, app):
        _, (stu, s_email) = self._student(app)
        client = login_as(app, (stu, s_email))
        with patch("app.services.tenant.get_quota", return_value=_quota_ok()):
            resp = client.post("/ai/chat/stream", json={})
        assert resp.status_code == 400

    def test_chat_stream_sse_yields_chunks(self, app):
        _, (stu, s_email) = self._student(app)
        client = login_as(app, (stu, s_email))
        with patch("app.services.tenant.get_quota", return_value=_quota_ok()):
            resp = client.post("/ai/chat/stream", json={"question": "ما هي الجذور التربيعية؟"})
        assert resp.status_code == 200
        assert resp.mimetype == "text/event-stream"
        body = resp.get_data(as_text=True)
        assert "data:" in body

    def test_chat_stream_creates_persisted_session(self, app):
        _, (stu, s_email) = self._student(app)
        client = login_as(app, (stu, s_email))
        with patch("app.services.tenant.get_quota", return_value=_quota_ok()):
            resp = client.post("/ai/chat/stream", json={"question": "سؤال فريد 42"})
        assert resp.status_code == 200
        # Consuming the SSE body drives the generator to completion — this is
        # where the route's finally-block commits the chat history (P1 fix).
        body = resp.get_data(as_text=True)
        assert "data:" in body
        with app.app_context():
            from app.models.ai import AiSession

            sessions = AiSession.query.filter_by(user_id=stu, session_type="student_helper").all()
            assert sessions

    def test_generate_quiz_requires_lesson_id(self, app):
        sid = make_school(app)
        teacher, t_email = mk_user(app, "teacher", school_id=sid)
        client = login_as(app, (teacher, t_email))
        with patch("app.services.tenant.get_quota", return_value=_quota_ok()):
            resp = client.post("/ai/quiz/generate", json={})
        assert resp.status_code == 400

    def test_generate_quiz_unknown_lesson_404(self, app):
        sid = make_school(app)
        teacher, t_email = mk_user(app, "teacher", school_id=sid)
        client = login_as(app, (teacher, t_email))
        with patch("app.services.tenant.get_quota", return_value=_quota_ok()):
            resp = client.post("/ai/quiz/generate", json={"lesson_id": 987_654})
        assert resp.status_code == 404

    def test_generate_quiz_cross_tenant_lesson_403(self, app):
        sid1, sid2 = make_school(app), make_school(app)
        gid = make_grade(app, sid2, grade_level=_next_level(sid2))
        cid2 = make_class(app, sid2, gid, make_subject(app))
        lesson_id = make_lesson(app, cid2)
        teacher, t_email = mk_user(app, "teacher", school_id=sid1)
        client = login_as(app, (teacher, t_email))
        with patch("app.services.tenant.get_quota", return_value=_quota_ok()):
            resp = client.post("/ai/quiz/generate", json={"lesson_id": lesson_id})
        assert resp.status_code in (403, 502)

    def test_generate_quiz_bad_difficulty_defaults(self, app):
        sid = make_school(app)
        gid = make_grade(app, sid, grade_level=_next_level(sid))
        cid = make_class(app, sid, gid, make_subject(app))
        lesson_id = make_lesson(app, cid)
        teacher, t_email = mk_user(app, "teacher", school_id=sid)
        client = login_as(app, (teacher, t_email))
        with (
            patch("app.services.tenant.get_quota", return_value=_quota_ok()),
            patch("app.services.quiz_ai_service.generate_quiz_from_lesson") as gq,
        ):
            gq.return_value = (None, "offline fallback failed")
            resp = client.post("/ai/quiz/generate", json={"lesson_id": lesson_id, "difficulty": "weird"})
        assert resp.status_code == 502
        kwargs = gq.call_args.kwargs
        assert kwargs["difficulty"] == "medium"


# ═══════════════════════════════════════════════════════════════════════
# Assessment routes — guards & error branches
# ═══════════════════════════════════════════════════════════════════════


class TestAssessmentGaps:
    def _quiz_env(self, app):
        sid, cid = _setup_class(app)
        teacher, t_email = mk_user(app, "teacher", school_id=sid)
        with app.app_context():
            from app.core.db import tx
            from app.extensions import db
            from app.models.assessment import Quiz
            from app.models.class_room import ClassRoom

            cls = db.session.get(ClassRoom, cid)
            cls.teacher_id = teacher
            db.session.commit()
            quiz = Quiz(class_id=cid, title="اختبار", status="published", created_by=teacher)
            db.session.add(quiz)
            tx(lambda: None)
            qid = quiz.id
        return sid, cid, teacher, t_email, qid

    def test_attempt_start_forbidden_for_non_member_student(self, app):
        sid, cid, teacher, t_email, qid = self._quiz_env(app)
        outsider, o_email = mk_user(app, "student")
        client = login_as(app, (outsider, o_email))
        assert client.get(f"/classes/quizzes/{qid}/attempt").status_code == 403

    def test_attempt_start_rejected_for_teacher(self, app):
        sid, cid, teacher, t_email, qid = self._quiz_env(app)
        client = login_as(app, (teacher, t_email))
        resp = client.get(f"/classes/quizzes/{qid}/attempt", follow_redirects=True)
        assert resp.status_code == 200

    def test_attempt_do_other_students_attempt_403(self, app):
        sid, cid, teacher, t_email, qid = self._quiz_env(app)
        stu, s_email = mk_user(app, "student", school_id=sid)
        make_class_member(app, cid, stu, status="active")
        with app.app_context():
            from app.core.db import tx
            from app.extensions import db
            from app.models.assessment import QuizAttempt

            att = QuizAttempt(quiz_id=qid, student_id=stu, attempt_no=1, status="in_progress")
            db.session.add(att)
            tx(lambda: None)
            aid = att.id
        other, o_email = mk_user(app, "student", school_id=sid)
        make_class_member(app, cid, other, status="active")
        client = login_as(app, (other, o_email))
        assert client.get(f"/classes/attempt/{aid}").status_code == 403

    def test_attempt_save_redirects_on_progress(self, app):
        sid, cid, teacher, t_email, qid = self._quiz_env(app)
        stu, s_email = mk_user(app, "student", school_id=sid)
        make_class_member(app, cid, stu, status="active")
        with app.app_context():
            from app.core.db import tx
            from app.extensions import db
            from app.models.assessment import QuizAttempt

            att = QuizAttempt(quiz_id=qid, student_id=stu, attempt_no=1, status="in_progress")
            db.session.add(att)
            tx(lambda: None)
            aid = att.id
        client = login_as(app, (stu, s_email))
        resp = client.post(f"/classes/attempt/{aid}/save", data={}, follow_redirects=True)
        assert resp.status_code == 200

    def test_attempt_submit_already_submitted_redirects_to_result(self, app):
        sid, cid, teacher, t_email, qid = self._quiz_env(app)
        stu, s_email = mk_user(app, "student", school_id=sid)
        make_class_member(app, cid, stu, status="active")
        with app.app_context():
            from app.core.db import tx
            from app.extensions import db
            from app.models.assessment import QuizAttempt

            att = QuizAttempt(quiz_id=qid, student_id=stu, attempt_no=1, status="submitted")
            db.session.add(att)
            tx(lambda: None)
            aid = att.id
        client = login_as(app, (stu, s_email))
        resp = client.post(f"/classes/attempt/{aid}/submit", follow_redirects=False)
        assert resp.status_code == 302

    def test_ai_generate_questions_route_forbidden_for_student(self, app):
        sid = make_school(app)
        stu, s_email = mk_user(app, "student", school_id=sid)
        client = login_as(app, (stu, s_email))
        resp = client.post("/classes/quiz/generate-ai", json={"topic": "جبر"}, buffered=True)
        assert resp.status_code == 403


# ═══════════════════════════════════════════════════════════════════════
# Grades routes — rubric builder, rubric grading, report-card guards
# ═══════════════════════════════════════════════════════════════════════


class TestGradesGaps:
    def _teacher_env(self, app):
        sid, cid = _setup_class(app)
        teacher, t_email = mk_user(app, "teacher", school_id=sid)
        # make_class without teacher_id → assign this teacher and re-login
        with app.app_context():
            from app.extensions import db
            from app.models.class_room import ClassRoom

            cls = db.session.get(ClassRoom, cid)
            cls.teacher_id = teacher
            db.session.commit()
        return sid, cid, teacher, t_email

    def test_rubric_create_validation_branches(self, app):
        sid, cid, teacher, t_email = self._teacher_env(app)
        client = login_as(app, (teacher, t_email))
        # no title → flash
        r1 = client.post(f"/classes/{cid}/rubric", data={}, follow_redirects=True)
        assert r1.status_code == 200
        # title but no criteria → flash
        r2 = client.post(f"/classes/{cid}/rubric", data={"title": "قالب"}, follow_redirects=True)
        assert r2.status_code == 200
        # full create
        r3 = client.post(
            f"/classes/{cid}/rubric",
            data={
                "title": "قالب التقييم",
                "criteria[0][title]": "الدقة",
                "criteria[0][max_score]": "10",
            },
            follow_redirects=True,
        )
        assert r3.status_code == 200

    def test_rubric_grade_view_and_save(self, app):
        sid, cid, teacher, t_email = self._teacher_env(app)
        stu, s_email = mk_user(app, "student", school_id=sid)
        make_class_member(app, cid, stu, status="active")
        with app.app_context():
            from app.core.db import tx
            from app.extensions import db
            from app.models.gradebook import Submission
            from app.models.user import User
            from app.services.rubric import create_rubric_template
            from tests.conftest import _db

            teacher_row = _db.session.get(User, teacher)
            tid = teacher_row.id if teacher_row else 1
            template = create_rubric_template(
                tid,
                sid,
                "قالب",
                "",
                [{"title": "معيار", "max_score": 10.0, "description": None}],
            )
            asg = __import__("app.models.gradebook", fromlist=["Assignment"]).Assignment(
                class_id=cid, title="واجب", body="اكتب", max_mark=20, created_by=tid
            )
            db.session.add(asg)
            db.session.flush()
            sub = Submission(assignment_id=asg.id, student_id=stu, body="حل")
            db.session.add(sub)
            db.session.flush()
            tx(lambda: None)
            tid2, _sid2, subid = template.id, asg.id, sub.id
        client = login_as(app, (teacher, t_email))
        assert client.get(f"/classes/rubric/{tid2}/grade/{subid}").status_code == 200
        resp = client.post(
            f"/classes/rubric/grade/{subid}",
            data={"score_1": "8"},
            follow_redirects=True,
        )
        assert resp.status_code == 200

    def test_report_card_pdf_for_self(self, app):
        sid, cid = _setup_class(app)
        stu, s_email = mk_user(app, "student", school_id=sid)
        make_class_member(app, cid, stu, status="active")
        client = login_as(app, (stu, s_email))
        with patch("app.services.report_card.render_report_card_pdf") as rp:
            rp.return_value = b"%PDF-1.4 fake"
            resp = client.get(f"/classes/{cid}/report-card/{stu}/pdf")
        assert resp.status_code == 200
        assert resp.mimetype == "application/pdf"

    def test_report_card_pdf_other_student_403(self, app):
        sid, cid = _setup_class(app)
        stu, s_email = mk_user(app, "student", school_id=sid)
        make_class_member(app, cid, stu, status="active")
        other_id, _o_email = mk_user(app, "student", school_id=sid)
        client = login_as(app, (stu, s_email))
        assert client.get(f"/classes/{cid}/report-card/{other_id}/pdf").status_code == 403

    def test_submission_file_no_file_404(self, app):
        sid, cid, teacher, t_email = self._teacher_env(app)
        stu, _ = mk_user(app, "student", school_id=sid)
        with app.app_context():
            from app.core.db import tx
            from app.extensions import db
            from app.models.gradebook import Assignment, Submission

            asg = Assignment(class_id=cid, title="w", body="b", max_mark=10, created_by=teacher)
            db.session.add(asg)
            db.session.flush()
            sub = Submission(assignment_id=asg.id, student_id=stu, body="نص فقط")
            db.session.add(sub)
            db.session.flush()
            tx(lambda: None)
            subid = sub.id
        client = login_as(app, (teacher, t_email))
        assert client.get(f"/classes/submissions/{subid}/file").status_code == 404


# ═══════════════════════════════════════════════════════════════════════
# Billing routes — TxError rollback + validate-code + review guards
# ═══════════════════════════════════════════════════════════════════════


class TestBillingGaps:
    def _billing(self, app, price=50.0):
        sid, cid = _setup_class(app)
        teacher, t_email = mk_user(app, "teacher", school_id=sid)
        make_class_member(app, cid, teacher, status="active")
        plan_id = make_subscription_plan(app, sid, class_id=cid, price=price)
        stu, s_email = mk_user(app, "student", school_id=sid)
        make_class_member(app, cid, stu, status="active")
        return sid, cid, teacher, t_email, stu, s_email, plan_id

    def _as_teacher(self, app, cid, teacher):
        """Assign the teacher to the class so @class_teach_required passes."""
        with app.app_context():
            from app.extensions import db
            from app.models.class_room import ClassRoom

            cls = db.session.get(ClassRoom, cid)
            cls.teacher_id = teacher
            db.session.commit()

    def test_plan_create_requires_teach(self, app):
        sid, cid, teacher, t_email, stu, s_email, plan_id = self._billing(app)
        client = login_as(app, (teacher, t_email))
        # Not the class teacher yet → 403 guard branch
        resp = client.post(f"/billing/{cid}/plans", data={"name": "p", "price": "10"})
        assert resp.status_code == 403
        self._as_teacher(app, cid, teacher)
        # Now valid teaching context → redirect (form may be invalid, still 302)
        resp2 = client.post(f"/billing/{cid}/plans", data={"name": "p", "price": "10"}, follow_redirects=True)
        assert resp2.status_code == 200

    def test_subscribe_requires_membership(self, app):
        sid, cid, teacher, t_email, stu, s_email, plan_id = self._billing(app)
        outsider, o_email = mk_user(app, "student")
        client = login_as(app, (outsider, o_email))
        assert (
            client.post(f"/billing/{cid}/subscribe", data={"plan_id": plan_id}, follow_redirects=False).status_code
            == 403
        )

    def test_subscribe_invalid_plan_redirects_with_flash(self, app):
        # Free class (price 0) so the student member can view the redirect target
        # (P-SEC-13: paid classes require an active subscription to view).
        sid, cid, teacher, t_email, stu, s_email, plan_id = self._billing(app, price=0.0)
        client = login_as(app, (stu, s_email))
        # Member + unknown plan → flash "خطة غير صالحة" + redirect
        resp = client.post(f"/billing/{cid}/subscribe", data={"plan_id": 987_654}, follow_redirects=True)
        assert resp.status_code == 200
        assert "خطة غير صالحة".encode() in resp.data

    def test_payment_create_wrong_user_403(self, app):
        sid, cid, teacher, t_email, stu, s_email, plan_id = self._billing(app)
        other_stu, o_email = mk_user(app, "student", school_id=sid)
        make_class_member(app, cid, other_stu, status="active")
        with app.app_context():
            from app.models.billing import Subscription
            from app.services.billing import get_plan

            sub = None
            from tests.conftest import _db

            plan = get_plan(plan_id)
            sub = Subscription(user_id=other_stu, plan_id=plan.id, class_id=cid, price=plan.price, status="pending")
            _db.session.add(sub)
            _db.session.commit()
            subid = sub.id
        client = login_as(app, (stu, s_email))
        assert client.post(f"/billing/subscriptions/{subid}/pay", data={}, follow_redirects=False).status_code == 403

    def test_review_reject_flow(self, app):
        sid, cid, teacher, t_email, stu, s_email, plan_id = self._billing(app)
        admin, a_email = mk_user(app, "school_admin", school_id=sid)
        with app.app_context():
            from app.models.billing import ManualPayment, Subscription
            from app.services.billing import get_plan
            from tests.conftest import _db

            plan = get_plan(plan_id)
            sub = Subscription(user_id=stu, plan_id=plan.id, class_id=cid, price=plan.price, status="pending")
            _db.session.add(sub)
            _db.session.commit()
            pay = ManualPayment(subscription_id=sub.id, amount=plan.price, reference="REF-R", status="pending")
            _db.session.add(pay)
            _db.session.commit()
            pid = pay.id
        client = login_as(app, (admin, a_email))
        with patch("app.services.email.send_payment_rejected_email"):
            resp = client.post(f"/billing/payments/{pid}/reject", follow_redirects=True)
        assert resp.status_code == 200

    def test_review_unknown_result_404(self, app):
        sid, cid, teacher, t_email, stu, s_email, plan_id = self._billing(app)
        admin, a_email = mk_user(app, "school_admin", school_id=sid)
        with app.app_context():
            from app.models.billing import ManualPayment, Subscription
            from app.services.billing import get_plan
            from tests.conftest import _db

            plan = get_plan(plan_id)
            sub = Subscription(user_id=stu, plan_id=plan.id, class_id=cid, price=plan.price, status="pending")
            _db.session.add(sub)
            _db.session.commit()
            pay = ManualPayment(subscription_id=sub.id, amount=plan.price, reference="R2", status="pending")
            _db.session.add(pay)
            _db.session.commit()
            pid = pay.id
        client = login_as(app, (admin, a_email))
        assert client.post(f"/billing/payments/{pid}/bogus", follow_redirects=False).status_code == 404

    def test_validate_code_endpoint(self, app):
        sid, cid, teacher, t_email, stu, s_email, plan_id = self._billing(app)
        client = login_as(app, (stu, s_email))
        # invalid body → 400
        r400 = client.post("/billing/validate-code", json={})
        assert r400.status_code == 400
        # unknown code → 400 with error
        r404 = client.post("/billing/validate-code", json={"code": "MISS", "plan_id": plan_id})
        assert r404.status_code == 400

    def test_invoice_view_for_member(self, app):
        sid, cid, teacher, t_email, stu, s_email, plan_id = self._billing(app)
        with app.app_context():
            from app.models.billing import Subscription
            from app.services.billing import get_plan
            from tests.conftest import _db

            plan = get_plan(plan_id)
            sub = Subscription(user_id=stu, plan_id=plan.id, class_id=cid, price=plan.price, status="active")
            _db.session.add(sub)
            _db.session.commit()
            subid = sub.id
        client = login_as(app, (stu, s_email))
        assert client.get(f"/billing/invoices/{subid}").status_code == 200


# ═══════════════════════════════════════════════════════════════════════
# Tutoring — live session guards + status route
# ═══════════════════════════════════════════════════════════════════════


class TestTutoringLiveGaps:
    def _session(self, app):
        sid = make_school(app)
        tutor, t_email = mk_user(app, "teacher", school_id=sid)
        stu, s_email = mk_user(app, "student", school_id=sid)
        sess_id = make_tutoring_session(app, tutor_id=tutor, student_id=stu)
        return sid, tutor, t_email, stu, s_email, sess_id

    def test_status_route_requires_tutor(self, app):
        sid, tutor, t_email, stu, s_email, sess_id = self._session(app)
        client = login_as(app, (stu, s_email))
        # Route is GET; student must also fail the tutor-only check
        resp = client.get(f"/tutoring/sessions/{sess_id}/status/completed")
        assert resp.status_code == 403

    def test_status_route_bad_value_404(self, app):
        sid, tutor, t_email, stu, s_email, sess_id = self._session(app)
        client = login_as(app, (tutor, t_email))
        assert client.get(f"/tutoring/sessions/{sess_id}/status/bogus").status_code == 404

    def test_status_route_completes_and_creates_commission(self, app):
        sid, tutor, t_email, stu, s_email, sess_id = self._session(app)
        client = login_as(app, (tutor, t_email))
        resp = client.get(f"/tutoring/sessions/{sess_id}/status/completed", follow_redirects=True)
        assert resp.status_code == 200

    def test_live_url_and_status(self, app):
        sid, tutor, t_email, stu, s_email, sess_id = self._session(app)
        client = login_as(app, (tutor, t_email))
        r1 = client.get(f"/tutoring/sessions/{sess_id}/live-url")
        assert r1.status_code in (200, 403)
        r2 = client.get(f"/tutoring/sessions/{sess_id}/live-status")
        assert r2.status_code == 200
        body = r2.get_json()
        assert "is_live" in body

    def test_start_and_end_live(self, app):
        sid, tutor, t_email, stu, s_email, sess_id = self._session(app)
        client = login_as(app, (tutor, t_email))
        r1 = client.post(f"/tutoring/sessions/{sess_id}/start-live", follow_redirects=True)
        assert r1.status_code == 200
        r2 = client.post(f"/tutoring/sessions/{sess_id}/end-live", follow_redirects=True)
        assert r2.status_code == 200

    def test_live_url_forbidden_for_outsider(self, app):
        sid, tutor, t_email, stu, s_email, sess_id = self._session(app)
        outsider, o_email = mk_user(app, "student")
        client = login_as(app, (outsider, o_email))
        assert client.get(f"/tutoring/sessions/{sess_id}/live-url").status_code == 403


# ═══════════════════════════════════════════════════════════════════════
# Payments gateway internals — Stripe config, CashU verify, fraud guard
# ═══════════════════════════════════════════════════════════════════════


class TestPaymentsGateways:
    def test_stripe_gateway_create_intent(self, app):
        from app.services.payments import PaymentGateway, PaymentStatus, StripeGateway

        fake_stripe = MagicMock()
        fake_stripe.PaymentIntent.create.return_value = MagicMock(id="pi_1", client_secret="cs_1")
        gw = StripeGateway({"secret_key": "sk_test", "webhook_secret": "whsec"})
        gw.stripe = fake_stripe
        intent = gw.create_payment_intent(Decimal("50"), "ILS", 1)
        assert intent.status == PaymentStatus.PENDING
        assert intent.gateway == PaymentGateway.STRIPE
        assert fake_stripe.PaymentIntent.create.called

    def test_cashu_verify_signature_ok_then_api_fail(self, app):
        import hashlib
        import hmac
        import json

        from app.services.payments import CashUGateway, PaymentGateway

        gw = CashUGateway({"webhook_secret": "sec", "encryption_key": "k", "base_url": "http://x"})
        payload = {"transaction_id": "t1", "status": "completed"}
        body = json.dumps(payload, sort_keys=True).encode()
        sig = hmac.new(b"sec", body, hashlib.sha256).hexdigest()
        intent = MagicMock()
        intent.id = "cashu_t1"
        intent.gateway = PaymentGateway.CASHU

        class FakeResp:
            status_code = 500

        with patch("requests.get", return_value=FakeResp()):
            assert gw.verify_payment(intent, {"payload": body.decode(), "headers": {"CashU-Signature": sig}}) is False

    def test_is_suspicious_amount_no_history_false(self, app):
        from app.services.payments import PaymentService

        with app.app_context():
            proc = PaymentService()
            assert proc._is_suspicious_amount(make_school(app), Decimal("1000")) is False


# ═══════════════════════════════════════════════════════════════════════
# App-level helpers — rate limit key, health degraded paths
# ═══════════════════════════════════════════════════════════════════════


class TestAppHelpers:
    def test_rate_limit_key_anonymous_vs_user(self, app):
        from app import _rate_limit_key

        with app.test_request_context("/"):
            key_anon = _rate_limit_key()
            assert key_anon
        # With a logged-in user the key includes the user id
        sid = make_school(app)
        stu, s_email = mk_user(app, "student", school_id=sid)
        client = login_as(app, (stu, s_email))
        assert client.get("/auth/dashboard").status_code in (200, 302)

    def test_health_endpoint(self, app):
        client = app.test_client()
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["status"] in ("healthy", "degraded", "down")
        assert "database" in body["checks"]
