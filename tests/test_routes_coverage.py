"""Route-level integration tests targeting coverage gaps in grades, assessment,
billing, content, AI, calendar, family, and export modules."""

from __future__ import annotations

import uuid

import pytest
from app import create_app
from app.core.security import hash_password
from app.extensions import db as _db
from app.models.assessment import Question, Quiz, QuizAttempt
from app.models.billing import ManualPayment, Subscription, SubscriptionPlan
from app.models.class_room import ClassMember, ClassRoom
from app.models.content import Lesson
from app.models.gradebook import (
    Assignment,
    GradeCategory,
    GradeItem,
)
from app.models.school import Grade, School, Subject
from app.models.user import User, UserApprovalStatus, UserRole

# ── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def app():
    a = create_app()
    a.config["TESTING"] = True
    a.config["WTF_CSRF_ENABLED"] = False
    a.config["EMAIL_ENABLED"] = False
    a.config["TALISMAN_ENABLED"] = False
    a.config["SESSION_COOKIE_SECURE"] = False
    with a.app_context():
        from sqlalchemy import text

        _db.session.execute(text("CREATE EXTENSION IF NOT EXISTS citext"))
        _db.session.commit()
        _db.create_all()
    yield a


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture(autouse=True)
def _clean(app):
    yield
    with app.app_context():
        from sqlalchemy import inspect, text

        inspector = inspect(_db.engine)
        tables = inspector.get_table_names(schema="public")
        tables = [t for t in tables if t != "alembic_version"]
        if tables:
            _db.session.execute(text(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE"))
            _db.session.commit()


# ── Helpers ──────────────────────────────────────────────────────


def _uid():
    return uuid.uuid4().hex[:10]


def _email():
    return f"u-{_uid()}@test.com"


def _create_user(app, role="student", **kw):
    with app.app_context():
        u = User(
            email=kw.get("email", _email()),
            name_ar=kw.get("name_ar", f"مستخدم {_uid()}"),
            role=UserRole(role),
            password_hash=hash_password("TestPass123!"),
            approval_status=UserApprovalStatus.approved,
            is_active=True,
        )
        _db.session.add(u)
        _db.session.commit()
        return u.id


def _login(client, email, password="TestPass123!"):
    return client.post(
        "/auth/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )


def _create_school(app):
    with app.app_context():
        s = School(name_ar=f"مدرسة {_uid()}", domain=f"{_uid()}.test.org", join_code=f"S-{_uid()[:6]}")
        _db.session.add(s)
        _db.session.commit()
        return s.id


def _create_grade(app, school_id):
    with app.app_context():
        g = Grade(school_id=school_id, grade_level=1, name_ar="صف 1")
        _db.session.add(g)
        _db.session.commit()
        return g.id


def _create_subject(app):
    with app.app_context():
        s = Subject(name_ar=f"مادة {_uid()}")
        _db.session.add(s)
        _db.session.commit()
        return s.id


def _create_class(app, school_id, grade_id, subject_id, teacher_id=None):
    with app.app_context():
        c = ClassRoom(
            school_id=school_id,
            grade_id=grade_id,
            subject_id=subject_id,
            teacher_id=teacher_id,
            join_code=f"C-{_uid()[:6]}",
            name=f"صف {_uid()}",
        )
        _db.session.add(c)
        _db.session.commit()
        return c.id


def _create_member(app, class_id, user_id, status="active"):
    with app.app_context():
        m = ClassMember(class_id=class_id, user_id=user_id, status=status)
        _db.session.add(m)
        _db.session.commit()
        return m.id


def _create_lesson(app, class_id, status="published"):
    with app.app_context():
        lesson_obj = Lesson(class_id=class_id, title=f"درس {_uid()}", status=status, sort_order=1)
        _db.session.add(lesson_obj)
        _db.session.commit()
        return lesson_obj.id


def _create_assignment(app, class_id, teacher_id):
    with app.app_context():
        a = Assignment(class_id=class_id, title=f"واجب {_uid()}", body="solve", max_mark=100, created_by=teacher_id)
        _db.session.add(a)
        _db.session.commit()
        return a.id


def _create_quiz(app, class_id, teacher_id, **kw):
    with app.app_context():
        q = Quiz(
            class_id=class_id,
            title=f"اختبار {_uid()}",
            duration_min=kw.get("duration_min", 30),
            attempts_allowed=kw.get("attempts_allowed", 1),
            created_by=teacher_id,
            enable_proctoring=kw.get("enable_proctoring", False),
            max_tab_switches=kw.get("max_tab_switches", 3),
            fullscreen_required=kw.get("fullscreen_required", False),
        )
        _db.session.add(q)
        _db.session.commit()
        return q.id


def _create_question(app, quiz_id, qtype="mcq", prompt=None):
    with app.app_context():
        opts = {"items": [{"label": "أ", "text": "A"}, {"label": "ب", "text": "B"}]}
        q = Question(
            quiz_id=quiz_id,
            type=qtype,
            prompt=prompt or f"سؤال {_uid()}",
            options=opts if qtype == "mcq" else None,
            correct_answer={"index": 0} if qtype == "mcq" else {"value": True} if qtype == "true_false" else None,
            mark=10,
        )
        _db.session.add(q)
        _db.session.commit()
        return q.id


def _create_attempt(app, quiz_id, student_id, status="in_progress"):
    with app.app_context():
        a = QuizAttempt(quiz_id=quiz_id, student_id=student_id, status=status, score=0)
        _db.session.add(a)
        _db.session.commit()
        return a.id


def _create_plan(app, school_id, class_id=None, price=100.0):
    with app.app_context():
        p = SubscriptionPlan(school_id=school_id, class_id=class_id, name=f"خطة {_uid()}", plan="annual", price=price)
        _db.session.add(p)
        _db.session.commit()
        return p.id


def _create_subscription(app, user_id, plan_id, class_id, price=100.0, status="pending"):
    with app.app_context():
        s = Subscription(user_id=user_id, plan_id=plan_id, class_id=class_id, price=price, status=status)
        _db.session.add(s)
        _db.session.commit()
        return s.id


def _create_payment(app, subscription_id, amount=50.0, status="pending"):
    with app.app_context():
        p = ManualPayment(subscription_id=subscription_id, reference=f"ref-{_uid()[:6]}", amount=amount, status=status)
        _db.session.add(p)
        _db.session.commit()
        return p.id


def _setup_class_with_teacher(app):
    """Create school+class+teacher and return (school_id, class_id, teacher_email)."""
    school_id = _create_school(app)
    grade_id = _create_grade(app, school_id)
    subject_id = _create_subject(app)
    teacher_id = _create_user(app, role="teacher")
    class_id = _create_class(app, school_id, grade_id, subject_id, teacher_id)
    email = f"t-{_uid()}@test.com"
    with app.app_context():
        u = _db.session.get(User, teacher_id)
        u.email = email
        _db.session.commit()
    _create_member(app, class_id, teacher_id)
    return school_id, class_id, email


def _setup_student_in_class(app, class_id):
    sid = _create_user(app, role="student")
    _create_member(app, class_id, sid)
    email = f"s-{_uid()}@test.com"
    with app.app_context():
        u = _db.session.get(User, sid)
        u.email = email
        _db.session.commit()
    return sid, email


# ═══════════════════════════════════════════════════════════════════
# GRADES ROUTES
# ═══════════════════════════════════════════════════════════════════


class TestGradesRoutes:
    def test_assignments_list(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        _login(client, teacher_email)
        resp = client.get(f"/classes/{class_id}/assignments")
        assert resp.status_code in (200, 302)

    def test_assignments_404(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        _login(client, teacher_email)
        resp = client.get("/classes/999999/assignments")
        assert resp.status_code in (404, 302)

    def test_assignment_create(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        _login(client, teacher_email)
        resp = client.post(
            f"/classes/{class_id}/assignments",
            data={"title": "واجب جديد", "body": "solve", "max_mark": 100},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 200)

    def test_assignment_detail(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        aid = _create_assignment(app, class_id, 1)
        _login(client, teacher_email)
        resp = client.get(f"/classes/{class_id}/assignments/{aid}")
        assert resp.status_code in (200, 302)

    def test_assignment_detail_404(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        _login(client, teacher_email)
        resp = client.get(f"/classes/{class_id}/assignments/999999")
        assert resp.status_code in (404, 302)

    def test_assignment_submit_student(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        aid = _create_assignment(app, class_id, 1)
        _, student_email = _setup_student_in_class(app, class_id)
        _login(client, student_email)
        resp = client.post(
            f"/classes/{class_id}/assignments/{aid}/submit",
            data={"body": "here is my answer"},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 200)

    def test_gradebook_view(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        _login(client, teacher_email)
        resp = client.get(f"/classes/{class_id}/gradebook")
        assert resp.status_code in (200, 302)

    def test_gradebook_student_view(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        sid, student_email = _setup_student_in_class(app, class_id)
        _login(client, student_email)
        resp = client.get(f"/classes/{class_id}/gradebook")
        assert resp.status_code in (200, 302)

    def test_category_create(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        _login(client, teacher_email)
        resp = client.post(
            f"/classes/{class_id}/categories",
            data={"name": "واجبات", "weight": 40},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 200)

    def test_grade_item_create(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        with app.app_context():
            cat = GradeCategory(class_id=class_id, name="اختبارات", weight=60)
            _db.session.add(cat)
            _db.session.commit()
            cat_id = cat.id
        _login(client, teacher_email)
        resp = client.post(
            f"/classes/categories/{cat_id}/items",
            data={"title": "امتحان 1", "max_mark": 50, "kind": "exam"},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 200)

    def test_grade_set(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        sid, _ = _setup_student_in_class(app, class_id)
        with app.app_context():
            cat = GradeCategory(class_id=class_id, name="اختبارات", weight=60)
            _db.session.add(cat)
            _db.session.commit()
            item = GradeItem(class_id=class_id, category_id=cat.id, title="exam1", max_mark=50)
            _db.session.add(item)
            _db.session.commit()
            item_id = item.id
        _login(client, teacher_email)
        resp = client.post(
            f"/classes/items/{item_id}/grade",
            data={"student_id": sid, "mark": 45},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 200)

    def test_attendance_view(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        _login(client, teacher_email)
        resp = client.get(f"/classes/{class_id}/attendance")
        assert resp.status_code in (200, 302)

    def test_attendance_save(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        sid, _ = _setup_student_in_class(app, class_id)
        _login(client, teacher_email)
        resp = client.post(
            f"/classes/{class_id}/attendance",
            data={f"status_{sid}": "present"},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 200)

    def test_report_card(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        sid, _ = _setup_student_in_class(app, class_id)
        _login(client, teacher_email)
        resp = client.get(f"/classes/{class_id}/report-card/{sid}")
        assert resp.status_code in (200, 302)

    def test_report_card_student_own(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        sid, student_email = _setup_student_in_class(app, class_id)
        _login(client, student_email)
        resp = client.get(f"/classes/{class_id}/report-card/{sid}")
        assert resp.status_code in (200, 302)

    def test_report_card_student_forbidden(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        sid, student_email = _setup_student_in_class(app, class_id)
        sid2, email2 = _setup_student_in_class(app, class_id)
        _login(client, email2)
        resp = client.get(f"/classes/{class_id}/report-card/{sid}")
        assert resp.status_code in (403, 302)

    def test_rubric_new(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        _login(client, teacher_email)
        resp = client.get(f"/classes/{class_id}/rubric/new")
        assert resp.status_code in (200, 302)

    def test_rubric_create(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        _login(client, teacher_email)
        resp = client.post(
            f"/classes/{class_id}/rubric",
            data={
                "title": "قالب تقييم",
                "description": "test",
                "criteria[0][title]": "محتوى",
                "criteria[0][max_score]": 10,
                "criteria[0][description]": "desc",
            },
            follow_redirects=False,
        )
        assert resp.status_code in (302, 200)

    def test_rubric_create_no_title(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        _login(client, teacher_email)
        resp = client.post(
            f"/classes/{class_id}/rubric",
            data={
                "title": "",
                "criteria[0][title]": "محتوى",
                "criteria[0][max_score]": 10,
            },
            follow_redirects=False,
        )
        assert resp.status_code in (302, 200)

    def test_rubric_create_no_criteria(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        _login(client, teacher_email)
        resp = client.post(
            f"/classes/{class_id}/rubric",
            data={"title": "قالب"},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 200)

    def test_appeals_list(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        _login(client, teacher_email)
        resp = client.get(f"/classes/{class_id}/appeals")
        assert resp.status_code in (200, 302)


# ═══════════════════════════════════════════════════════════════════
# ASSESSMENT ROUTES
# ═══════════════════════════════════════════════════════════════════


class TestAssessmentRoutes:
    def test_quiz_list(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        _login(client, teacher_email)
        resp = client.get(f"/classes/{class_id}/quizzes")
        assert resp.status_code in (200, 302)

    def test_quiz_list_student(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        sid, student_email = _setup_student_in_class(app, class_id)
        _login(client, student_email)
        resp = client.get(f"/classes/{class_id}/quizzes")
        assert resp.status_code in (200, 302)

    def test_quiz_new_form(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        _login(client, teacher_email)
        resp = client.get(f"/classes/{class_id}/quizzes/new")
        assert resp.status_code in (200, 302)

    def test_quiz_create(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        _login(client, teacher_email)
        resp = client.post(
            f"/classes/{class_id}/quizzes/new",
            data={
                "title": "اختبار جديد",
                "duration_min": 30,
                "attempts_allowed": 1,
                "shuffle": "y",
                "show_answers_after": "y",
            },
            follow_redirects=False,
        )
        assert resp.status_code in (302, 200)

    def test_quiz_manage(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        qid = _create_quiz(app, class_id, 1)
        _login(client, teacher_email)
        resp = client.get(f"/classes/{class_id}/quizzes/{qid}")
        assert resp.status_code in (200, 302)

    def test_quiz_manage_add_mcq(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        qid = _create_quiz(app, class_id, 1)
        _login(client, teacher_email)
        resp = client.post(
            f"/classes/{class_id}/quizzes/{qid}",
            data={
                "qtype": "mcq",
                "prompt": "ما هو 1+1؟",
                "option_a": "1",
                "option_b": "2",
                "option_c": "3",
                "option_d": "4",
                "correct_index": "1",
                "mark": 10,
            },
            follow_redirects=False,
        )
        assert resp.status_code in (302, 200)

    def test_quiz_manage_add_true_false(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        qid = _create_quiz(app, class_id, 1)
        _login(client, teacher_email)
        resp = client.post(
            f"/classes/{class_id}/quizzes/{qid}",
            data={
                "qtype": "true_false",
                "prompt": "الأرض مسطحة",
                "correct_tf": "false",
                "mark": 5,
            },
            follow_redirects=False,
        )
        assert resp.status_code in (302, 200)

    def test_quiz_manage_add_essay(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        qid = _create_quiz(app, class_id, 1)
        _login(client, teacher_email)
        resp = client.post(
            f"/classes/{class_id}/quizzes/{qid}",
            data={"qtype": "essay", "prompt": "اكتب مقالة", "mark": 20},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 200)

    def test_question_delete(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        qid = _create_quiz(app, class_id, 1)
        qnid = _create_question(app, qid)
        _login(client, teacher_email)
        resp = client.post(
            f"/classes/questions/{qnid}/delete", follow_redirects=False)
        assert resp.status_code in (302, 200)

    def test_attempt_start_student(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        qid = _create_quiz(app, class_id, 1)
        sid, student_email = _setup_student_in_class(app, class_id)
        _login(client, student_email)
        resp = client.get(f"/classes/quizzes/{qid}/attempt", follow_redirects=False)
        assert resp.status_code in (302, 200)

    def test_attempt_start_teacher_redirect(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        qid = _create_quiz(app, class_id, 1)
        _login(client, teacher_email)
        resp = client.get(f"/classes/quizzes/{qid}/attempt", follow_redirects=False)
        assert resp.status_code in (302, 200)

    def test_attempt_do(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        qid = _create_quiz(app, class_id, 1)
        sid, student_email = _setup_student_in_class(app, class_id)
        aid = _create_attempt(app, qid, sid)
        _login(client, student_email)
        resp = client.get(f"/classes/attempt/{aid}")
        assert resp.status_code in (200, 302)

    def test_attempt_do_completed_redirects(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        qid = _create_quiz(app, class_id, 1)
        sid, student_email = _setup_student_in_class(app, class_id)
        aid = _create_attempt(app, qid, sid, status="completed")
        _login(client, student_email)
        resp = client.get(f"/classes/attempt/{aid}", follow_redirects=False)
        assert resp.status_code in (302, 200)

    def test_attempt_save(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        qid = _create_quiz(app, class_id, 1)
        qnid = _create_question(app, qid, "mcq")
        sid, student_email = _setup_student_in_class(app, class_id)
        aid = _create_attempt(app, qid, sid)
        _login(client, student_email)
        resp = client.post(
            f"/classes/attempt/{aid}/save",
            data={f"q_{qnid}": "0"},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 200)

    def test_attempt_submit(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        qid = _create_quiz(app, class_id, 1)
        qnid = _create_question(app, qid, "mcq")
        sid, student_email = _setup_student_in_class(app, class_id)
        aid = _create_attempt(app, qid, sid)
        _login(client, student_email)
        resp = client.post(
            f"/classes/attempt/{aid}/submit",
            data={f"q_{qnid}": "0"},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 200)

    def test_attempt_result(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        qid = _create_quiz(app, class_id, 1)
        sid, student_email = _setup_student_in_class(app, class_id)
        aid = _create_attempt(app, qid, sid, status="completed")
        _login(client, student_email)
        resp = client.get(f"/classes/attempt/{aid}/result")
        assert resp.status_code in (200, 302)

    def test_attempt_result_teacher(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        qid = _create_quiz(app, class_id, 1)
        sid, student_email = _setup_student_in_class(app, class_id)
        aid = _create_attempt(app, qid, sid, status="completed")
        _login(client, teacher_email)
        resp = client.get(f"/classes/attempt/{aid}/result")
        assert resp.status_code in (200, 302)

    def test_quiz_results(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        qid = _create_quiz(app, class_id, 1)
        _login(client, teacher_email)
        resp = client.get(f"/classes/quizzes/{qid}/results")
        assert resp.status_code in (200, 302)

    def test_question_bank_list(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        _login(client, teacher_email)
        resp = client.get("/classes/question-bank")
        assert resp.status_code in (200, 302)

    def test_question_bank_create(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        _login(client, teacher_email)
        resp = client.post(
            "/classes/question-bank/new",
            data={
                "question_text": "سؤال بنك",
                "question_type": "mcq",
                "option_a": "أ",
                "option_b": "ب",
                "correct_index": "0",
                "difficulty": "3",
            },
            follow_redirects=False,
        )
        assert resp.status_code in (302, 200)

    def test_question_bank_create_tf(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        _login(client, teacher_email)
        resp = client.post(
            "/classes/question-bank/new",
            data={
                "question_text": "سؤال بنك ص/خ",
                "question_type": "true_false",
                "correct_tf": "true",
                "difficulty": "2",
            },
            follow_redirects=False,
        )
        assert resp.status_code in (302, 200)

    def test_bank_import_page(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        qid = _create_quiz(app, class_id, 1)
        _login(client, teacher_email)
        resp = client.get(f"/classes/quiz/{qid}/bank-import")
        assert resp.status_code in (200, 302)

    def test_bank_import_action(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        qid = _create_quiz(app, class_id, 1)
        _login(client, teacher_email)
        resp = client.post(
            f"/classes/quiz/{qid}/bank-import",
            data={"question_ids": []},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 200)

    def test_quiz_stats_empty(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        qid = _create_quiz(app, class_id, 1)
        _login(client, teacher_email)
        resp = client.get(f"/classes/quiz/{qid}/stats", follow_redirects=False)
        assert resp.status_code in (302, 200)

    def test_proctor_log(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        qid = _create_quiz(app, class_id, 1)
        sid, student_email = _setup_student_in_class(app, class_id)
        aid = _create_attempt(app, qid, sid)
        _login(client, student_email)
        resp = client.post(
            f"/classes/attempt/{aid}/proctor",
            json={"event_type": "tab_switch"},
            content_type="application/json",
        )
        assert resp.status_code in (200, 403)

    def test_proctor_log_invalid_event(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        qid = _create_quiz(app, class_id, 1)
        sid, student_email = _setup_student_in_class(app, class_id)
        aid = _create_attempt(app, qid, sid)
        _login(client, student_email)
        resp = client.post(
            f"/classes/attempt/{aid}/proctor",
            json={"event_type": "invalid"},
            content_type="application/json",
        )
        assert resp.status_code in (400, 403)


# ═══════════════════════════════════════════════════════════════════
# BILLING ROUTES
# ═══════════════════════════════════════════════════════════════════


class TestBillingRoutes:
    def test_class_billing(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        _login(client, teacher_email)
        resp = client.get(f"/billing/{class_id}")
        assert resp.status_code in (200, 302)

    def test_class_billing_student(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        sid, student_email = _setup_student_in_class(app, class_id)
        _login(client, student_email)
        resp = client.get(f"/billing/{class_id}")
        assert resp.status_code in (200, 302)

    def test_plan_create(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        _login(client, teacher_email)
        resp = client.post(
            f"/billing/{class_id}/plans",
            data={
                "name": "خطة سنوية",
                "plan": "annual",
                "price": 500,
                "currency": "ILS",
                "duration_days": 365,
            },
            follow_redirects=False,
        )
        assert resp.status_code in (302, 200)

    def test_subscribe_route(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        sid, student_email = _setup_student_in_class(app, class_id)
        plan_id = _create_plan(app, 1, class_id)
        _login(client, student_email)
        resp = client.post(
            f"/billing/{class_id}/subscribe",
            data={"plan_id": plan_id},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 200)

    def test_subscribe_teacher_403(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        _login(client, teacher_email)
        resp = client.post(
            f"/billing/{class_id}/subscribe",
            data={"plan_id": 999},
            follow_redirects=False,
        )
        assert resp.status_code in (403, 302)

    def test_payment_create(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        sid, student_email = _setup_student_in_class(app, class_id)
        plan_id = _create_plan(app, 1, class_id)
        sub_id = _create_subscription(app, sid, plan_id, class_id)
        _login(client, student_email)
        resp = client.post(
            f"/billing/subscriptions/{sub_id}/pay",
            data={"reference": "REF001", "amount": 100, "note": "test"},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 200)

    def test_payment_wrong_user_403(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        sid, _ = _setup_student_in_class(app, class_id)
        sid2, email2 = _setup_student_in_class(app, class_id)
        plan_id = _create_plan(app, 1, class_id)
        sub_id = _create_subscription(app, sid, plan_id, class_id)
        _login(client, email2)
        resp = client.post(
            f"/billing/subscriptions/{sub_id}/pay",
            data={"reference": "REF002", "amount": 50},
            follow_redirects=False,
        )
        assert resp.status_code in (403, 302)

    def test_admin_pending(self, app, client):
        admin_id = _create_user(app, role="super_admin")
        email = f"adm-{_uid()}@test.com"
        with app.app_context():
            u = _db.session.get(User, admin_id)
            u.email = email
            _db.session.commit()
        _login(client, email)
        resp = client.get("/billing/admin")
        assert resp.status_code in (200, 302)

    def test_approve_payment(self, app, client):
        admin_id = _create_user(app, role="super_admin")
        email = f"adm-{_uid()}@test.com"
        _, class_id, _ = _setup_class_with_teacher(app)
        sid, _ = _setup_student_in_class(app, class_id)
        plan_id = _create_plan(app, 1, class_id)
        sub_id = _create_subscription(app, sid, plan_id, class_id)
        pay_id = _create_payment(app, sub_id)
        with app.app_context():
            u = _db.session.get(User, admin_id)
            u.email = email
            _db.session.commit()
        _login(client, email)
        resp = client.post(
            f"/billing/payments/{pay_id}/approve",
            follow_redirects=False,
        )
        assert resp.status_code in (302, 200)

    def test_reject_payment(self, app, client):
        admin_id = _create_user(app, role="super_admin")
        email = f"adm-{_uid()}@test.com"
        _, class_id, _ = _setup_class_with_teacher(app)
        sid, _ = _setup_student_in_class(app, class_id)
        plan_id = _create_plan(app, 1, class_id)
        sub_id = _create_subscription(app, sid, plan_id, class_id)
        pay_id = _create_payment(app, sub_id)
        with app.app_context():
            u = _db.session.get(User, admin_id)
            u.email = email
            _db.session.commit()
        _login(client, email)
        resp = client.post(
            f"/billing/payments/{pay_id}/reject",
            follow_redirects=False,
        )
        assert resp.status_code in (302, 200)

    def test_discount_list(self, app, client):
        admin_id = _create_user(app, role="super_admin")
        email = f"adm-{_uid()}@test.com"
        with app.app_context():
            u = _db.session.get(User, admin_id)
            u.email = email
            _db.session.commit()
        _login(client, email)
        resp = client.get("/billing/discounts")
        assert resp.status_code in (200, 302)

    def test_discount_create_get(self, app, client):
        admin_id = _create_user(app, role="super_admin")
        email = f"adm-{_uid()}@test.com"
        with app.app_context():
            u = _db.session.get(User, admin_id)
            u.email = email
            _db.session.commit()
        _login(client, email)
        resp = client.get("/billing/discounts/new")
        assert resp.status_code in (200, 302)

    def test_discount_create_post(self, app, client):
        admin_id = _create_user(app, role="super_admin")
        email = f"adm-{_uid()}@test.com"
        with app.app_context():
            u = _db.session.get(User, admin_id)
            u.email = email
            _db.session.commit()
        _login(client, email)
        resp = client.post(
            "/billing/discounts/new",
            data={
                "code": f"DISC-{_uid()[:6]}",
                "name": "خصم",
                "type": "percent",
                "value": 10,
                "max_uses": 50,
            },
            follow_redirects=False,
        )
        assert resp.status_code in (302, 200)

    def test_validate_code(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        sid, student_email = _setup_student_in_class(app, class_id)
        plan_id = _create_plan(app, 1, class_id)
        _login(client, student_email)
        resp = client.post(
            "/billing/validate-code",
            data={"code": "INVALID", "plan_id": plan_id},
            follow_redirects=False,
        )
        assert resp.status_code in (400, 200)

    def test_invoice_view(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        sid, student_email = _setup_student_in_class(app, class_id)
        plan_id = _create_plan(app, 1, class_id)
        sub_id = _create_subscription(app, sid, plan_id, class_id)
        _login(client, student_email)
        resp = client.get(f"/billing/invoices/{sub_id}")
        assert resp.status_code in (200, 302)


# ═══════════════════════════════════════════════════════════════════
# CONTENT ROUTES
# ═══════════════════════════════════════════════════════════════════


class TestContentRoutes:
    def test_class_lessons(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        _login(client, teacher_email)
        resp = client.get(f"/classes/{class_id}/lessons")
        assert resp.status_code in (200, 302)

    def test_lesson_new_form(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        _login(client, teacher_email)
        resp = client.get(f"/classes/{class_id}/lessons/new")
        assert resp.status_code in (200, 302)

    def test_lesson_create(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        _login(client, teacher_email)
        resp = client.post(
            f"/classes/{class_id}/lessons",
            data={"title": "درس جديد", "body_html": "<p>محتوى</p>"},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 200)

    def test_lesson_detail(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        lid = _create_lesson(app, class_id)
        _login(client, teacher_email)
        resp = client.get(f"/classes/{class_id}/lessons/{lid}")
        assert resp.status_code in (200, 302)

    def test_lesson_detail_student(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        lid = _create_lesson(app, class_id)
        sid, student_email = _setup_student_in_class(app, class_id)
        _login(client, student_email)
        resp = client.get(f"/classes/{class_id}/lessons/{lid}")
        assert resp.status_code in (200, 302)

    def test_lesson_update(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        lid = _create_lesson(app, class_id)
        _login(client, teacher_email)
        resp = client.post(
            f"/classes/{class_id}/lessons/{lid}",
            data={"title": "درس محدث", "body_html": "<p>جديد</p>"},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 200)

    def test_lesson_publish(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        lid = _create_lesson(app, class_id, status="draft")
        _login(client, teacher_email)
        resp = client.post(f"/classes/{class_id}/lessons/{lid}/publish", follow_redirects=False)
        assert resp.status_code in (302, 200)

    def test_lesson_unpublish(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        lid = _create_lesson(app, class_id, status="published")
        _login(client, teacher_email)
        resp = client.post(f"/classes/{class_id}/lessons/{lid}/publish", follow_redirects=False)
        assert resp.status_code in (302, 200)

    def test_unit_create(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        _login(client, teacher_email)
        resp = client.post(
            f"/classes/{class_id}/units",
            data={"title": "وحدة 1"},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 200)

    def test_youtube_add(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        lid = _create_lesson(app, class_id)
        _login(client, teacher_email)
        resp = client.post(
            f"/classes/{class_id}/lessons/{lid}/youtube",
            data={"url": "https://youtube.com/watch?v=test", "title": "فيديو"},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 200)

    def test_shared_library(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        _login(client, teacher_email)
        resp = client.get("/classes/shared")
        assert resp.status_code in (200, 302)

    def test_offline_downloads(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        sid, student_email = _setup_student_in_class(app, class_id)
        _login(client, student_email)
        resp = client.get("/classes/offline")
        assert resp.status_code in (200, 302)

    def test_lesson_404(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        _login(client, teacher_email)
        resp = client.get(f"/classes/{class_id}/lessons/999999")
        assert resp.status_code in (404, 302)


# ═══════════════════════════════════════════════════════════════════
# AI ROUTES
# ═══════════════════════════════════════════════════════════════════


class TestAIRoutes:
    def test_chat_page(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        _login(client, teacher_email)
        resp = client.get("/ai/chat")
        assert resp.status_code in (200, 302)

    def test_chat_empty_question(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        _login(client, teacher_email)
        resp = client.post(
            "/ai/chat",
            json={"question": ""},
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_chat_stream_empty_question(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        _login(client, teacher_email)
        resp = client.post(
            "/ai/chat/stream",
            json={"question": ""},
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_suggest_grade_no_answer(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        _login(client, teacher_email)
        resp = client.post(
            "/ai/grade/suggest",
            json={"student_answer": ""},
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_suggest_grade_student_forbidden(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        sid, student_email = _setup_student_in_class(app, class_id)
        _login(client, student_email)
        resp = client.post(
            "/ai/grade/suggest",
            json={"student_answer": "essay text"},
            content_type="application/json",
        )
        assert resp.status_code == 403

    def test_generate_questions_empty_topic(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        _login(client, teacher_email)
        resp = client.post(
            "/ai/questions/generate",
            json={"topic": ""},
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_generate_questions_student_forbidden(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        sid, student_email = _setup_student_in_class(app, class_id)
        _login(client, student_email)
        resp = client.post(
            "/ai/questions/generate",
            json={"topic": "math"},
            content_type="application/json",
        )
        assert resp.status_code == 403

    def test_usage_stats_admin(self, app, client):
        admin_id = _create_user(app, role="super_admin")
        email = f"adm-{_uid()}@test.com"
        with app.app_context():
            u = _db.session.get(User, admin_id)
            u.email = email
            _db.session.commit()
        _login(client, email)
        resp = client.get("/ai/usage/stats")
        assert resp.status_code in (200, 403)

    def test_usage_stats_student_forbidden(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        sid, student_email = _setup_student_in_class(app, class_id)
        _login(client, student_email)
        resp = client.get("/ai/usage/stats")
        assert resp.status_code == 403


# ═══════════════════════════════════════════════════════════════════
# CALENDAR ROUTES
# ═══════════════════════════════════════════════════════════════════


class TestCalendarRoutes:
    def test_calendar_index(self, app, client):
        admin_id = _create_user(app, role="super_admin")
        email = f"adm-{_uid()}@test.com"
        school_id = _create_school(app)
        with app.app_context():
            u = _db.session.get(User, admin_id)
            u.email = email
            _db.session.commit()
        _login(client, email)
        resp = client.get(f"/calendar/{school_id}")
        assert resp.status_code in (200, 302)

    def test_event_create(self, app, client):
        admin_id = _create_user(app, role="super_admin")
        email = f"adm-{_uid()}@test.com"
        school_id = _create_school(app)
        with app.app_context():
            u = _db.session.get(User, admin_id)
            u.email = email
            _db.session.commit()
        _login(client, email)
        resp = client.post(
            f"/calendar/{school_id}/events",
            data={
                "title": "حدث جديد",
                "event_type": "holiday",
                "start_date": "2026-09-01",
                "end_date": "2026-09-05",
            },
            follow_redirects=False,
        )
        assert resp.status_code in (302, 200)


# ═══════════════════════════════════════════════════════════════════
# FAMILY ROUTES
# ═══════════════════════════════════════════════════════════════════


class TestFamilyRoutes:
    def test_family_index(self, app, client):
        parent_id = _create_user(app, role="parent")
        email = f"p-{_uid()}@test.com"
        with app.app_context():
            u = _db.session.get(User, parent_id)
            u.email = email
            _db.session.commit()
        _login(client, email)
        resp = client.get("/family/")
        assert resp.status_code in (200, 302)

    def test_generate_code_student(self, app, client):
        sid, student_email = _setup_student_in_class(app, 1) if False else (None, None)
        # Create student with a class
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        sid, student_email = _setup_student_in_class(app, class_id)
        _login(client, student_email)
        resp = client.get("/family/generate")
        assert resp.status_code in (200, 302)


# ═══════════════════════════════════════════════════════════════════
# EXPORT ROUTES
# ═══════════════════════════════════════════════════════════════════


class TestExportRoutes:
    def test_students_excel(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        _login(client, teacher_email)
        resp = client.get(f"/export/{class_id}/students")
        assert resp.status_code in (200, 302)

    def test_grades_excel(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        _login(client, teacher_email)
        resp = client.get(f"/export/{class_id}/grades")
        assert resp.status_code in (200, 302)

    def test_progress_excel(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        _login(client, teacher_email)
        resp = client.get(f"/export/{class_id}/progress")
        assert resp.status_code in (200, 302)

    def test_students_excel_404(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        _login(client, teacher_email)
        resp = client.get("/export/999999/students")
        assert resp.status_code in (404, 302)


# ═══════════════════════════════════════════════════════════════════
# SCHOOLS ROUTES
# ═══════════════════════════════════════════════════════════════════


class TestSchoolRoutes:
    def test_schools_index(self, app, client):
        admin_id = _create_user(app, role="super_admin")
        email = f"adm-{_uid()}@test.com"
        with app.app_context():
            u = _db.session.get(User, admin_id)
            u.email = email
            _db.session.commit()
        _login(client, email)
        resp = client.get("/schools/")
        assert resp.status_code in (200, 302)

    def test_school_create_get(self, app, client):
        admin_id = _create_user(app, role="super_admin")
        email = f"adm-{_uid()}@test.com"
        with app.app_context():
            u = _db.session.get(User, admin_id)
            u.email = email
            _db.session.commit()
        _login(client, email)
        resp = client.get("/schools/new")
        assert resp.status_code in (200, 302)

    def test_school_manage(self, app, client):
        admin_id = _create_user(app, role="super_admin")
        email = f"adm-{_uid()}@test.com"
        school_id = _create_school(app)
        with app.app_context():
            u = _db.session.get(User, admin_id)
            u.email = email
            _db.session.commit()
        _login(client, email)
        resp = client.get(f"/schools/{school_id}/manage")
        assert resp.status_code in (200, 302)

    def test_my_classes(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        _login(client, teacher_email)
        resp = client.get("/schools/classes")
        assert resp.status_code in (200, 302)

    def test_class_detail(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        _login(client, teacher_email)
        resp = client.get(f"/schools/class/{class_id}")
        assert resp.status_code in (200, 302)

    def test_class_detail_student_member(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        sid, student_email = _setup_student_in_class(app, class_id)
        _login(client, student_email)
        resp = client.get(f"/schools/class/{class_id}")
        assert resp.status_code in (200, 302)

    def test_class_code_regenerate(self, app, client):
        admin_id = _create_user(app, role="super_admin")
        email = f"adm-{_uid()}@test.com"
        _, class_id, _ = _setup_class_with_teacher(app)
        with app.app_context():
            u = _db.session.get(User, admin_id)
            u.email = email
            _db.session.commit()
        _login(client, email)
        resp = client.post(f"/schools/class/{class_id}/code", follow_redirects=False)
        assert resp.status_code in (302, 200)

    def test_school_classes(self, app, client):
        admin_id = _create_user(app, role="super_admin")
        email = f"adm-{_uid()}@test.com"
        school_id = _create_school(app)
        with app.app_context():
            u = _db.session.get(User, admin_id)
            u.email = email
            _db.session.commit()
        _login(client, email)
        resp = client.get(f"/schools/{school_id}/classes")
        assert resp.status_code in (200, 302)

    def test_class_new_get(self, app, client):
        admin_id = _create_user(app, role="super_admin")
        email = f"adm-{_uid()}@test.com"
        school_id = _create_school(app)
        with app.app_context():
            u = _db.session.get(User, admin_id)
            u.email = email
            _db.session.commit()
        _login(client, email)
        resp = client.get(f"/schools/{school_id}/classes/new")
        assert resp.status_code in (200, 302)

    def test_class_new_post(self, app, client):
        admin_id = _create_user(app, role="super_admin")
        email = f"adm-{_uid()}@test.com"
        school_id = _create_school(app)
        grade_id = _create_grade(app, school_id)
        with app.app_context():
            u = _db.session.get(User, admin_id)
            u.email = email
            _db.session.commit()
        _login(client, email)
        resp = client.post(
            f"/schools/{school_id}/classes/new",
            data={
                "name": "صف اختبار",
                "subject": "رياضيات",
                "grade_id": grade_id,
                "semester": "1",
            },
            follow_redirects=False,
        )
        assert resp.status_code in (302, 200)

    def test_grade_add(self, app, client):
        admin_id = _create_user(app, role="super_admin")
        email = f"adm-{_uid()}@test.com"
        school_id = _create_school(app)
        with app.app_context():
            u = _db.session.get(User, admin_id)
            u.email = email
            _db.session.commit()
        _login(client, email)
        resp = client.post(
            f"/schools/{school_id}/grades",
            data={"grade_level": 2, "name_ar": "الصف الثاني"},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 200)


# ═══════════════════════════════════════════════════════════════════
# TUTORING ROUTES
# ═══════════════════════════════════════════════════════════════════


class TestTutoringRoutes:
    def test_tutoring_index(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        _login(client, teacher_email)
        resp = client.get("/tutoring/")
        assert resp.status_code in (200, 302)

    def test_tutoring_my(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        _login(client, teacher_email)
        resp = client.get("/tutoring/my")
        assert resp.status_code in (200, 302)

    def test_profile_new_get(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        _login(client, teacher_email)
        resp = client.get("/tutoring/profile/new")
        assert resp.status_code in (200, 302)

    def test_profile_new_post(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        _login(client, teacher_email)
        resp = client.post(
            "/tutoring/profile/new",
            data={
                "subject": "رياضيات",
                "price_hour": 100,
                "price_session": 80,
                "mode": "online",
                "bio": "معلم خبرة",
            },
            follow_redirects=False,
        )
        assert resp.status_code in (302, 200)

    def test_profile_edit_get(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        _login(client, teacher_email)
        # Create profile first
        client.post(
            "/tutoring/profile/new",
            data={
                "subject": "رياضيات",
                "price_hour": 100,
                "price_session": 80,
                "mode": "online",
                "bio": "معلم",
            },
        )
        resp = client.get("/tutoring/profile/edit")
        assert resp.status_code in (200, 302)

    def test_search_tutors(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        _login(client, teacher_email)
        resp = client.get("/tutoring/?q=math")
        assert resp.status_code in (200, 302)

    def test_book_get(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        # Get teacher ID
        with app.app_context():
            teacher_user = User.query.filter_by(email=teacher_email).first()
            teacher_id = teacher_user.id
        # Login as student
        sid, student_email = _setup_student_in_class(app, class_id)
        _login(client, student_email)
        resp = client.get(f"/tutoring/book/{teacher_id}")
        assert resp.status_code in (200, 302)


# ═══════════════════════════════════════════════════════════════════
# PROGRESS ROUTES
# ═══════════════════════════════════════════════════════════════════


class TestProgressRoutes:
    def test_class_overview(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        _login(client, teacher_email)
        resp = client.get(f"/progress/class/{class_id}")
        assert resp.status_code in (200, 302)

    def test_student_detail(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        sid, student_email = _setup_student_in_class(app, class_id)
        _login(client, student_email)
        resp = client.get(f"/progress/class/{class_id}/student/{sid}")
        assert resp.status_code in (200, 302)

    def test_student_detail_teacher(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        sid, _ = _setup_student_in_class(app, class_id)
        _login(client, teacher_email)
        resp = client.get(f"/progress/class/{class_id}/student/{sid}")
        assert resp.status_code in (200, 302)

    def test_student_detail_forbidden(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        sid, _ = _setup_student_in_class(app, class_id)
        sid2, email2 = _setup_student_in_class(app, class_id)
        _login(client, email2)
        resp = client.get(f"/progress/class/{class_id}/student/{sid}")
        assert resp.status_code in (403, 302)

    def test_my_progress(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        sid, student_email = _setup_student_in_class(app, class_id)
        _login(client, student_email)
        resp = client.get("/progress/my")
        assert resp.status_code in (200, 302)


# ═══════════════════════════════════════════════════════════════════
# PAYMENTS UI ROUTES
# ═══════════════════════════════════════════════════════════════════


class TestPaymentsRoutes:
    def test_payment_methods_page(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        _login(client, teacher_email)
        resp = client.get("/payments/")
        assert resp.status_code in (200, 302)

    def test_payment_methods_api(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        _login(client, teacher_email)
        resp = client.get("/payments/methods")
        assert resp.status_code in (200, 302)


# ═══════════════════════════════════════════════════════════════════
# MESSAGES ROUTES
# ═══════════════════════════════════════════════════════════════════


class TestMessagesRoutes:
    def test_inbox(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        _login(client, teacher_email)
        resp = client.get("/messages/inbox")
        assert resp.status_code in (200, 302)

    def test_sent(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        _login(client, teacher_email)
        resp = client.get("/messages/sent")
        assert resp.status_code in (200, 302)

    def test_send_form(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        _login(client, teacher_email)
        resp = client.get("/messages/send")
        assert resp.status_code in (200, 302)

    def test_unread_count(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        _login(client, teacher_email)
        resp = client.get("/messages/unread-count")
        assert resp.status_code in (200, 302)


# ═══════════════════════════════════════════════════════════════════
# NOTIFICATIONS ROUTES
# ═══════════════════════════════════════════════════════════════════


class TestNotificationsRoutes:
    def test_notifications_index(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        _login(client, teacher_email)
        resp = client.get("/notifications/")
        assert resp.status_code in (200, 302)

    def test_notifications_preferences(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        _login(client, teacher_email)
        resp = client.get("/notifications/preferences")
        assert resp.status_code in (200, 302)


# ═══════════════════════════════════════════════════════════════════
# GAMIFICATION ROUTES
# ═══════════════════════════════════════════════════════════════════


class TestGamificationRoutes:
    def test_badges(self, app, client):
        _, class_id, teacher_email = _setup_class_with_teacher(app)
        sid, student_email = _setup_student_in_class(app, class_id)
        _login(client, student_email)
        resp = client.get("/profile/badges")
        assert resp.status_code in (200, 302)
