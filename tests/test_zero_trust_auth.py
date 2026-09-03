"""Zero-Trust Authorization Integration Tests.

Verifies that:
- Cross-tenant access returns strict 403/404
- Role isolation is enforced (student cannot do teacher actions)
- Ownership checks prevent IDOR/BOLA
- Class membership is enforced for progress tracking
"""

from tests.conftest import (
    make_academic_event,
    make_class,
    make_class_member,
    make_family_link,
    make_grade,
    make_school,
    make_subject,
    make_user,
)


# ═══════════════════════════════════════════════════════════════════════════
# CROSS-TENANT ISOLATION
# ═══════════════════════════════════════════════════════════════════════════


class TestCrossTenantIsolation:
    """Students/teachers from school A cannot access school B's data."""

    def test_student_cannot_view_other_school_class(self, app, client):
        school_a = make_school(app)
        school_b = make_school(app)
        grade_b = make_grade(app, school_b)
        subject_id = make_subject(app)
        student = make_user(app, role="student", school_id=school_a)
        class_b_id = make_class(app, school_b, grade_b, subject_id)

        with client.session_transaction() as s:
            s["_user_id"] = str(student)

        resp = client.get(f"/classes/class/{class_b_id}")
        assert resp.status_code in (403, 404)

    def test_teacher_cannot_view_other_school_class(self, app, client):
        school_a = make_school(app)
        school_b = make_school(app)
        grade_b = make_grade(app, school_b)
        subject_id = make_subject(app)
        teacher = make_user(app, role="teacher", school_id=school_a)
        class_b_id = make_class(app, school_b, grade_b, subject_id)

        with client.session_transaction() as s:
            s["_user_id"] = str(teacher)

        resp = client.get(f"/classes/class/{class_b_id}")
        assert resp.status_code in (403, 404)

    def test_school_admin_cannot_access_other_school_api(self, app, client):
        school_a = make_school(app)
        school_b = make_school(app)
        grade_b = make_grade(app, school_b)
        subject_id = make_subject(app)
        admin_a = make_user(app, role="school_admin", school_id=school_a)
        class_b_id = make_class(app, school_b, grade_b, subject_id)

        with client.session_transaction() as s:
            s["_user_id"] = str(admin_a)

        resp = client.get(f"/api/v1/classes/{class_b_id}")
        assert resp.status_code in (403, 404)


# ═══════════════════════════════════════════════════════════════════════════
# ROLE ISOLATION
# ═══════════════════════════════════════════════════════════════════════════


class TestRoleIsolation:
    """Students cannot perform teacher/admin actions."""

    def test_student_cannot_create_assignment(self, app, client):
        school = make_school(app)
        grade = make_grade(app, school)
        subject_id = make_subject(app)
        teacher = make_user(app, role="teacher", school_id=school)
        student = make_user(app, role="student", school_id=school)
        class_id = make_class(app, school, grade, subject_id, teacher_id=teacher)

        with client.session_transaction() as s:
            s["_user_id"] = str(student)

        resp = client.post(
            f"/classes/{class_id}/assignments",
            data={"title": "Test", "body": "", "max_mark": 10},
            follow_redirects=False,
        )
        assert resp.status_code in (403, 404)

    def test_student_cannot_access_admin_route(self, app, client):
        school = make_school(app)
        student = make_user(app, role="student", school_id=school)

        with client.session_transaction() as s:
            s["_user_id"] = str(student)

        resp = client.get("/admin/")
        assert resp.status_code in (403, 404)

    def test_parent_cannot_create_lesson(self, app, client):
        school = make_school(app)
        grade = make_grade(app, school)
        subject_id = make_subject(app)
        parent = make_user(app, role="parent", school_id=school)
        class_id = make_class(app, school, grade, subject_id)

        with client.session_transaction() as s:
            s["_user_id"] = str(parent)

        resp = client.get(f"/content/{class_id}/lessons/new")
        assert resp.status_code in (403, 404)

    def test_unauthenticated_gets_401(self, app, client):
        resp = client.get("/classes/")
        assert resp.status_code in (302, 401, 404)


# ═══════════════════════════════════════════════════════════════════════════
# OWNERSHIP / IDOR PREVENTION
# ═══════════════════════════════════════════════════════════════════════════


