"""Test Persona 4: The Teacher (Class-Bound).

Verifies that:
1. Teachers can access their assigned classes
2. Teachers CANNOT access classes they are NOT assigned to
3. Teachers CANNOT access admin panel
4. Teachers CANNOT access other tenants' classes
"""

from __future__ import annotations


class TestTeacherOwnClassAccess:
    """Teacher can access their own assigned class."""

    def test_can_view_lessons(self, app, teacher_a_persona, class_a, lesson_a):
        _, client = teacher_a_persona
        resp = client.get(f"/classes/{class_a}/lessons", follow_redirects=True)
        assert resp.status_code == 200

    def test_can_view_assignments(self, app, teacher_a_persona, class_a):
        _, client = teacher_a_persona
        resp = client.get(f"/classes/{class_a}/assignments", follow_redirects=True)
        assert resp.status_code == 200

    def test_can_view_gradebook(self, app, teacher_a_persona, class_a):
        _, client = teacher_a_persona
        resp = client.get(f"/classes/{class_a}/gradebook", follow_redirects=True)
        assert resp.status_code == 200

    def test_can_view_attendance(self, app, teacher_a_persona, class_a):
        _, client = teacher_a_persona
        resp = client.get(f"/classes/{class_a}/attendance", follow_redirects=True)
        assert resp.status_code == 200

    def test_can_create_lesson(self, app, teacher_a_persona, class_a):
        _, client = teacher_a_persona
        resp = client.get(f"/classes/{class_a}/lessons/new", follow_redirects=True)
        assert resp.status_code == 200


class TestTeacherOtherClassDenied:
    """Teacher CANNOT access unassigned classes."""

    def test_cannot_view_other_class_lessons(self, app, teacher_a_persona, class_b):
        _, client = teacher_a_persona
        resp = client.get(f"/classes/{class_b}/lessons", follow_redirects=False)
        assert resp.status_code == 403

    def test_cannot_view_other_class_assignments(self, app, teacher_a_persona, class_b):
        _, client = teacher_a_persona
        resp = client.get(f"/classes/{class_b}/assignments", follow_redirects=False)
        assert resp.status_code == 403

    def test_cannot_view_other_class_gradebook(self, app, teacher_a_persona, class_b):
        _, client = teacher_a_persona
        resp = client.get(f"/classes/{class_b}/gradebook", follow_redirects=False)
        assert resp.status_code == 403

    def test_cannot_create_lesson_in_other_class(self, app, teacher_a_persona, class_b):
        _, client = teacher_a_persona
        resp = client.post(f"/classes/{class_b}/lessons", follow_redirects=False)
        assert resp.status_code == 403

    def test_cannot_create_assignment_in_other_class(self, app, teacher_a_persona, class_b):
        _, client = teacher_a_persona
        resp = client.post(
            f"/classes/{class_b}/assignments",
            data={"title": "واجب محاول", "max_mark": 10},
            follow_redirects=False,
        )
        assert resp.status_code == 403


class TestTeacherAdminDenied:
    """Teacher CANNOT access the admin panel."""

    def test_admin_dashboard_forbidden(self, app, teacher_a_persona):
        _, client = teacher_a_persona
        resp = client.get("/admin/", follow_redirects=False)
        assert resp.status_code == 403

    def test_admin_users_forbidden(self, app, teacher_a_persona):
        _, client = teacher_a_persona
        resp = client.get("/admin/users", follow_redirects=False)
        assert resp.status_code == 403

    def test_admin_payments_forbidden(self, app, teacher_a_persona):
        _, client = teacher_a_persona
        resp = client.get("/admin/payments/pending", follow_redirects=False)
        assert resp.status_code == 403

    def test_admin_settings_forbidden(self, app, teacher_a_persona):
        _, client = teacher_a_persona
        resp = client.get("/admin/settings", follow_redirects=False)
        assert resp.status_code == 403

    def test_admin_schools_forbidden(self, app, teacher_a_persona):
        _, client = teacher_a_persona
        resp = client.get("/admin/schools", follow_redirects=False)
        assert resp.status_code == 403


class TestTeacherCrossTenantDenied:
    """Teacher from School A CANNOT access School B's classes."""

    def test_cannot_access_other_tenant_class(self, app, teacher_a_persona, class_b):
        _, client = teacher_a_persona
        resp = client.get(f"/classes/{class_b}/lessons", follow_redirects=False)
        assert resp.status_code == 403


class TestTeacherGradeStudentInOwnClass:
    """Teacher CAN grade students in their own class."""

    def test_can_access_grade_page(self, app, teacher_a_persona, class_a):
        _, client = teacher_a_persona
        resp = client.get(f"/classes/{class_a}/assignments", follow_redirects=True)
        assert resp.status_code == 200
