"""Round J — branch closure: grades + assessment partial branches.

Targets the branch arcs still reported missing by CI (run 43296221930,
backend 100% lines / 97.22% branches):

- app/modules/grades/routes.py: invalid assignment form, ``create_assignment``
  returning ``(None, None)``, invalid submission form, ``submit_assignment``
  returning ``(None, None)``, invalid grade form, invalid category form,
  rubric criterion skipped for blank title / missing score, rubric save with
  no ``score_*`` fields.
- app/modules/assessment/routes.py: ``create_quiz`` returning ``(None, None)``,
  quiz without ``created_by`` (notify skipped, email still sent), submit with a
  question left unanswered, true/false question bank entry, proctoring force
  submit with no answers in the payload, and proctoring events on an attempt
  that is no longer ``in_progress``.
"""

from __future__ import annotations

from unittest.mock import patch

from tests.conftest import (
    make_class,
    make_class_member,
    make_grade,
    make_school,
    make_subject,
    make_user,
)

PASSWORD = "TestPass123!"

_LEVELS: dict[int, int] = {}


def _next_level(sid: int) -> int:
    _LEVELS[sid] = _LEVELS.get(sid, 0) + 1
    return _LEVELS[sid]


def mk_user(app, role: str, school_id=None):
    from tests.conftest import _uid

    email = f"rnd-j-{_uid()}@test.com"
    uid = make_user(app, role=role, school_id=school_id, email=email)
    return uid, email


def login_as(app, email: str):
    client = app.test_client()
    client.post("/auth/login", data={"email": email, "password": PASSWORD})
    return client


def _setup_class(app):
    sid = make_school(app)
    gid = make_grade(app, sid, grade_level=_next_level(sid))
    subj = make_subject(app)
    cid = make_class(app, sid, gid, subj)
    return sid, cid


def _set_class_teacher(app, cid: int, tid: int):
    from app.extensions import db
    from app.models.class_room import ClassRoom

    with app.app_context():
        db.session.get(ClassRoom, cid).teacher_id = tid
        db.session.commit()


def _teacher_class(app):
    sid, cid = _setup_class(app)
    tid, t_email = mk_user(app, "teacher", school_id=sid)
    _set_class_teacher(app, cid, tid)
    return sid, cid, tid, t_email


def _assignment(app, cid: int, tid: int, title: str = "واجب") -> int:
    from app.extensions import db
    from app.models.gradebook import Assignment

    with app.app_context():
        asg = Assignment(class_id=cid, title=title, created_by=tid)
        db.session.add(asg)
        db.session.commit()
        return asg.id


def _submission(app, asg_id: int, stu_id: int, body: str = "حلّي") -> int:
    from app.extensions import db
    from app.models.gradebook import Submission

    with app.app_context():
        sub = Submission(assignment_id=asg_id, student_id=stu_id, body=body)
        db.session.add(sub)
        db.session.commit()
        return sub.id


def _assignment_count(app, cid: int) -> int:
    from app.extensions import db
    from app.models.gradebook import Assignment

    with app.app_context():
        return db.session.query(Assignment).filter_by(class_id=cid).count()


# ═════════════════════════════ grades ═════════════════════════════