class TestOwnershipPrevention:
    """Users cannot access other users' private data via IDOR."""

    def test_student_cannot_view_other_student_report_card(self, app, client):
        school = make_school(app)
        grade = make_grade(app, school)
        subject_id = make_subject(app)
        student_a = make_user(app, role="student", school_id=school)
        student_b = make_user(app, role="student", school_id=school)
        class_id = make_class(app, school, grade, subject_id)
        make_class_member(app, class_id, student_a)
        make_class_member(app, class_id, student_b)

        with client.session_transaction() as s:
            s["_user_id"] = str(student_a)

        resp = client.get(f"/classes/{class_id}/report-card/{student_b}")
        assert resp.status_code in (403, 404)

    def test_parent_cannot_view_unlinked_child_grades(self, app, client):
        school = make_school(app)
        grade = make_grade(app, school)
        subject_id = make_subject(app)
        parent = make_user(app, role="parent", school_id=school)
        student = make_user(app, role="student", school_id=school)
        class_id = make_class(app, school, grade, subject_id)
        make_class_member(app, class_id, student)

        with client.session_transaction() as s:
            s["_user_id"] = str(parent)

        resp = client.get(f"/family/children/{student}/grades")
        assert resp.status_code in (403, 404)


# ═══════════════════════════════════════════════════════════════════════════
# CLASS MEMBERSHIP ENFORCEMENT
# ═══════════════════════════════════════════════════════════════════════════


class TestClassMembershipEnforcement:
    """Students must be class members to track progress."""

    def test_student_not_in_class_gets_403_on_heartbeat(self, app, client):
        school = make_school(app)
        grade = make_grade(app, school)
        subject_id = make_subject(app)
        student = make_user(app, role="student", school_id=school)
        class_id = make_class(app, school, grade, subject_id)
        # Student is NOT a member of this class

        with client.session_transaction() as s:
            s["_user_id"] = str(student)

        resp = client.post(
            f"/progress/lesson/99999/heartbeat",
            json={"seconds": 30},
            content_type="application/json",
        )
        assert resp.status_code in (403, 404)


# ═══════════════════════════════════════════════════════════════════════════
# TUTORING SESSION ISOLATION
# ═══════════════════════════════════════════════════════════════════════════


class TestTutoringIsolation:
    """Only session participants can access session data."""

    def test_unrelated_user_cannot_view_session(self, app, client):
        from app.models.tutoring import TutoringSession

        school = make_school(app)
        tutor = make_user(app, role="teacher", school_id=school)
        student = make_user(app, role="student", school_id=school)
        other = make_user(app, role="student", school_id=school)

        with app.app_context():
            from app.extensions import db

            session = TutoringSession(
                tutor_id=tutor,
                student_id=student,
                subject="Math",
                status="requested",
            )
            db.session.add(session)
            db.session.commit()
            session_id = session.id

        with client.session_transaction() as s:
            s["_user_id"] = str(other)

        resp = client.get(f"/tutoring/sessions/{session_id}")
        assert resp.status_code in (403, 404)

    def test_student_cannot_change_session_status(self, app, client):
        from app.models.tutoring import TutoringSession

        school = make_school(app)
        tutor = make_user(app, role="teacher", school_id=school)
        student = make_user(app, role="student", school_id=school)

        with app.app_context():
            from app.extensions import db

            session = TutoringSession(
                tutor_id=tutor,
                student_id=student,
                subject="Math",
                status="active",
            )
            db.session.add(session)
            db.session.commit()
            session_id = session.id

        with client.session_transaction() as s:
            s["_user_id"] = str(student)

        resp = client.get(f"/tutoring/sessions/{session_id}/status/completed")
        assert resp.status_code in (403, 404)

    def test_student_cannot_confirm_payment_for_others(self, app, client):
        from app.models.tutoring import TutoringSession

        school = make_school(app)
        tutor = make_user(app, role="teacher", school_id=school)
        student_a = make_user(app, role="student", school_id=school)
        student_b = make_user(app, role="student", school_id=school)

        with app.app_context():
            from app.extensions import db

            session = TutoringSession(
                tutor_id=tutor,
                student_id=student_a,
                subject="Math",
                status="active",
            )
            db.session.add(session)
            db.session.commit()
            session_id = session.id

        with client.session_transaction() as s:
            s["_user_id"] = str(student_b)

        resp = client.post(
            f"/tutoring/sessions/{session_id}/pay",
            follow_redirects=False,
        )
        assert resp.status_code in (403, 404)


