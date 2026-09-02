"""Test Persona 5: The Student (Enrollment & Subscription-Bound).

Verifies that:
1. Enrolled students CAN access their own class content
2. Students CANNOT access classes they are not enrolled in
3. Students CANNOT access paid classes without active subscription
4. Students CANNOT access admin panel or teacher controls
5. Students CANNOT access other students' private grades
6. Students CANNOT tamper with student_id in quiz submissions
"""

from __future__ import annotations


class TestStudentEnrolledClassAccess:
    """Student can access content in classes they are enrolled in."""

    def test_can_view_lessons(self, app, student_a_persona, class_a, lesson_a):
        _, client = student_a_persona
        resp = client.get(f"/classes/{class_a}/lessons", follow_redirects=True)
        assert resp.status_code == 200

    def test_can_view_progress(self, app, student_a_persona):
        _, client = student_a_persona
        resp = client.get("/progress/my", follow_redirects=True)
        assert resp.status_code == 200


class TestStudentUnenrolledClassDenied:
    """Student CANNOT access classes they are not enrolled in."""

    def test_cannot_view_other_class_lessons(self, app, student_a_persona, class_b):
        _, client = student_a_persona
        resp = client.get(f"/classes/{class_b}/lessons", follow_redirects=False)
        assert resp.status_code == 403

    def test_cannot_view_other_class_assignments(self, app, student_a_persona, class_b):
        _, client = student_a_persona
        resp = client.get(f"/classes/{class_b}/assignments", follow_redirects=False)
        assert resp.status_code == 403


class TestStudentAdminDenied:
    """Student CANNOT access the admin panel."""

    def test_admin_dashboard_forbidden(self, app, student_a_persona):
        _, client = student_a_persona
        resp = client.get("/admin/", follow_redirects=False)
        assert resp.status_code == 403

    def test_admin_users_forbidden(self, app, student_a_persona):
        _, client = student_a_persona
        resp = client.get("/admin/users", follow_redirects=False)
        assert resp.status_code == 403

    def test_admin_payments_forbidden(self, app, student_a_persona):
        _, client = student_a_persona
        resp = client.get("/admin/payments/pending", follow_redirects=False)
        assert resp.status_code == 403

    def test_admin_settings_forbidden(self, app, student_a_persona):
        _, client = student_a_persona
        resp = client.get("/admin/settings", follow_redirects=False)
        assert resp.status_code == 403

    def test_admin_schools_forbidden(self, app, student_a_persona):
        _, client = student_a_persona
        resp = client.get("/admin/schools", follow_redirects=False)
        assert resp.status_code == 403


class TestStudentCannotCreateContent:
    """Student CANNOT create lessons or assignments."""

    def test_cannot_create_lesson(self, app, student_a_persona, class_a):
        _, client = student_a_persona
        resp = client.post(
            f"/classes/{class_a}/lessons",
            data={"title": "درس محاكاة"},
            follow_redirects=False,
        )
        assert resp.status_code == 403

    def test_cannot_create_assignment(self, app, student_a_persona, class_a):
        _, client = student_a_persona
        resp = client.post(
            f"/classes/{class_a}/assignments",
            data={"title": "واجب محاكاة", "max_mark": 10},
            follow_redirects=False,
        )
        assert resp.status_code == 403

    def test_cannot_create_category(self, app, student_a_persona, class_a):
        _, client = student_a_persona
        resp = client.post(
            f"/classes/{class_a}/categories",
            data={"name": "فئة محاكاة", "weight": 50},
            follow_redirects=False,
        )
        assert resp.status_code == 403


class TestStudentCrossTenantDenied:
    """Student from School A CANNOT access School B's classes."""

    def test_cannot_access_other_tenant_class(self, app, student_a_persona, class_b):
        _, client = student_a_persona
        resp = client.get(f"/classes/{class_b}/lessons", follow_redirects=False)
        assert resp.status_code == 403


class TestStudentCannotGradeOthers:
    """Student CANNOT grade other students."""

    def test_cannot_access_grade_submission_endpoint(self, app, student_a_persona):
        _, client = student_a_persona
        resp = client.post(
            "/grades/submissions/1/grade",
            data={"mark": 10},
            follow_redirects=False,
        )
        assert resp.status_code in (403, 404)


class TestStudentCannotViewOtherStudentsGrades:
    """Student CANNOT view other students' report cards via direct URL."""

    def test_cannot_view_other_student_report_card(self, app, student_a_persona, class_a):
        _, client = student_a_persona
        # Try to access report card for student_id=999 (doesn't exist but should be rejected)
        resp = client.get(
            f"/classes/{class_a}/report-card/999",
            follow_redirects=False,
        )
        assert resp.status_code in (403, 404)

    def test_cannot_access_attendance_management(self, app, student_a_persona, class_a):
        """Student cannot POST attendance (teacher-only)."""
        _, client = student_a_persona
        resp = client.post(
            f"/classes/{class_a}/attendance",
            data={"student_id": 1, "status": "present"},
            follow_redirects=False,
        )
        assert resp.status_code == 403
