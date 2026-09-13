"""Extended coverage round C — assessment/grades/content/tutoring routes + AI service internals.

Targets CI-verified missed lines (run 34769116916, backend 92.2% lines / 78.8% branches):
- app/modules/assessment/routes.py: quiz CRUD, attempt lifecycle, proctoring force-submit,
  question bank, answer grading
- app/modules/grades/routes.py: categories/items, attendance, report-card, appeals
- app/modules/content/routes.py: lesson publish, unit create, offline marks, attachment upload
- app/modules/tutoring/routes.py: profile create/edit, invite, earnings, payout
- app/modules/schools/routes.py: class code regenerate, assign teacher, school classes
- app/modules/admin/routes.py: settings save, registrations approve/reject, user toggle,
  bulk actions, subscription cancel/detail, school-admin dashboard
- app/services/ai.py: _verify_permission, get_usage_stats, start_session, log_message,
  _mock_ai_answer branches
- app/__init__.py: currency format filter
"""

from __future__ import annotations

import json

from tests.conftest import (
    make_class,
    make_class_member,
    make_grade,
    make_grade_category,
    make_grade_item,
    make_lesson,
    make_school,
    make_subject,
    make_subscription,
    make_subscription_plan,
    make_tutor_profile,
    make_user,
)

PASSWORD = "TestPass123!"

_LEVELS: dict[int, int] = {}


def mk_user(app, role: str, school_id=None):
    from tests.conftest import _uid

    email = f"xc-{_uid()}@test.com"
    uid = make_user(app, role=role, school_id=school_id, email=email)
    return uid, email


def persona(app, role: str, school_id=None):
    uid, email = mk_user(app, role, school_id)
    client = app.test_client()
    client.post("/auth/login", data={"email": email, "password": PASSWORD})
    return uid, client


def login_as(app, email: str):
    client = app.test_client()
    client.post("/auth/login", data={"email": email, "password": PASSWORD})
    return client


def _next_level(sid: int) -> int:
    _LEVELS[sid] = _LEVELS.get(sid, 0) + 1
    return _LEVELS[sid]


def _setup_class(app):
    sid = make_school(app)
    gid = make_grade(app, sid, grade_level=_next_level(sid))
    subj = make_subject(app)
    cid = make_class(app, sid, gid, subj)
    return sid, cid, gid


def _set_class_teacher(app, cid: int, tid: int):
    from app.extensions import db
    from app.models.class_room import ClassRoom

    with app.app_context():
        db.session.get(ClassRoom, cid).teacher_id = tid
        db.session.commit()


# ═════════════════════════════ assessment ═════════════════════════════


def _quiz(app, cid: int, tid: int, title="اختبار"):
    from app.extensions import db
    from app.models.assessment import Quiz

    with app.app_context():
        q = Quiz(class_id=cid, title=title, duration_min=30, created_by=tid, status="published")
        db.session.add(q)
        db.session.commit()
        return q.id


def _question(app, quiz_id: int, qtype="mcq", prompt=None):
    from app.extensions import db
    from app.models.assessment import Question

    with app.app_context():
        if qtype == "mcq":
            options = {"items": [{"label": "أ", "text": "1"}, {"label": "ب", "text": "2"}]}
            correct = {"index": 0}
        elif qtype == "true_false":
            options = None
            correct = {"value": True}
        else:
            options = None
            correct = None
        q = Question(
            quiz_id=quiz_id,
            type=qtype,
            prompt=prompt or f"سؤال {qtype}",
            options=options,
            correct_answer=correct,
            mark=5.0,
        )
        db.session.add(q)
        db.session.commit()
        return q.id