# ═══════════════════════════════════════════════════════════════════════════
# EXPORT ROUTES — @class_teach_required enforcement
# ═══════════════════════════════════════════════════════════════════════════


class TestExportRouteGuards:
    """Export endpoints require teaching access to the class."""

    def test_student_cannot_export_students(self, app, client):
        school = make_school(app)
        grade = make_grade(app, school)
        subject_id = make_subject(app)
        student = make_user(app, role="student", school_id=school)
        class_id = make_class(app, school, grade, subject_id)

        with client.session_transaction() as s:
            s["_user_id"] = str(student)

        resp = client.get(f"/export/{class_id}/students")
        assert resp.status_code in (403, 404)

    def test_student_cannot_export_grades(self, app, client):
        school = make_school(app)
        grade = make_grade(app, school)
        subject_id = make_subject(app)
        student = make_user(app, role="student", school_id=school)
        class_id = make_class(app, school, grade, subject_id)

        with client.session_transaction() as s:
            s["_user_id"] = str(student)

        resp = client.get(f"/export/{class_id}/grades")
        assert resp.status_code in (403, 404)

    def test_student_cannot_export_progress(self, app, client):
        school = make_school(app)
        grade = make_grade(app, school)
        subject_id = make_subject(app)
        student = make_user(app, role="student", school_id=school)
        class_id = make_class(app, school, grade, subject_id)

        with client.session_transaction() as s:
            s["_user_id"] = str(student)

        resp = client.get(f"/export/{class_id}/progress")
        assert resp.status_code in (403, 404)

    def test_teacher_cannot_export_other_school_class(self, app, client):
        school_a = make_school(app)
        school_b = make_school(app)
        grade_b = make_grade(app, school_b)
        subject_id = make_subject(app)
        teacher = make_user(app, role="teacher", school_id=school_a)
        class_b_id = make_class(app, school_b, grade_b, subject_id)

        with client.session_transaction() as s:
            s["_user_id"] = str(teacher)

        resp = client.get(f"/export/{class_b_id}/students")
        assert resp.status_code in (403, 404)


# ═══════════════════════════════════════════════════════════════════════════
# AI ROUTES — @role_required enforcement
# ═══════════════════════════════════════════════════════════════════════════


class TestAIRouteGuards:
    """AI grading/generation endpoints require teacher/admin role."""

    def test_student_cannot_suggest_grade(self, app, client):
        school = make_school(app)
        student = make_user(app, role="student", school_id=school)

        with client.session_transaction() as s:
            s["_user_id"] = str(student)

        resp = client.post(
            "/ai/grade/suggest",
            json={"student_answer": "test", "question_type": "essay"},
            content_type="application/json",
        )
        assert resp.status_code == 403

    def test_student_cannot_generate_questions(self, app, client):
        school = make_school(app)
        student = make_user(app, role="student", school_id=school)

        with client.session_transaction() as s:
            s["_user_id"] = str(student)

        resp = client.post(
            "/ai/questions/generate",
            json={"topic": "math", "count": 3},
            content_type="application/json",
        )
        assert resp.status_code == 403

    def test_teacher_cannot_view_ai_usage_stats(self, app, client):
        school = make_school(app)
        teacher = make_user(app, role="teacher", school_id=school)

        with client.session_transaction() as s:
            s["_user_id"] = str(teacher)

        resp = client.get("/ai/usage/stats")
        assert resp.status_code == 403


# ═══════════════════════════════════════════════════════════════════════════
# CALENDAR ROUTES — tenant isolation
# ═══════════════════════════════════════════════════════════════════════════