class TestGradesBranchClosure:
    def test_assignment_create_rejects_invalid_form(self, app):
        """الشكل غير الصالح (بلا عنوان) يُعيد التوجيه دون إنشاء واجب."""
        _, cid, _, t_email = _teacher_class(app)
        client = login_as(app, t_email)
        before = _assignment_count(app, cid)
        resp = client.post(f"/classes/{cid}/assignments", data={"body": "بلا عنوان"}, follow_redirects=False)
        assert resp.status_code == 302
        assert _assignment_count(app, cid) == before

    def test_assignment_create_without_object_or_error(self, app):
        """خدمة الإسناد تُعيد (None, None): لا flash ولا audit، توجيه فقط."""
        _, cid, _, t_email = _teacher_class(app)
        client = login_as(app, t_email)
        with (
            patch("app.modules.grades.routes.create_assignment", return_value=(None, None)),
            patch("app.modules.grades.routes.audit") as audited,
        ):
            resp = client.post(
                f"/classes/{cid}/assignments",
                data={"title": "واجب", "body": "نصّ", "max_mark": "10"},
                follow_redirects=False,
            )
        assert resp.status_code == 302
        audited.assert_not_called()
        assert _assignment_count(app, cid) == 0

    def test_assignment_submit_rejects_invalid_form(self, app):
        """تسليم فارغ (لا نص ولا ملف) لا يمرّ من التحقق.

        كل حقول SubmissionForm اختيارية، فيبقى التحقق صحيحاً ما دام CSRF معطّلاً
        في الاختبارات (ومتى فُعّل سبق الطلب معالج CSRF العام قبل جسم المسار).
        لذلك نُحاكي استمارة غير صالحة عند حدودها ونتأكد أن الخدمة لا تُستدعى.
        """
        sid, cid, tid, _ = _teacher_class(app)
        asg_id = _assignment(app, cid, tid)
        stu_id, s_email = mk_user(app, "student", school_id=sid)
        make_class_member(app, cid, stu_id)
        client = login_as(app, s_email)

        class _InvalidForm:
            def validate_on_submit(self):
                return False

        with (
            patch("app.modules.grades.routes.SubmissionForm", return_value=_InvalidForm()),
            patch("app.modules.grades.routes.submit_assignment") as submitted,
        ):
            resp = client.post(
                f"/classes/{cid}/assignments/{asg_id}/submit",
                data={"body": "نصّ"},
                follow_redirects=False,
            )
        assert resp.status_code == 302
        submitted.assert_not_called()

    def test_assignment_submit_without_object_or_error(self, app):
        """خدمة التسليم تُعيد (None, None): لا إشعار ولا audit."""
        sid, cid, tid, _ = _teacher_class(app)
        asg_id = _assignment(app, cid, tid)
        stu_id, s_email = mk_user(app, "student", school_id=sid)
        make_class_member(app, cid, stu_id)
        client = login_as(app, s_email)
        with (
            patch("app.modules.grades.routes.submit_assignment", return_value=(None, None)),
            patch("app.modules.grades.routes.notify") as notified,
            patch("app.modules.grades.routes.audit") as audited,
        ):
            resp = client.post(
                f"/classes/{cid}/assignments/{asg_id}/submit",
                data={"body": "إجابتي"},
                follow_redirects=False,
            )
        assert resp.status_code == 302
        notified.assert_not_called()
        audited.assert_not_called()

    def test_submission_grade_rejects_invalid_form(self, app):
        """الرصد بلا علامة لا يُنفَّذ — توجيه فقط دون استدعاء الخدمة."""
        sid, cid, tid, t_email = _teacher_class(app)
        asg_id = _assignment(app, cid, tid)
        stu_id, _ = mk_user(app, "student", school_id=sid)
        make_class_member(app, cid, stu_id)
        sub_id = _submission(app, asg_id, stu_id)
        client = login_as(app, t_email)
        with patch("app.modules.grades.routes.grade_submission") as graded:
            resp = client.post(f"/classes/submissions/{sub_id}/grade", data={}, follow_redirects=False)
        assert resp.status_code == 302
        graded.assert_not_called()

    def test_category_create_rejects_invalid_form(self, app):
        """قسم بلا اسم لا يُنشأ."""
        _, cid, _, t_email = _teacher_class(app)
        client = login_as(app, t_email)
        with patch("app.modules.grades.routes.create_category") as created:
            resp = client.post(f"/classes/{cid}/categories", data={}, follow_redirects=False)
        assert resp.status_code == 302
        created.assert_not_called()

    def test_rubric_criterion_skipped_when_title_blank(self, app):
        """معيار بعنوان فارغ يُتجاهل، فيبقى القالب بلا معايير ويُرفض."""
        _, cid, _, t_email = _teacher_class(app)
        client = login_as(app, t_email)
        with patch("app.services.rubric.create_rubric_template") as created:
            resp = client.post(
                f"/classes/{cid}/rubric",
                data={
                    "title": "قالب تقييم",
                    "criteria[0][title]": "   ",
                    "criteria[0][max_score]": "5",
                },
                follow_redirects=False,
            )
        assert resp.status_code == 302
        created.assert_not_called()

    def test_rubric_grade_save_without_scores(self, app):
        """حفظ تقييم روبريك بلا أي حقل score_* لا يكتب شيئاً."""
        sid, cid, tid, t_email = _teacher_class(app)
        asg_id = _assignment(app, cid, tid)
        stu_id, _ = mk_user(app, "student", school_id=sid)
        make_class_member(app, cid, stu_id)
        sub_id = _submission(app, asg_id, stu_id)
        client = login_as(app, t_email)
        with patch("app.services.rubric.grade_with_rubric") as graded:
            resp = client.post(
                f"/classes/rubric/grade/{sub_id}",
                data={"comment_1": "ملاحظة بلا علامة"},
                follow_redirects=False,
            )
        assert resp.status_code == 302
        graded.assert_not_called()


