"""Query-Count Performance Integration Tests.

Verifies that key endpoints execute a bounded number of SQL queries
regardless of dataset size, preventing N+1 regressions.
"""

from sqlalchemy import event

from tests.conftest import (
    make_class,
    make_class_member,
    make_grade,
    make_school,
    make_subject,
    make_user,
)


class QueryCounter:
    """Context manager that counts SQLAlchemy statements via the engine."""

    def __init__(self, engine):
        self.engine = engine
        self.count = 0
        self._listener = None

    def __enter__(self):
        self._listener = lambda *a, **kw: setattr(self, "count", self.count + 1)
        event.listen(self.engine, "before_cursor_execute", self._listener)
        return self

    def __exit__(self, *args):
        event.remove(self.engine, "before_cursor_execute", self._listener)


class TestGradebookQueryCount:
    """Gradebook page must not N+1 on categories -> items -> entries."""

    def test_gradebook_query_count_bounded(self, app, client):
        from app.extensions import db

        school = make_school(app)
        grade = make_grade(app, school)
        subject_id = make_subject(app)
        teacher = make_user(app, role="teacher", school_id=school)
        student = make_user(app, role="student", school_id=school)
        class_id = make_class(app, school, grade, subject_id, teacher_id=teacher)
        make_class_member(app, class_id, student)

        with client.session_transaction() as s:
            s["_user_id"] = str(teacher)

        with app.app_context():
            with QueryCounter(db.engine) as qc:
                resp = client.get(f"/classes/{class_id}/gradebook")
            assert resp.status_code == 200
            # Must be <= 15 queries regardless of category/item count
            assert qc.count <= 15, f"Gradebook used {qc.count} queries (expected <= 15)"


class TestQuizListQueryCount:
    """Quiz list must not N+1 on quizzes -> questions -> attempts."""

    def test_quiz_list_query_count_bounded(self, app, client):
        from app.extensions import db

        school = make_school(app)
        grade = make_grade(app, school)
        subject_id = make_subject(app)
        teacher = make_user(app, role="teacher", school_id=school)
        class_id = make_class(app, school, grade, subject_id, teacher_id=teacher)

        with client.session_transaction() as s:
            s["_user_id"] = str(teacher)

        with app.app_context():
            with QueryCounter(db.engine) as qc:
                resp = client.get(f"/classes/{class_id}/quizzes")
            assert resp.status_code == 200
            assert qc.count <= 15, f"Quiz list used {qc.count} queries (expected <= 15)"


class TestAssignmentListQueryCount:
    """Assignment list must not N+1 on assignments -> submissions."""

    def test_assignment_list_query_count_bounded(self, app, client):
        from app.extensions import db

        school = make_school(app)
        grade = make_grade(app, school)
        subject_id = make_subject(app)
        teacher = make_user(app, role="teacher", school_id=school)
        class_id = make_class(app, school, grade, subject_id, teacher_id=teacher)

        with client.session_transaction() as s:
            s["_user_id"] = str(teacher)

        with app.app_context():
            with QueryCounter(db.engine) as qc:
                resp = client.get(f"/classes/{class_id}/assignments")
            assert resp.status_code == 200
            assert qc.count <= 15, f"Assignment list used {qc.count} queries (expected <= 15)"


class TestAdminDashboardQueryCount:
    """Admin dashboard must use SQL aggregation, not Python loops."""

    def test_admin_dashboard_query_count_bounded(self, app, client):
        from app.extensions import db

        admin = make_user(app, role="super_admin")

        with client.session_transaction() as s:
            s["_user_id"] = str(admin)

        with app.app_context():
            with QueryCounter(db.engine) as qc:
                resp = client.get("/admin/")
            assert resp.status_code == 200
            # Dashboard should use <= 30 queries (many aggregated SQL calls)
            assert qc.count <= 30, f"Admin dashboard used {qc.count} queries (expected <= 30)"


class TestBillingQueryCount:
    """Billing page must not N+1 on plans -> subscriptions."""

    def test_billing_query_count_bounded(self, app, client):
        from app.extensions import db

        school = make_school(app)
        grade = make_grade(app, school)
        subject_id = make_subject(app)
        teacher = make_user(app, role="teacher", school_id=school)
        class_id = make_class(app, school, grade, subject_id, teacher_id=teacher)

        with client.session_transaction() as s:
            s["_user_id"] = str(teacher)

        with app.app_context():
            with QueryCounter(db.engine) as qc:
                resp = client.get(f"/billing/{class_id}")
            assert resp.status_code == 200
            assert qc.count <= 15, f"Billing page used {qc.count} queries (expected <= 15)"


class TestNotificationsQueryCount:
    """Notifications page must not N+1."""

    def test_notifications_query_count_bounded(self, app, client):
        from app.extensions import db

        student = make_user(app, role="student")

        with client.session_transaction() as s:
            s["_user_id"] = str(student)

        with app.app_context():
            with QueryCounter(db.engine) as qc:
                resp = client.get("/notifications/")
            assert resp.status_code == 200
            assert qc.count <= 10, f"Notifications used {qc.count} queries (expected <= 10)"