class TestAssessmentQuizCrud:
    def test_quiz_new_get_and_post(self, app):
        sid, cid, _ = _setup_class(app)
        tid, t_email = mk_user(app, "teacher", school_id=sid)
        _set_class_teacher(app, cid, tid)
        client = login_as(app, t_email)
        assert client.get(f"/classes/{cid}/quizzes/new").status_code == 200
        resp = client.post(
            f"/classes/{cid}/quizzes/new",
            data={
                "title": "اختبار الوحدة 1",
                "duration_min": "30",
                "attempts_allowed": "1",
                "shuffle": "y",
                "show_answers_after": "y",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302

    def test_quiz_manage_add_mcq_question(self, app):
        sid, cid, _ = _setup_class(app)
        tid, t_email = mk_user(app, "teacher", school_id=sid)
        _set_class_teacher(app, cid, tid)
        qid = _quiz(app, cid, tid)
        client = login_as(app, t_email)
        assert client.get(f"/classes/{cid}/quizzes/{qid}").status_code == 200
        resp = client.post(
            f"/classes/{cid}/quizzes/{qid}",
            data={
                "qtype": "mcq",
                "prompt": "عاصمة فلسطين؟",
                "option_a": "القدس",
                "option_b": "رام الله",
                "option_c": "غزة",
                "option_d": "نابلس",
                "correct_index": "0",
                "mark": "5",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302

    def test_question_delete_by_other_teacher_403(self, app):
        sid, cid, _ = _setup_class(app)
        tid, _ = mk_user(app, "teacher", school_id=sid)
        _set_class_teacher(app, cid, tid)
        qid = _quiz(app, cid, tid)
        q_id = _question(app, qid)
        other, o_email = mk_user(app, "teacher", school_id=sid)
        client = login_as(app, o_email)
        resp = client.post(f"/classes/questions/{q_id}/delete", follow_redirects=False)
        assert resp.status_code == 403

    def test_quiz_list_student_with_attempts(self, app):
        sid, cid, _ = _setup_class(app)
        tid, _ = mk_user(app, "teacher", school_id=sid)
        _set_class_teacher(app, cid, tid)
        qid = _quiz(app, cid, tid)
        stu_id, s_email = mk_user(app, "student", school_id=sid)
        make_class_member(app, cid, stu_id)
        from app.extensions import db
        from app.models.assessment import QuizAttempt

        with app.app_context():
            att = QuizAttempt(quiz_id=qid, student_id=stu_id, status="in_progress")
            db.session.add(att)
            db.session.commit()
        client = login_as(app, s_email)
        resp = client.get(f"/classes/{cid}/quizzes")
        assert resp.status_code == 200


class TestAssessmentAttemptLifecycle:
    def _attempt(self, app, cid: int, tid: int, stu_id: int, qtype="mcq"):
        qid = _quiz(app, cid, tid)
        q_id = _question(app, qid, qtype=qtype)
        from app.extensions import db
        from app.models.assessment import QuizAttempt

        with app.app_context():
            att = QuizAttempt(quiz_id=qid, student_id=stu_id, status="in_progress")
            db.session.add(att)
            db.session.commit()
            return att.id, q_id

    def test_attempt_start_non_student_redirects(self, app):
        sid, cid, _ = _setup_class(app)
        tid, t_email = mk_user(app, "teacher", school_id=sid)
        _set_class_teacher(app, cid, tid)
        qid = _quiz(app, cid, tid)
        client = login_as(app, t_email)
        resp = client.get(f"/classes/quizzes/{qid}/attempt", follow_redirects=False)
        assert resp.status_code == 302

    def test_attempt_do_by_owner(self, app):
        sid, cid, _ = _setup_class(app)
        tid, _ = mk_user(app, "teacher", school_id=sid)
        _set_class_teacher(app, cid, tid)
        stu_id, s_email = mk_user(app, "student", school_id=sid)
        make_class_member(app, cid, stu_id)
        att_id, _ = self._attempt(app, cid, tid, stu_id)
        client = login_as(app, s_email)
        resp = client.get(f"/classes/attempt/{att_id}")
        assert resp.status_code == 200

    def test_attempt_do_by_other_403(self, app):
        sid, cid, _ = _setup_class(app)
        tid, _ = mk_user(app, "teacher", school_id=sid)
        _set_class_teacher(app, cid, tid)
        stu_id, _ = mk_user(app, "student", school_id=sid)
        make_class_member(app, cid, stu_id)
        att_id, _ = self._attempt(app, cid, tid, stu_id)
        other, o_email = mk_user(app, "student", school_id=sid)
        client = login_as(app, o_email)
        resp = client.get(f"/classes/attempt/{att_id}", follow_redirects=False)
        assert resp.status_code == 403

    def test_attempt_save_answers(self, app):
        sid, cid, _ = _setup_class(app)
        tid, _ = mk_user(app, "teacher", school_id=sid)
        _set_class_teacher(app, cid, tid)
        stu_id, s_email = mk_user(app, "student", school_id=sid)
        make_class_member(app, cid, stu_id)
        att_id, q_id = self._attempt(app, cid, tid, stu_id, qtype="true_false")
        client = login_as(app, s_email)
        resp = client.post(f"/classes/attempt/{att_id}/save", data={f"q_{q_id}": "true"}, follow_redirects=False)
        assert resp.status_code == 302

    def test_attempt_submit_grades_mcq(self, app):
        sid, cid, _ = _setup_class(app)
        tid, _ = mk_user(app, "teacher", school_id=sid)
        _set_class_teacher(app, cid, tid)
        stu_id, s_email = mk_user(app, "student", school_id=sid)
        make_class_member(app, cid, stu_id)
        att_id, q_id = self._attempt(app, cid, tid, stu_id, qtype="true_false")
        client = login_as(app, s_email)
        resp = client.post(f"/classes/attempt/{att_id}/submit", data={f"q_{q_id}": "true"}, follow_redirects=False)
        assert resp.status_code == 302
        from app.extensions import db
        from app.models.assessment import QuizAttempt

        with app.app_context():
            db.session.expire_all()
            att = db.session.get(QuizAttempt, att_id)
            assert att.status == "submitted"

    def test_attempt_result_denies_non_owner(self, app):
        sid, cid, _ = _setup_class(app)
        tid, _ = mk_user(app, "teacher", school_id=sid)
        _set_class_teacher(app, cid, tid)
        stu_id, _ = mk_user(app, "student", school_id=sid)
        make_class_member(app, cid, stu_id)
        att_id, _ = self._attempt(app, cid, tid, stu_id)
        other, o_email = mk_user(app, "student", school_id=sid)
        client = login_as(app, o_email)
        resp = client.get(f"/classes/attempt/{att_id}/result", follow_redirects=False)
        assert resp.status_code == 403

    def test_proctor_invalid_event_400(self, app):
        sid, cid, _ = _setup_class(app)
        tid, _ = mk_user(app, "teacher", school_id=sid)
        _set_class_teacher(app, cid, tid)
        stu_id, s_email = mk_user(app, "student", school_id=sid)
        make_class_member(app, cid, stu_id)
        att_id, _ = self._attempt(app, cid, tid, stu_id)
        client = login_as(app, s_email)
        resp = client.post(
            f"/classes/attempt/{att_id}/proctor",
            data=json.dumps({"event_type": "bogus"}),
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_proctor_tab_switch_under_limit_ok(self, app):
        sid, cid, _ = _setup_class(app)
        tid, _ = mk_user(app, "teacher", school_id=sid)
        _set_class_teacher(app, cid, tid)
        stu_id, s_email = mk_user(app, "student", school_id=sid)
        make_class_member(app, cid, stu_id)
        att_id, _ = self._attempt(app, cid, tid, stu_id)
        client = login_as(app, s_email)
        resp = client.post(
            f"/classes/attempt/{att_id}/proctor",
            data=json.dumps({"event_type": "tab_switch"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True

    def test_proctor_forbidden_for_non_owner(self, app):
        sid, cid, _ = _setup_class(app)
        tid, _ = mk_user(app, "teacher", school_id=sid)
        _set_class_teacher(app, cid, tid)
        stu_id, _ = mk_user(app, "student", school_id=sid)
        make_class_member(app, cid, stu_id)
        att_id, _ = self._attempt(app, cid, tid, stu_id)
        other, o_email = mk_user(app, "student", school_id=sid)
        client = login_as(app, o_email)
        resp = client.post(
            f"/classes/attempt/{att_id}/proctor",
            data=json.dumps({"event_type": "tab_switch"}),
            content_type="application/json",
        )
        assert resp.status_code == 403


class TestAssessmentQuestionBank:
    def test_bank_list_with_filters(self, app):
        sid = make_school(app)
        tid, t_email = mk_user(app, "teacher", school_id=sid)
        client = login_as(app, t_email)
        resp = client.get("/classes/question-bank?type=mcq&difficulty=3")
        assert resp.status_code == 200

    def test_bank_create_true_false(self, app):
        sid = make_school(app)
        tid, t_email = mk_user(app, "teacher", school_id=sid)
        client = login_as(app, t_email)
        resp = client.post(
            "/classes/question-bank/new",
            data={"question_text": "الشمس نجم", "question_type": "true_false", "correct_tf": "true", "difficulty": "2"},
            follow_redirects=False,
        )
        assert resp.status_code == 302

    def test_bank_import_page(self, app):
        sid, cid, _ = _setup_class(app)
        tid, t_email = mk_user(app, "teacher", school_id=sid)
        _set_class_teacher(app, cid, tid)
        qid = _quiz(app, cid, tid)
        client = login_as(app, t_email)
        resp = client.get(f"/classes/quiz/{qid}/bank-import")
        assert resp.status_code == 200

    def test_bank_import_empty_selection(self, app):
        sid, cid, _ = _setup_class(app)
        tid, t_email = mk_user(app, "teacher", school_id=sid)
        _set_class_teacher(app, cid, tid)
        qid = _quiz(app, cid, tid)
        client = login_as(app, t_email)
        resp = client.post(f"/classes/quiz/{qid}/bank-import", data={}, follow_redirects=False)
        assert resp.status_code == 302


class TestAssessmentQuizResults:
    def test_quiz_results_by_teacher(self, app):
        sid, cid, _ = _setup_class(app)
        tid, t_email = mk_user(app, "teacher", school_id=sid)
        _set_class_teacher(app, cid, tid)
        qid = _quiz(app, cid, tid)
        client = login_as(app, t_email)
        resp = client.get(f"/classes/quizzes/{qid}/results")
        assert resp.status_code == 200

    def test_quiz_results_denies_student(self, app):
        sid, cid, _ = _setup_class(app)
        tid, _ = mk_user(app, "teacher", school_id=sid)
        _set_class_teacher(app, cid, tid)
        qid = _quiz(app, cid, tid)
        stu_id, s_email = mk_user(app, "student", school_id=sid)
        make_class_member(app, cid, stu_id)
        client = login_as(app, s_email)
        resp = client.get(f"/classes/quizzes/{qid}/results", follow_redirects=False)
        assert resp.status_code == 403


# ═════════════════════════════ grades ═════════════════════════════


class TestGradesMore:
    def _teacher_class(self, app):
        sid, cid, _ = _setup_class(app)
        tid, t_email = mk_user(app, "teacher", school_id=sid)
        _set_class_teacher(app, cid, tid)
        stu_id, s_email = mk_user(app, "student", school_id=sid)
        make_class_member(app, cid, stu_id)
        return sid, cid, tid, t_email, stu_id, s_email

    def test_category_and_item_create(self, app):
        sid, cid, _, t_email, _, _ = self._teacher_class(app)
        client = login_as(app, t_email)
        assert client.get(f"/classes/{cid}/gradebook").status_code == 200
        resp = client.post(
            f"/classes/{cid}/categories",
            data={"name": "اختبارات", "weight": "50"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        from app.extensions import db
        from app.models.gradebook import GradeCategory

        with app.app_context():
            cat = db.session.query(GradeCategory).filter_by(class_id=cid).first()
            cat_id = cat.id
        resp2 = client.post(
            f"/classes/categories/{cat_id}/items",
            data={"title": "اختبار 1", "max_mark": "20", "kind": "quiz"},
            follow_redirects=False,
        )
        assert resp2.status_code == 302

    def test_grade_set_records_mark(self, app):
        sid, cid, _, t_email, stu_id, _ = self._teacher_class(app)
        cat_id = make_grade_category(app, cid, "واجبات", 50)
        item_id = make_grade_item(app, cid, cat_id, "واجب 1", 100)
        client = login_as(app, t_email)
        resp = client.post(
            f"/classes/items/{item_id}/grade",
            data={"student_id": str(stu_id), "mark": "85.5"},
            follow_redirects=False,
        )
        assert resp.status_code == 302

    def test_attendance_save(self, app):
        sid, cid, _, t_email, stu_id, _ = self._teacher_class(app)
        client = login_as(app, t_email)
        assert client.get(f"/classes/{cid}/attendance").status_code == 200
        resp = client.post(
            f"/classes/{cid}/attendance",
            data={f"status_{stu_id}": "present"},
            follow_redirects=False,
        )
        assert resp.status_code == 302

    def test_report_card_student_self(self, app):
        sid, cid, _, _, stu_id, s_email = self._teacher_class(app)
        client = login_as(app, s_email)
        resp = client.get(f"/classes/{cid}/report-card/{stu_id}")
        assert resp.status_code == 200

    def test_report_card_denies_other_student(self, app):
        sid, cid, _, _, stu_id, _ = self._teacher_class(app)
        other, o_email = mk_user(app, "student", school_id=sid)
        make_class_member(app, cid, other)
        client = login_as(app, o_email)
        resp = client.get(f"/classes/{cid}/report-card/{stu_id}", follow_redirects=False)
        assert resp.status_code == 403

    def test_assignment_create_and_submit(self, app):
        sid, cid, _, t_email, stu_id, s_email = self._teacher_class(app)
        client = login_as(app, t_email)
        resp = client.post(
            f"/classes/{cid}/assignments",
            data={"title": "واجب القانون", "body": "اكتب مقالاً", "max_mark": "20"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        from app.extensions import db
        from app.models.gradebook import Assignment

        with app.app_context():
            asg = db.session.query(Assignment).filter_by(class_id=cid).first()
            asg_id = asg.id
        sclient = login_as(app, s_email)
        assert sclient.get(f"/classes/{cid}/assignments/{asg_id}").status_code == 200
        resp2 = sclient.post(
            f"/classes/{cid}/assignments/{asg_id}/submit",
            data={"body": "إجابتي هنا"},
            follow_redirects=False,
        )
        assert resp2.status_code == 302

    def test_appeal_submit_empty_reason(self, app):
        sid, cid, _, _, stu_id, s_email = self._teacher_class(app)
        from app.extensions import db
        from app.models.gradebook import Assignment, Submission

        with app.app_context():
            asg = Assignment(class_id=cid, title="واجب", created_by=1)
            db.session.add(asg)
            db.session.commit()
            sub = Submission(assignment_id=asg.id, student_id=stu_id, body="حل")
            db.session.add(sub)
            db.session.commit()
            sub_id = sub.id
        client = login_as(app, s_email)
        resp = client.post(f"/classes/submissions/{sub_id}/appeal", data={"reason": ""}, follow_redirects=False)
        assert resp.status_code == 302


# ═════════════════════════════ content ═════════════════════════════


class TestContentMore:
    def _teacher_lesson(self, app):
        sid, cid, _ = _setup_class(app)
        tid, t_email = mk_user(app, "teacher", school_id=sid)
        _set_class_teacher(app, cid, tid)
        lid = make_lesson(app, cid)
        return sid, cid, lid, tid, t_email

    def test_lesson_publish_toggle(self, app):
        _, cid, lid, _, t_email = self._teacher_lesson(app)
        client = login_as(app, t_email)
        resp = client.post(f"/classes/{cid}/lessons/{lid}/publish", follow_redirects=False)
        assert resp.status_code == 302
        # toggle back (draft branch)
        resp2 = client.post(f"/classes/{cid}/lessons/{lid}/publish", follow_redirects=False)
        assert resp2.status_code == 302

    def test_unit_create(self, app):
        _, cid, _, _, t_email = self._teacher_lesson(app)
        client = login_as(app, t_email)
        resp = client.post(f"/classes/{cid}/units", data={"title": "الوحدة الأولى"}, follow_redirects=False)
        assert resp.status_code == 302

    def test_lesson_detail_as_student(self, app):
        sid, cid, lid, _, _ = self._teacher_lesson(app)
        stu_id, s_email = mk_user(app, "student", school_id=sid)
        make_class_member(app, cid, stu_id)
        client = login_as(app, s_email)
        resp = client.get(f"/classes/{cid}/lessons/{lid}")
        assert resp.status_code == 200

    def test_offline_mark_missing_data(self, app):
        sid = make_school(app)
        uid, email = mk_user(app, "student", school_id=sid)
        client = login_as(app, email)
        resp = client.post("/classes/offline/mark", data={}, follow_redirects=False)
        assert resp.status_code == 302

    def test_offline_remove_other_student_403(self, app):
        sid = make_school(app)
        uid, _ = mk_user(app, "student", school_id=sid)
        other, o_email = mk_user(app, "student", school_id=sid)
        client = login_as(app, o_email)
        resp = client.post("/classes/offline/999999/remove", follow_redirects=False)
        assert resp.status_code in (404, 403)


# ═════════════════════════════ tutoring ═════════════════════════════


class TestTutoringMore:
    def test_profile_create_by_any_user(self, app):
        sid = make_school(app)
        uid, email = mk_user(app, "teacher", school_id=sid)
        client = login_as(app, email)
        assert client.get("/tutoring/profile/new").status_code == 200
        resp = client.post(
            "/tutoring/profile/new",
            data={
                "subject": "فيزياء",
                "price_hour": "90",
                "price_session": "70",
                "mode": "both",
                "bio": "خبرة 10 سنوات",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302

    def test_profile_edit_requires_existing(self, app):
        sid = make_school(app)
        uid, email = mk_user(app, "student", school_id=sid)
        client = login_as(app, email)
        resp = client.get("/tutoring/profile/edit", follow_redirects=False)
        assert resp.status_code == 302

    def test_invite_valid_and_invalid(self, app):
        sid = make_school(app)
        tid, _ = mk_user(app, "teacher", school_id=sid)
        prof_id = make_tutor_profile(app, tid)
        from app.extensions import db
        from app.models.tutoring import TutorProfile

        with app.app_context():
            code = db.session.get(TutorProfile, prof_id).invite_code
        client = app.test_client()
        assert client.get(f"/tutoring/invite/{code}", follow_redirects=False).status_code == 302
        assert client.get("/tutoring/invite/NOPE-123", follow_redirects=True).status_code == 200

    def test_earnings_page(self, app):
        sid = make_school(app)
        tid, t_email = mk_user(app, "teacher", school_id=sid)
        make_tutor_profile(app, tid)
        client = login_as(app, t_email)
        resp = client.get("/tutoring/earnings")
        assert resp.status_code == 200

    def test_index_search(self, app):
        client = app.test_client()
        resp = client.get("/tutoring/", query_string={"q": "رياضيات"}, follow_redirects=False)
        assert resp.status_code == 302
        sid = make_school(app)
        uid, email = mk_user(app, "student", school_id=sid)
        authed = login_as(app, email)
        resp2 = authed.get("/tutoring/", query_string={"q": "رياضيات"})
        assert resp2.status_code == 200


# ═════════════════════════════ schools ═════════════════════════════


class TestSchoolsMore:
    def test_class_code_regenerate(self, app):
        sid, cid, _ = _setup_class(app)
        admin_id, a_email = mk_user(app, "school_admin", school_id=sid)
        client = login_as(app, a_email)
        resp = client.post(f"/schools/class/{cid}/code", follow_redirects=False)
        assert resp.status_code == 302

    def test_class_code_denies_other_school(self, app):
        sid, cid, _ = _setup_class(app)
        other_admin, o_email = mk_user(app, "school_admin", school_id=make_school(app))
        client = login_as(app, o_email)
        resp = client.post(f"/schools/class/{cid}/code", follow_redirects=False)
        assert resp.status_code == 403

    def test_assign_teacher_success(self, app):
        sid, cid, _ = _setup_class(app)
        admin_id, a_email = mk_user(app, "school_admin", school_id=sid)
        tid, _ = mk_user(app, "teacher", school_id=sid)
        client = login_as(app, a_email)
        resp = client.post(f"/schools/class/{cid}/teacher", data={"teacher_id": str(tid)}, follow_redirects=False)
        assert resp.status_code == 302

    def test_school_classes_page(self, app):
        sid, cid, _ = _setup_class(app)
        admin_id, a_email = mk_user(app, "school_admin", school_id=sid)
        client = login_as(app, a_email)
        assert client.get(f"/schools/{sid}/classes").status_code == 200
        assert client.get(f"/schools/{sid}/manage").status_code == 200


# ═════════════════════════════ admin ═════════════════════════════


class TestAdminMore:
    def test_settings_save(self, app):
        admin_id, a_email = mk_user(app, "super_admin")
        client = login_as(app, a_email)
        resp = client.post(
            "/admin/settings",
            data={"site_motto": "التعليم للجميع"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        from app.extensions import db
        from app.models.system import Setting

        with app.app_context():
            setting = db.session.query(Setting).filter_by(key="site_motto").first()
            assert setting is not None and setting.value == "التعليم للجميع"

    def test_registration_reject(self, app):
        admin_id, a_email = mk_user(app, "super_admin")
        from tests.conftest import make_user as _mk

        uid = _mk(app, role="student", school_id=make_school(app), approved=False)
        from app.extensions import db
        from app.models.user import User, UserApprovalStatus

        with app.app_context():
            db.session.get(User, uid).approval_status = UserApprovalStatus.pending
            db.session.commit()
        client = login_as(app, a_email)
        resp = client.post(f"/admin/registrations/{uid}/reject", follow_redirects=False)
        assert resp.status_code == 302

    def test_registration_approve_non_pending_warns(self, app):
        admin_id, a_email = mk_user(app, "super_admin")
        from tests.conftest import make_user as _mk

        uid = _mk(app, role="student", school_id=make_school(app), approved=True)
        client = login_as(app, a_email)
        resp = client.post(f"/admin/registrations/{uid}/approve", follow_redirects=True)
        assert resp.status_code == 200

    def test_user_toggle(self, app):
        admin_id, a_email = mk_user(app, "super_admin")
        tid, _ = mk_user(app, "teacher", school_id=make_school(app))
        client = login_as(app, a_email)
        resp = client.post(f"/admin/users/{tid}/toggle", follow_redirects=False)
        assert resp.status_code == 302
        # self-toggle warns (no action)
        resp2 = client.post(f"/admin/users/{admin_id}/toggle", follow_redirects=False)
        assert resp2.status_code == 302

    def test_bulk_action_invalid_payload(self, app):
        admin_id, a_email = mk_user(app, "super_admin")
        client = login_as(app, a_email)
        resp = client.post("/admin/bulk-action", data=json.dumps({}), content_type="application/json")
        assert resp.status_code == 400
        resp2 = client.post(
            "/admin/bulk-action",
            data=json.dumps({"entity": "aliens", "action": "delete", "ids": [1]}),
            content_type="application/json",
        )
        assert resp2.status_code == 400

    def test_bulk_action_deactivate_users(self, app):
        admin_id, a_email = mk_user(app, "super_admin")
        sid = make_school(app)
        t1, _ = mk_user(app, "teacher", school_id=sid)
        t2, _ = mk_user(app, "teacher", school_id=sid)
        client = login_as(app, a_email)
        resp = client.post(
            "/admin/bulk-action",
            data=json.dumps({"entity": "users", "action": "deactivate", "ids": [t1, t2]}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        from app.extensions import db
        from app.models.user import User

        with app.app_context():
            db.session.expire_all()
            assert db.session.get(User, t1).is_active is False
            assert db.session.get(User, t2).is_active is False

    def test_subscription_cancel(self, app):
        admin_id, a_email = mk_user(app, "super_admin")
        sid, cid, _ = _setup_class(app)
        stu_id, _ = mk_user(app, "student", school_id=sid)
        plan_id = make_subscription_plan(app, sid, class_id=cid, price=100.0)
        sub_id = make_subscription(app, stu_id, plan_id, cid, status="pending")
        client = login_as(app, a_email)
        resp = client.post(f"/admin/subscriptions/{sub_id}/cancel", follow_redirects=False)
        assert resp.status_code == 302
        from app.extensions import db
        from app.models.billing import Subscription

        with app.app_context():
            db.session.expire_all()
            assert db.session.get(Subscription, sub_id).status == "cancelled"

    def test_subscription_detail_renders(self, app):
        admin_id, a_email = mk_user(app, "super_admin")
        sid, cid, _ = _setup_class(app)
        stu_id, _ = mk_user(app, "student", school_id=sid)
        plan_id = make_subscription_plan(app, sid, class_id=cid, price=100.0)
        sub_id = make_subscription(app, stu_id, plan_id, cid, status="active")
        client = login_as(app, a_email)
        resp = client.get(f"/admin/subscriptions/{sub_id}")
        assert resp.status_code == 200

    def test_users_list_filters(self, app):
        admin_id, a_email = mk_user(app, "super_admin")
        client = login_as(app, a_email)
        assert client.get("/admin/users?role=teacher&search=azad").status_code == 200
        assert client.get("/admin/users?page=1").status_code == 200

    def test_schools_list_search(self, app):
        admin_id, a_email = mk_user(app, "super_admin")
        client = login_as(app, a_email)
        resp = client.get("/admin/schools?search=أزاد")
        assert resp.status_code == 200

    def test_school_detail(self, app):
        sid = make_school(app)
        admin_id, a_email = mk_user(app, "super_admin")
        client = login_as(app, a_email)
        resp = client.get(f"/admin/schools/{sid}")
        assert resp.status_code == 200

    def test_school_admin_dashboard_redirect_without_school(self, app):
        admin_id, a_email = mk_user(app, "super_admin")
        client = login_as(app, a_email)
        resp = client.get("/admin/school-admin", follow_redirects=False)
        assert resp.status_code == 302

    def test_dashboard_renders_super_admin(self, app):
        admin_id, a_email = mk_user(app, "super_admin")
        client = login_as(app, a_email)
        resp = client.get("/admin/")
        assert resp.status_code == 200

    def test_subscriptions_list_filter(self, app):
        admin_id, a_email = mk_user(app, "super_admin")
        client = login_as(app, a_email)
        assert client.get("/admin/subscriptions?status=active").status_code == 200
        assert client.get("/admin/subscriptions").status_code == 200


# ═════════════════════════════ AI service internals ═════════════════════════════


class TestAiServiceInternals:
    def test_verify_permission_anonymous(self, app):
        from app.services.ai import AiService

        svc = AiService.__new__(AiService)  # skip __init__ side effects
        from types import SimpleNamespace

        anon = SimpleNamespace(is_authenticated=False, role=None)
        assert svc._verify_permission(anon) is False

    def test_verify_permission_super_admin(self, app):
        from app.models.user import UserRole
        from app.services.ai import AiService

        svc = AiService.__new__(AiService)
        from types import SimpleNamespace

        admin = SimpleNamespace(is_authenticated=True, role=UserRole.super_admin)
        assert svc._verify_permission(admin, UserRole.teacher) is True

    def test_verify_permission_matching_role(self, app):
        from app.models.user import UserRole
        from app.services.ai import AiService

        svc = AiService.__new__(AiService)
        from types import SimpleNamespace

        teacher = SimpleNamespace(is_authenticated=True, role=UserRole.teacher)
        assert svc._verify_permission(teacher, {UserRole.teacher, UserRole.school_admin}) is True

    def test_verify_permission_denies_other_role(self, app):
        from app.models.user import UserRole
        from app.services.ai import AiService

        svc = AiService.__new__(AiService)
        from types import SimpleNamespace

        student = SimpleNamespace(is_authenticated=True, role=UserRole.student)
        assert svc._verify_permission(student, UserRole.teacher) is False

    def test_mock_ai_answer_branches(self, app):
        from app.services.ai import AiService

        svc = AiService.__new__(AiService)
        assert "سؤال" in svc._mock_ai_answer("")
        assert "رياضيات" in svc._mock_ai_answer("solve this math equation")
        assert "اختبارات" in svc._mock_ai_answer("I have a question about the exam")
        assert "درجاتك" in svc._mock_ai_answer("what is my grade")
        assert "واجبات" in svc._mock_ai_answer("homework help please")
        assert len(svc._mock_ai_answer("كيف حالك")) > 0

    def test_start_session_and_log_message(self, app):
        sid = make_school(app)
        uid, _ = mk_user(app, "student", school_id=sid)
        with app.app_context():
            from app.services.ai import AiService

            svc = AiService.__new__(AiService)
            session = svc.start_session(uid, "student_helper")
            msg = svc.log_message(session.id, "user", "مرحبا")
            assert msg.session_id == session.id
            assert msg.content == "مرحبا"

    def test_get_usage_stats_empty(self, app):
        with app.app_context():
            from app.services.ai import AiService

            svc = AiService.__new__(AiService)
            stats = svc.get_usage_stats(days=7)
        assert stats["total_requests"] == 0
        assert stats["period_days"] == 7
        assert "budget" in stats and "rate_limit" in stats

    def test_estimate_cost(self, app):
        from app.services.ai import AiConfig, AiService

        svc = AiService.__new__(AiService)
        svc.config = AiConfig()
        # gpt-4o-mini: 0.00015/1K input + 0.0006/1K output
        cost = svc._estimate_cost(1000, 2000)
        assert abs(cost - (0.00015 + 2 * 0.0006)) < 1e-9


# ═════════════════════════════ app factory helpers ═════════════════════════════


class TestAppHelpers:
    def test_currency_format_filter(self, app):
        with app.test_request_context("/"):
            fmt = app.jinja_env.filters["currencyformat"]
            assert fmt(None) == "—"
            out = fmt(100.5, "ILS")
            assert "100" in out
            weird = fmt(5, "XYZ")
            assert "5" in weird  # fallback raw form

    def test_404_error_page(self, app):
        client = app.test_client()
        resp = client.get("/definitely/not/a/route")
        assert resp.status_code == 404
