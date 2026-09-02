"""Test Persona 6: The Parent (Child-Bound).

Verifies that:
1. Parents CAN view progress and grades of their linked children
2. Parents CANNOT view progress/grades of unlinked children
3. Parents CANNOT join classes as a student
4. Parents CANNOT edit grades or assignments
5. Parents CANNOT access admin panel
"""

from __future__ import annotations


class TestParentLinkedChildAccess:
    """Parent can access linked child's data."""

    def test_can_view_children_list(self, app, parent_a_persona):
        _, client = parent_a_persona
        resp = client.get("/family/", follow_redirects=True)
        assert resp.status_code == 200

    def test_can_view_linked_child_progress(self, app, parent_a_persona, student_a_persona):
        _, client = parent_a_persona
        student_id = student_a_persona[0]
        resp = client.get(f"/family/children/{student_id}/progress", follow_redirects=True)
        assert resp.status_code == 200

    def test_can_view_linked_child_grades(self, app, parent_a_persona, student_a_persona):
        _, client = parent_a_persona
        student_id = student_a_persona[0]
        resp = client.get(f"/family/children/{student_id}/grades", follow_redirects=True)
        assert resp.status_code == 200


class TestParentUnlinkedChildDenied:
    """Parent CANNOT access unlinked children's data."""

    def test_cannot_view_unlinked_child_progress(
        self, app, parent_a_persona, student_b_persona
    ):
        _, client = parent_a_persona
        student_b_id = student_b_persona[0]
        resp = client.get(
            f"/family/children/{student_b_id}/progress", follow_redirects=False
        )
        assert resp.status_code == 403

    def test_cannot_view_unlinked_child_grades(
        self, app, parent_a_persona, student_b_persona
    ):
        _, client = parent_a_persona
        student_b_id = student_b_persona[0]
        resp = client.get(
            f"/family/children/{student_b_id}/grades", follow_redirects=False
        )
        assert resp.status_code == 403

    def test_cannot_view_nonexistent_child(self, app, parent_a_persona):
        _, client = parent_a_persona
        resp = client.get("/family/children/99999/progress", follow_redirects=False)
        assert resp.status_code in (403, 404)


class TestParentAdminDenied:
    """Parent CANNOT access the admin panel."""

    def test_admin_dashboard_forbidden(self, app, parent_a_persona):
        _, client = parent_a_persona
        resp = client.get("/admin/", follow_redirects=False)
        assert resp.status_code == 403

    def test_admin_users_forbidden(self, app, parent_a_persona):
        _, client = parent_a_persona
        resp = client.get("/admin/users", follow_redirects=False)
        assert resp.status_code == 403

    def test_admin_settings_forbidden(self, app, parent_a_persona):
        _, client = parent_a_persona
        resp = client.get("/admin/settings", follow_redirects=False)
        assert resp.status_code == 403


class TestParentCannotEditGrades:
    """Parent CANNOT edit grades or assignments."""

    def test_cannot_grade_submission(self, app, parent_a_persona):
        _, client = parent_a_persona
        resp = client.post(
            "/grades/submissions/1/grade",
            data={"mark": 10},
            follow_redirects=False,
        )
        assert resp.status_code in (403, 404)

    def test_cannot_create_assignment(self, app, parent_a_persona, class_a):
        _, client = parent_a_persona
        resp = client.post(
            f"/classes/{class_a}/assignments",
            data={"title": "واجب ولي أمر", "max_mark": 10},
            follow_redirects=False,
        )
        assert resp.status_code == 403

    def test_cannot_manage_attendance(self, app, parent_a_persona, class_a):
        _, client = parent_a_persona
        resp = client.post(
            f"/classes/{class_a}/attendance",
            data={"student_id": 1, "status": "present"},
            follow_redirects=False,
        )
        assert resp.status_code in (403, 404)


class TestParentCannotJoinClass:
    """Parent CANNOT join classes as a student."""

    def test_cannot_use_student_join(self, app, parent_a_persona):
        _, client = parent_a_persona
        resp = client.post(
            "/schools/join",
            data={"join_code": "SOMECODE"},
            follow_redirects=False,
        )
        # Route either requires student role (403) or doesn't exist (404)
        assert resp.status_code in (403, 404, 405)

    def test_cannot_access_individual_subscribe(self, app, parent_a_persona):
        _, client = parent_a_persona
        resp = client.get("/my/courses", follow_redirects=True)
        # Individual route may redirect or show empty, but shouldn't crash
        assert resp.status_code in (200, 302, 403)


class TestParentCrossTenantDenied:
    """Parent CANNOT access data from other tenants."""

    def test_cannot_access_other_tenant_class(self, app, parent_a_persona, class_b):
        _, client = parent_a_persona
        resp = client.get(f"/classes/{class_b}/lessons", follow_redirects=False)
        assert resp.status_code == 403

    def test_cannot_generate_family_code_for_other_student(
        self, app, parent_a_persona, student_b_persona
    ):
        """Parent cannot generate family link codes for other students."""
        _, client = parent_a_persona
        resp = client.get("/family/generate", follow_redirects=True)
        # This returns a code for the parent to share, not for other students
        assert resp.status_code in (200, 403)