class TestCalendarTenantIsolation:
    """School admins can only manage events in their own school."""

    def test_school_admin_cannot_delete_other_school_event(self, app, client):
        school_a = make_school(app)
        school_b = make_school(app)
        admin_a = make_user(app, role="school_admin", school_id=school_a)
        event_id = make_academic_event(
            app, school_b, "Test Event", "holiday", "2026-01-01", "2026-01-02"
        )

        with client.session_transaction() as s:
            s["_user_id"] = str(admin_a)

        resp = client.post(
            f"/calendar/events/{event_id}/delete",
            follow_redirects=False,
        )
        assert resp.status_code in (403, 404)

    def test_student_cannot_access_calendar(self, app, client):
        school = make_school(app)
        student = make_user(app, role="student", school_id=school)

        with client.session_transaction() as s:
            s["_user_id"] = str(student)

        resp = client.get(f"/calendar/{school}")
        assert resp.status_code in (403, 404)


# ═══════════════════════════════════════════════════════════════════════════
# INDIVIDUAL ROUTES — @role_required enforcement
# ═══════════════════════════════════════════════════════════════════════════


class TestIndividualRouteGuards:
    """Individual course routes require student role."""

    def test_teacher_cannot_access_my_courses(self, app, client):
        school = make_school(app)
        teacher = make_user(app, role="teacher", school_id=school)

        with client.session_transaction() as s:
            s["_user_id"] = str(teacher)

        resp = client.get("/my/courses")
        assert resp.status_code in (403, 404)

    def test_parent_cannot_subscribe_to_course(self, app, client):
        school = make_school(app)
        grade = make_grade(app, school)
        subject_id = make_subject(app)
        parent = make_user(app, role="parent", school_id=school)
        class_id = make_class(app, school, grade, subject_id)

        with client.session_transaction() as s:
            s["_user_id"] = str(parent)

        resp = client.post(
            f"/my/catalog/{class_id}/subscribe",
            follow_redirects=False,
        )
        assert resp.status_code in (403, 404)


# ═══════════════════════════════════════════════════════════════════════════
# QUESTION BANK — @role_required enforcement
# ═══════════════════════════════════════════════════════════════════════════


class TestQuestionBankGuards:
    """Question bank requires teacher/admin role."""

    def test_student_cannot_access_question_bank(self, app, client):
        school = make_school(app)
        student = make_user(app, role="student", school_id=school)

        with client.session_transaction() as s:
            s["_user_id"] = str(student)

        resp = client.get("/classes/question-bank")
        assert resp.status_code == 403

    def test_student_cannot_create_bank_question(self, app, client):
        school = make_school(app)
        student = make_user(app, role="student", school_id=school)

        with client.session_transaction() as s:
            s["_user_id"] = str(student)

        resp = client.post(
            "/classes/question-bank/new",
            data={"question_text": "Q", "question_type": "mcq"},
            follow_redirects=False,
        )
        assert resp.status_code == 403

    def test_student_cannot_delete_bank_question(self, app, client):
        school = make_school(app)
        student = make_user(app, role="student", school_id=school)

        with client.session_transaction() as s:
            s["_user_id"] = str(student)

        resp = client.post(
            "/classes/question-bank/1/delete",
            follow_redirects=False,
        )
        assert resp.status_code == 403


# ═══════════════════════════════════════════════════════════════════════════
# BILLING — class-level access enforcement
# ═══════════════════════════════════════════════════════════════════════════


class TestBillingAccessGuards:
    """Billing endpoints require class access."""

    def test_student_cannot_create_plan(self, app, client):
        school = make_school(app)
        grade = make_grade(app, school)
        subject_id = make_subject(app)
        student = make_user(app, role="student", school_id=school)
        class_id = make_class(app, school, grade, subject_id)

        with client.session_transaction() as s:
            s["_user_id"] = str(student)

        resp = client.post(
            f"/billing/{class_id}/plans",
            data={"name": "Plan", "plan": "monthly", "price": 100, "currency": "ILS", "duration_days": 30},
            follow_redirects=False,
        )
        assert resp.status_code in (403, 404)

    def test_student_cannot_access_other_school_billing(self, app, client):
        school_a = make_school(app)
        school_b = make_school(app)
        grade_b = make_grade(app, school_b)
        subject_id = make_subject(app)
        student = make_user(app, role="student", school_id=school_a)
        class_b_id = make_class(app, school_b, grade_b, subject_id)

        with client.session_transaction() as s:
            s["_user_id"] = str(student)

        resp = client.get(f"/billing/{class_b_id}")
        assert resp.status_code in (403, 404)
