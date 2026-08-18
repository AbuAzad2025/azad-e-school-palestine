"""اختبارات مراقبة الاختبارات — ProctoringLog + مسار proctor."""

import json

from app.extensions import db
from tests.conftest import make_class, make_grade, make_school, make_subject, make_user


def _create_quiz_with_proctoring(app, teacher_id, school_id, max_tabs=3, fullscreen=True):
    """مساعدة: إنشاء اختبار مع تفعيل المراقبة + طالب + محاولة."""
    grade_id = make_grade(app, school_id)
    subject_id = make_subject(app)
    class_id = make_class(app, school_id, grade_id, subject_id, teacher_id=teacher_id)
    student_id = make_user(app, role="student", school_id=school_id)
    with app.app_context():
        from app.models.assessment import Question, Quiz, QuizAttempt

        quiz = Quiz(
            class_id=class_id,
            title="اختبار مراقبة",
            created_by=teacher_id,
            enable_proctoring=True,
            max_tab_switches=max_tabs,
            fullscreen_required=fullscreen,
        )
        db.session.add(quiz)
        db.session.flush()

        question = Question(
            quiz_id=quiz.id,
            type="mcq",
            prompt="2+2=?",
            options={
                "items": [{"label": "أ", "text": "3"}, {"label": "ب", "text": "4"}],
            },
            correct_answer={"index": 1},
            mark=1.0,
        )
        db.session.add(question)
        db.session.flush()

        attempt = QuizAttempt(
            quiz_id=quiz.id,
            student_id=student_id,
            attempt_no=1,
            status="in_progress",
        )
        db.session.add(attempt)
        db.session.commit()
        return quiz.id, attempt.id, student_id, class_id


def test_proctor_tab_switch_recorded(app):
    school_id = make_school(app)
    teacher_id = make_user(app, role="teacher", school_id=school_id)
    with app.app_context():
        quiz_id, attempt_id, student_id, class_id = _create_quiz_with_proctoring(app, teacher_id, school_id)
    with client_session(app, student_id) as client:
        resp = client.post(
            f"/classes/attempt/{attempt_id}/proctor",
            data=json.dumps({"event_type": "tab_switch"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.json["ok"] is True


def test_proctor_auto_submit_on_max_tabs(app):
    school_id = make_school(app)
    teacher_id = make_user(app, role="teacher", school_id=school_id)
    with app.app_context():
        quiz_id, attempt_id, student_id, class_id = _create_quiz_with_proctoring(
            app,
            teacher_id,
            school_id,
            max_tabs=2,
        )
    with client_session(app, student_id) as client:
        for _ in range(2):
            resp = client.post(
                f"/classes/attempt/{attempt_id}/proctor",
                data=json.dumps({"event_type": "tab_switch", "q_1": {"index": 1}}),
                content_type="application/json",
            )
        assert resp.status_code == 200
        assert resp.json.get("auto_submit") is True


def test_proctor_fullscreen_exit_recorded(app):
    school_id = make_school(app)
    teacher_id = make_user(app, role="teacher", school_id=school_id)
    with app.app_context():
        quiz_id, attempt_id, student_id, class_id = _create_quiz_with_proctoring(
            app,
            teacher_id,
            school_id,
            fullscreen=True,
        )
    with client_session(app, student_id) as client:
        resp = client.post(
            f"/classes/attempt/{attempt_id}/proctor",
            data=json.dumps({"event_type": "fullscreen_exit"}),
            content_type="application/json",
        )
        assert resp.status_code == 200


def test_proctor_auto_submit_on_fullscreen_exits(app):
    school_id = make_school(app)
    teacher_id = make_user(app, role="teacher", school_id=school_id)
    with app.app_context():
        quiz_id, attempt_id, student_id, class_id = _create_quiz_with_proctoring(
            app,
            teacher_id,
            school_id,
            fullscreen=True,
        )
    with client_session(app, student_id) as client:
        for _ in range(2):
            resp = client.post(
                f"/classes/attempt/{attempt_id}/proctor",
                data=json.dumps({"event_type": "fullscreen_exit", "q_1": {"index": 1}}),
                content_type="application/json",
            )
        assert resp.status_code == 200
        assert resp.json.get("auto_submit") is True


def test_proctor_invalid_event_type(app):
    school_id = make_school(app)
    teacher_id = make_user(app, role="teacher", school_id=school_id)
    with app.app_context():
        quiz_id, attempt_id, student_id, class_id = _create_quiz_with_proctoring(app, teacher_id, school_id)
    with client_session(app, student_id) as client:
        resp = client.post(
            f"/classes/attempt/{attempt_id}/proctor",
            data=json.dumps({"event_type": "invalid_event"}),
            content_type="application/json",
        )
        assert resp.status_code == 400


def test_proctor_wrong_student_forbidden(app):
    school_id = make_school(app)
    teacher_id = make_user(app, role="teacher", school_id=school_id)
    other_student = make_user(app, role="student", school_id=school_id)
    with app.app_context():
        quiz_id, attempt_id, student_id, class_id = _create_quiz_with_proctoring(app, teacher_id, school_id)
    with client_session(app, other_student) as client:
        resp = client.post(
            f"/classes/attempt/{attempt_id}/proctor",
            data=json.dumps({"event_type": "tab_switch"}),
            content_type="application/json",
        )
        assert resp.status_code == 403


def test_proctor_log_model(app):
    school_id = make_school(app)
    teacher_id = make_user(app, role="teacher", school_id=school_id)
    with app.app_context():
        from app.models.assessment import ProctoringLog

        quiz_id, attempt_id, student_id, class_id = _create_quiz_with_proctoring(app, teacher_id, school_id)
        log = ProctoringLog(attempt_id=attempt_id, event_type="tab_switch")
        db.session.add(log)
        db.session.commit()
        logs = ProctoringLog.query.filter_by(attempt_id=attempt_id).all()
        assert len(logs) == 1
        assert logs[0].event_type == "tab_switch"


# ═══════════════════════════════════════════════════════════════════
# مساعد: سياق جلسة اختبار
# ═══════════════════════════════════════════════════════════════════


class client_session:
    """سياق اختبار يُنشئ client ويسجّل المستخدم."""

    def __init__(self, app, user_id):
        self.app = app
        self.user_id = user_id
        self._client = None

    def __enter__(self):
        self._client = self.app.test_client()
        with self._client.session_transaction() as s:
            s["_user_id"] = str(self.user_id)
        return self._client

    def __exit__(self, *args):
        pass
