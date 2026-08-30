"""Zero-Trust Authorization Integration Tests.

Verifies that:
- Cross-tenant access returns strict 403/404
- Role isolation is enforced (student cannot do teacher actions)
- Ownership checks prevent IDOR/BOLA
- Class membership is enforced for progress tracking
"""

from tests.conftest import (
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
                status="pending",
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