# ═════════════════════════════ assessment ═════════════════════════════


def _quiz(app, cid: int, tid: int | None, *, fullscreen_required=False, max_tab_switches=3) -> int:
    from app.extensions import db
    from app.models.assessment import Quiz

    with app.app_context():
        q = Quiz(
            class_id=cid,
            title="اختبار",
            duration_min=30,
            created_by=tid,
            status="published",
            fullscreen_required=fullscreen_required,
            max_tab_switches=max_tab_switches,
        )
        db.session.add(q)
        db.session.commit()
        return q.id


def _question(app, quiz_id: int, *, qtype="true_false") -> int:
    from app.extensions import db
    from app.models.assessment import Question

    with app.app_context():
        q = Question(
            quiz_id=quiz_id,
            type=qtype,
            prompt="سؤال",
            options=None,
            correct_answer={"value": True} if qtype == "true_false" else None,
            mark=5.0,
        )
        db.session.add(q)
        db.session.commit()
        return q.id


def _attempt(app, quiz_id: int, stu_id: int, status: str = "in_progress") -> int:
    from app.extensions import db
    from app.models.assessment import QuizAttempt

    with app.app_context():
        att = QuizAttempt(quiz_id=quiz_id, student_id=stu_id, status=status)
        db.session.add(att)
        db.session.commit()
        return att.id


class TestAssessmentBranchClosure:
    def test_quiz_new_without_object_or_error(self, app):
        """خدمة الاختبارات تُعيد (None, None): تُعرض الاستمارة بلا إنشاء."""
        _, cid, _, t_email = _teacher_class(app)
        client = login_as(app, t_email)
        with (
            patch("app.modules.assessment.routes.create_quiz", return_value=(None, None)),
            patch("app.modules.assessment.routes.audit") as audited,
        ):
            resp = client.post(
                f"/classes/{cid}/quizzes/new",
                data={"title": "اختبار", "duration_min": "30", "attempts_allowed": "1"},
                follow_redirects=False,
            )
        assert resp.status_code == 200
        audited.assert_not_called()

    def test_submit_skips_notify_when_quiz_has_no_author(self, app):
        """اختبار بلا منشئ: لا إشعار للمعلّم، لكن بريد النتيجة يُرسل للطالب."""
        sid, cid = _setup_class(app)
        qid = _quiz(app, cid, None)
        _question(app, qid)
        stu_id, s_email = mk_user(app, "student", school_id=sid)
        make_class_member(app, cid, stu_id)
        att_id = _attempt(app, qid, stu_id)
        client = login_as(app, s_email)
        with (
            patch("app.modules.assessment.routes.notify") as notified,
            patch("app.services.email.send_quiz_result_email") as emailed,
        ):
            resp = client.post(f"/classes/attempt/{att_id}/submit", data={}, follow_redirects=False)
        assert resp.status_code == 302
        notified.assert_not_called()
        emailed.assert_called_once()

    def test_submit_with_unanswered_question(self, app):
        """سؤال بلا إجابة في الطلب: الحلقة تتخطّاه بدل حفظ قيمة فارغة."""
        sid, cid = _setup_class(app)
        qid = _quiz(app, cid, None)
        answered = _question(app, qid)
        unanswered = _question(app, qid)
        stu_id, s_email = mk_user(app, "student", school_id=sid)
        make_class_member(app, cid, stu_id)
        att_id = _attempt(app, qid, stu_id)
        client = login_as(app, s_email)
        with patch("app.services.email.send_quiz_result_email"):
            resp = client.post(
                f"/classes/attempt/{att_id}/submit",
                data={f"q_{answered}": "true"},
                follow_redirects=False,
            )
        assert resp.status_code == 302
        from app.extensions import db
        from app.models.assessment import Answer

        with app.app_context():
            saved = {a.question_id: a for a in db.session.query(Answer).filter_by(attempt_id=att_id).all()}
        # السؤال المُجاب صُحّح، وغير المُجاب بقي فارغاً بلا تصحيح (لا حفظ لقيمة غائبة)
        assert saved[answered].answer == {"value": True}
        assert saved[answered].is_correct is True
        assert saved[unanswered].answer is None
        assert saved[unanswered].is_correct is None

    def test_question_bank_true_false_entry(self, app):
        """إدخال سؤال صح/خطأ في بنك الأسئلة يبني correct_answer صريحاً."""
        _, _, _, t_email = _teacher_class(app)
        client = login_as(app, t_email)
        resp = client.post(
            "/classes/question-bank/new",
            data={"question_text": "الأرض مسطّحة", "question_type": "true_false", "correct_tf": "false"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        from app.extensions import db
        from app.models.question_bank import QuestionBank

        with app.app_context():
            row = db.session.query(QuestionBank).order_by(QuestionBank.id.desc()).first()
            assert row is not None
            assert row.correct_answer == {"value": False}

    def test_question_bank_essay_entry_has_no_answer_payload(self, app):
        """سؤال مقالي (ليس mcq ولا صح/خطأ) يُحفظ بلا correct_answer."""
        _, _, _, t_email = _teacher_class(app)
        client = login_as(app, t_email)
        resp = client.post(
            "/classes/question-bank/new",
            data={"question_text": "اشرح دورة الماء", "question_type": "essay", "difficulty": "3"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        from app.extensions import db
        from app.models.question_bank import QuestionBank

        with app.app_context():
            row = db.session.query(QuestionBank).order_by(QuestionBank.id.desc()).first()
        assert row is not None
        assert row.question_text == "اشرح دورة الماء"
        assert row.correct_answer is None

    def test_proctor_force_submit_without_answers_in_payload(self, app):
        """تجاوز حدّ تبديل التبويبات يسلّم فوراً حتى بلا إجابات في الطلب."""
        sid, cid = _setup_class(app)
        qid = _quiz(app, cid, None, max_tab_switches=0)
        _question(app, qid)
        stu_id, s_email = mk_user(app, "student", school_id=sid)
        make_class_member(app, cid, stu_id)
        att_id = _attempt(app, qid, stu_id)
        client = login_as(app, s_email)
        with patch("app.services.email.send_quiz_result_email"):
            resp = client.post(
                f"/classes/attempt/{att_id}/proctor",
                json={"event_type": "tab_switch"},
            )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["auto_submit"] is True
        assert body["reason"] == "tab_switches_exceeded"

    def test_proctor_tab_switch_on_finished_attempt_is_noop(self, app):
        """محاولة مُسلَّمة سابقاً لا تُسلَّم مرة أخرى مهما بلغ عدد التبديلات."""
        sid, cid = _setup_class(app)
        qid = _quiz(app, cid, None, max_tab_switches=0)
        stu_id, s_email = mk_user(app, "student", school_id=sid)
        make_class_member(app, cid, stu_id)
        att_id = _attempt(app, qid, stu_id, status="submitted")
        client = login_as(app, s_email)
        resp = client.post(f"/classes/attempt/{att_id}/proctor", json={"event_type": "tab_switch"})
        assert resp.status_code == 200
        assert resp.get_json() == {"ok": True, "event_type": "tab_switch"}

    def test_proctor_fullscreen_exit_when_not_required(self, app):
        """حدث خروج ملء الشاشة على اختبار لا يفرضه لا يفعل شيئاً."""
        sid, cid = _setup_class(app)
        qid = _quiz(app, cid, None, fullscreen_required=False)
        stu_id, s_email = mk_user(app, "student", school_id=sid)
        make_class_member(app, cid, stu_id)
        att_id = _attempt(app, qid, stu_id)
        client = login_as(app, s_email)
        resp = client.post(f"/classes/attempt/{att_id}/proctor", json={"event_type": "fullscreen_exit"})
        assert resp.status_code == 200
        assert resp.get_json() == {"ok": True, "event_type": "fullscreen_exit"}

    def test_proctor_fullscreen_exit_on_finished_attempt_is_noop(self, app):
        """حدّ الخروج من ملء الشاشة لا يُسلّم محاولة منتهية."""
        sid, cid = _setup_class(app)
        qid = _quiz(app, cid, None, fullscreen_required=True)
        stu_id, s_email = mk_user(app, "student", school_id=sid)
        make_class_member(app, cid, stu_id)
        att_id = _attempt(app, qid, stu_id, status="submitted")
        client = login_as(app, s_email)
        for _ in range(3):
            resp = client.post(f"/classes/attempt/{att_id}/proctor", json={"event_type": "fullscreen_exit"})
        assert resp.status_code == 200
        assert resp.get_json() == {"ok": True, "event_type": "fullscreen_exit"}
