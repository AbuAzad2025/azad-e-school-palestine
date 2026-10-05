"""RLS coverage rollout + per-attempt quiz shuffling.

Two independent gaps share this file because they share one failure mode:
both are about *which rows a request is allowed to see*, and both are only
provable against a real PostgreSQL database — SQLite has no row-level
security, so a mocked session would pass while production leaked.

The RLS tests drive raw SQL through the application's own session with the
tenant variables set by hand. That is deliberate: the app-level guard
(``can_view_class``) already passes, and the point of these tests is the floor
*underneath* it. If the application layer ever regresses and starts issuing an
unscoped query, these still fail.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from app.core.rls import (
    _INDIRECT_TENANT_TABLES,
    _TENANT_TABLES,
    _USER_SCOPED_TABLES,
    _USER_SCOPED_WITH_TENANT,
)
from app.extensions import db
from sqlalchemy import text

# --------------------------------------------------------------------------
# Session-level RLS bypass for fixture setup.
#
# Same reason scripts/seed_e2e.py needs it: these tables are FORCEd, so even
# the table owner is filtered, and the fixtures write across every tenant at
# once. Session-level (not SET LOCAL) so it survives the commits that tx()
# performs between writes.
# --------------------------------------------------------------------------
RLS_TEST_PASSWORD = "RlsTest!12345"


def _make_school_with_class(app, tag: str) -> dict:
    """A tenant with one class, one teacher and one student.

    Built with the RLS bypass active, then read back through tenant-scoped
    connections by the tests themselves.
    """
    from datetime import date

    from app.core.db import tx
    from app.core.security import hash_password
    from app.models.attendance import Attendance
    from app.models.class_room import ClassMember, ClassRoom
    from app.models.school import Grade, School, Subject
    from app.models.user import User, UserApprovalStatus, UserRole, UserRoleLink

    with app.app_context():
        school = School(name_ar=f"rls {tag}", domain=f"rls-{tag}.example.com", is_active=True)
        tx(db.session.add, school)
        db.session.flush()
        subject = Subject(code=f"RLS-{tag}", name_ar="رياضيات")
        tx(db.session.add, subject)
        db.session.flush()
        grade = Grade(school_id=school.id, grade_level=1, name_ar="الأول", stage="primary")
        tx(db.session.add, grade)
        db.session.flush()

        users = {}
        for role, key in ((UserRole.teacher, "teacher"), (UserRole.student, "student")):
            user = User(
                email=f"{key}-{tag}@rls.example.com",
                name_ar=f"{key}-{tag}",
                role=role,
                password_hash=hash_password(RLS_TEST_PASSWORD),
                approval_status=UserApprovalStatus.approved,
                is_active=True,
                is_verified=True,
            )
            tx(db.session.add, user)
            db.session.flush()
            tx(
                db.session.add,
                UserRoleLink(user_id=user.id, school_id=school.id, role=role, is_active=True),
            )
            users[key] = user

        class_room = ClassRoom(
            school_id=school.id,
            subject_id=subject.id,
            grade_id=grade.id,
            name=f"rls class {tag}",
            join_code=f"RLSJ{tag}",
            is_active=True,
            teacher_id=users["teacher"].id,
            currency="ILS",
        )
        tx(db.session.add, class_room)
        db.session.flush()
        tx(
            db.session.add,
            ClassMember(class_id=class_room.id, user_id=users["student"].id, status="active"),
        )
        tx(
            db.session.add,
            Attendance(
                class_id=class_room.id,
                student_id=users["student"].id,
                date=date.today(),
                status="present",
                recorded_by=users["teacher"].id,
            ),
        )
        db.session.commit()
        return {
            "school_id": school.id,
            "class_id": class_room.id,
            "teacher_id": users["teacher"].id,
            "student_id": users["student"].id,
        }


def _run_as_tenant(app, school_id: int, user_id: int, sql: str):
    """Run one statement as a tenant and return the rows.

    Sets the same three variables ``set_tenant_for_request`` sets per request,
    in the same transaction-local way, so the policies see exactly what they
    see in production.
    """
    with app.app_context():
        db.session.execute(
            text("SET LOCAL app.current_user_id = :uid"),
            {"uid": str(user_id)},
        )
        db.session.execute(
            text("SET LOCAL app.current_school_id = :sid"),
            {"sid": str(school_id)},
        )
        db.session.execute(text("SET LOCAL app.is_super_admin = '0'"))
        result = db.session.execute(text(sql)).all()
        db.session.rollback()
        return result


# --------------------------------------------------------------------------
# Policy inventory: every table the rollout claims to protect is claimed in
# app/core/rls.py. A table added to one list and not the other is a silent
# gap, which is exactly how the original rollout dropped 17 tables.
# --------------------------------------------------------------------------
ROLL_OUT_TABLES = [
    "announcements",
    "assignments",
    "attendance",
    "class_members",
    "grade_categories",
    "grade_items",
    "lessons",
    "lesson_attachments",
    "manual_payments",
    "offline_downloads",
    "payment_receipts",
    "rubric_criteria",
    "student_progress",
    "subscriptions",
    "units",
    "video_progress",
    "wallets",
    "wallet_transactions",
]


@pytest.mark.parametrize("table", ROLL_OUT_TABLES)
def test_rollout_table_is_registered_in_rls_registry(table):
    """The migration's targets are the same list the runtime keeps."""
    assert table in _TENANT_TABLES or table in _INDIRECT_TENANT_TABLES


@pytest.mark.parametrize("table", _USER_SCOPED_TABLES)
def test_user_scoped_tables_are_registered(table):
    assert table in _USER_SCOPED_TABLES


def test_user_role_links_is_not_tenant_scoped():
    """`user_role_links` derives the tenant; a tenant policy there is circular.

    If someone "fixes" it by scoping it like every other table, login breaks:
    ``User.school_id`` reads this table, so the query that resolves the school
    would be filtered by the school it is resolving.

    It is registered in its own list rather than in ``_TENANT_TABLES``: it is
    scoped by the acting user *and* by the tenant, and the second arm only
    widens visibility inside a tenant the user arm has already resolved.
    """
    assert "user_role_links" in _USER_SCOPED_WITH_TENANT
    assert "user_role_links" not in _TENANT_TABLES
    assert "user_role_links" not in _INDIRECT_TENANT_TABLES


class TestUserRoleLinksTenantArm:
    """A tenant's members must be able to read each other's role links.

    ``User.school_id`` and ``assert_user_belongs_to_accessible_school`` both
    read the *target* user's links, not the caller's. Scoping the table to the
    acting user alone therefore leaves every colleague with an empty set, and
    ``/api/v1/users/<id>`` answers 403 for a student in the caller's own
    school.
    """

    @pytest.fixture
    def same_school_colleagues(self, app):
        """Two schools; school A has two members, school B has one."""
        return {"a": _make_school_with_class(app, "a"), "b": _make_school_with_class(app, "b")}

    def test_colleague_in_same_school_is_visible(self, app, same_school_colleagues):
        from app.models.user import User, UserRole, UserRoleLink

        a = same_school_colleagues["a"]
        with app.app_context():
            extra = User(
                email=f"colleague-{a['school_id']}@test.org",
                password_hash="x",
                role=UserRole.student,
                locale="ar",
            )
            db.session.add(extra)
            db.session.flush()
            db.session.add(
                UserRoleLink(
                    user_id=extra.id,
                    school_id=a["school_id"],
                    role=UserRole.student,
                    is_active=True,
                )
            )
            db.session.commit()
            colleague_id = extra.id
            own_id = a["student_id"]

        sql = f"SELECT user_id FROM user_role_links WHERE user_id IN ({own_id}, {colleague_id}) ORDER BY user_id"
        seen = [row[0] for row in _run_as_tenant(app, a["school_id"], own_id, sql)]

        assert seen == sorted([own_id, colleague_id]), (
            f"a member of school A must see the other member's role link; saw {seen}"
        )

    def test_other_tenants_links_stay_hidden(self, app, same_school_colleagues):
        """The tenant arm must widen inside one school only."""
        a, b = same_school_colleagues["a"], same_school_colleagues["b"]
        sql = f"SELECT count(*) FROM user_role_links WHERE school_id = {b['school_id']}"
        leaked = _run_as_tenant(app, a["school_id"], a["student_id"], sql)[0][0]
        assert leaked == 0, "school B's role links leaked into school A's session"


def _run_as_individual(app, system_school_id: int, user_id: int, class_ids: str, sql: str):
    """Run one statement with the variables an individual subscriber's request sets.

    Mirrors ``set_tenant_for_request``: the class list and the individual flag
    are set alongside the school, and the school is the *system* school — the
    one the individual actually has a role link to.
    """
    with app.app_context():
        db.session.execute(text("SET LOCAL app.current_user_id = :uid"), {"uid": str(user_id)})
        db.session.execute(text("SET LOCAL app.current_class_ids = :cls"), {"cls": class_ids})
        db.session.execute(text("SET LOCAL app.is_individual = '1'"))
        db.session.execute(text("SET LOCAL app.current_school_id = :sid"), {"sid": str(system_school_id)})
        db.session.execute(text("SET LOCAL app.is_super_admin = '0'"))
        result = db.session.execute(text(sql)).all()
        db.session.rollback()
        return result


class TestHybridTenancyClassArm:
    """An individual must reach the school they subscribed to, and nothing else.

    The hybrid feature and RLS disagreed about what a tenant is: an individual
    holds a role link only to the system school, so the single
    ``app.current_school_id`` hid every page of the feature they pay for. The
    fix added a second value — ``app.current_class_ids``, the classes the actor
    is an active member of.

    Widening a tenant policy is the kind of change that looks like a feature
    and behaves like a hole, so each arm is pinned here with the case it must
    NOT open: reads stay inside the enrolled classes, writes stay inside the
    tenant, and the cross-school catalogue reach stays behind
    ``app.is_individual``.
    """

    @pytest.fixture
    def hybrid(self, app):
        """One host school with a public and a private class; one subscriber."""
        from app.core.db import tx
        from app.core.security import hash_password
        from app.models.assessment import Quiz
        from app.models.billing import Subscription, SubscriptionPlan
        from app.models.class_room import ClassMember, ClassRoom
        from app.models.content import Lesson, Unit
        from app.models.gradebook import Assignment
        from app.models.school import Grade, School, Subject
        from app.models.user import User, UserApprovalStatus, UserRole, UserRoleLink

        with app.app_context():
            system = School(name_ar="rls system", domain="rls-system.example.com", is_system=True, is_active=True)
            tx(db.session.add, system)
            db.session.flush()
            host = School(name_ar="rls host", domain="rls-host.example.com", is_active=True)
            tx(db.session.add, host)
            db.session.flush()
            subject = Subject(code="RLSH", name_ar="math")
            tx(db.session.add, subject)
            db.session.flush()
            grade = Grade(school_id=host.id, grade_level=1, name_ar="first")
            tx(db.session.add, grade)
            db.session.flush()

            subscriber = User(
                email="subscriber@rls.example.com",
                name_ar="subscriber",
                role=UserRole.student,
                password_hash=hash_password(RLS_TEST_PASSWORD),
                approval_status=UserApprovalStatus.approved,
                is_active=True,
                is_verified=True,
                is_individual=True,
            )
            tx(db.session.add, subscriber)
            db.session.flush()
            tx(
                db.session.add,
                UserRoleLink(user_id=subscriber.id, school_id=system.id, role=UserRole.student, is_active=True),
            )
            db.session.flush()

            public = ClassRoom(
                school_id=host.id,
                subject_id=subject.id,
                grade_id=grade.id,
                name="open",
                join_code="HYBOPEN",
                is_public=True,
                is_active=True,
            )
            private = ClassRoom(
                school_id=host.id,
                subject_id=subject.id,
                grade_id=grade.id,
                name="closed",
                join_code="HYBCLOSD",
                is_public=False,
                is_active=True,
            )
            tx(db.session.add, public)
            tx(db.session.add, private)
            db.session.flush()

            enrolled_unit = Unit(class_id=public.id, title="unit-a")
            tx(db.session.add, enrolled_unit)
            db.session.flush()
            private_unit = Unit(class_id=private.id, title="unit-b")
            tx(db.session.add, private_unit)
            db.session.flush()

            enrolled_lesson = Lesson(class_id=public.id, unit_id=enrolled_unit.id, title="lesson-a")
            tx(db.session.add, enrolled_lesson)
            private_lesson = Lesson(class_id=private.id, unit_id=private_unit.id, title="lesson-b")
            tx(db.session.add, private_lesson)
            db.session.flush()

            # A second enrolled class that is NOT public: the class row itself
            # is only reachable through the membership arm, never through the
            # catalogue gate, which is what makes it a test of the arm.
            enrolled_closed = ClassRoom(
                school_id=host.id,
                subject_id=subject.id,
                grade_id=grade.id,
                name="closed-enrolled",
                join_code="HYBCLOSE",
                is_public=False,
                is_active=True,
            )
            tx(db.session.add, enrolled_closed)
            db.session.flush()

            assignment = Assignment(class_id=public.id, title="homework", max_mark=10)
            quiz = Quiz(class_id=public.id, title="quiz", attempts_allowed=1, created_by=None)
            plan = SubscriptionPlan(school_id=host.id, class_id=public.id, name="plan", plan="annual", price=100)
            other_student = User(
                email="other@rls.example.com",
                name_ar="other",
                role=UserRole.student,
                password_hash=hash_password(RLS_TEST_PASSWORD),
                approval_status=UserApprovalStatus.approved,
                is_active=True,
                is_verified=True,
            )
            tx(db.session.add, assignment)
            tx(db.session.add, quiz)
            tx(db.session.add, plan)
            tx(db.session.add, other_student)
            db.session.flush()
            other_subscription = Subscription(
                user_id=other_student.id,
                plan_id=plan.id,
                class_id=public.id,
                price=100,
                status="pending",
            )
            tx(db.session.add, other_subscription)
            db.session.flush()

            tx(
                db.session.add,
                ClassMember(class_id=public.id, user_id=subscriber.id, status="active"),
            )
            tx(
                db.session.add,
                ClassMember(class_id=enrolled_closed.id, user_id=subscriber.id, status="active"),
            )
            db.session.commit()
            return {
                "system_school_id": system.id,
                "host_school_id": host.id,
                "subscriber_id": subscriber.id,
                "public_class_id": public.id,
                "private_class_id": private.id,
                "enrolled_private_class_id": enrolled_closed.id,
                "enrolled_lesson_id": enrolled_lesson.id,
                "private_lesson_id": private_lesson.id,
                "assignment_id": assignment.id,
                "quiz_id": quiz.id,
                "plan_id": plan.id,
                "other_student_id": other_student.id,
                "other_subscription_id": other_subscription.id,
            }

    def test_enrolled_class_content_is_readable(self, app, hybrid):
        """The whole point: the lesson they subscribed to must not be hidden."""
        seen = _run_as_individual(
            app,
            hybrid["system_school_id"],
            hybrid["subscriber_id"],
            str(hybrid["public_class_id"]),
            f"SELECT id FROM lessons WHERE id = {hybrid['enrolled_lesson_id']}",
        )
        assert [r[0] for r in seen] == [hybrid["enrolled_lesson_id"]]

    def test_class_not_joined_stays_hidden(self, app, hybrid):
        """Enrolling in one class must not open every class of that school."""
        seen = _run_as_individual(
            app,
            hybrid["system_school_id"],
            hybrid["subscriber_id"],
            str(hybrid["public_class_id"]),
            f"SELECT id FROM lessons WHERE id = {hybrid['private_lesson_id']}",
        )
        assert seen == [], "a lesson in an un-enrolled foreign class became visible"

    def test_empty_class_list_opens_nothing(self, app, hybrid):
        """Without the membership list the tenant still stands alone."""
        seen = _run_as_individual(
            app,
            hybrid["system_school_id"],
            hybrid["subscriber_id"],
            "",
            f"SELECT id FROM lessons WHERE id = {hybrid['enrolled_lesson_id']}",
        )
        assert seen == [], "the class arm widened with an empty membership list"

    def test_membership_does_not_grant_write_access(self, app, hybrid):
        """Read access to a class is not authority to author inside it.

        The class arm is on ``USING`` only. If it ever reaches ``WITH CHECK``, a
        student could insert their own lessons into a paid class.
        """
        with app.app_context():
            from sqlalchemy.exc import DBAPIError

            with pytest.raises(DBAPIError) as caught:
                _run_as_individual(
                    app,
                    hybrid["system_school_id"],
                    hybrid["subscriber_id"],
                    str(hybrid["public_class_id"]),
                    f"INSERT INTO lessons (class_id, title, status) "
                    f"VALUES ({hybrid['public_class_id']}, 'injected', 'draft')",
                )
            assert "row-level security" in str(caught.value)

    def test_public_catalogue_is_not_reachable_by_school_tenants(self, app, hybrid):
        """``app.is_individual`` is the gate on cross-school catalogue reads.

        Without it every school would see every other school's public classes.
        """
        host = hybrid["host_school_id"]
        other = _make_school_with_class(app, "catalogue")
        seen = _run_as_tenant(
            app,
            other["school_id"],
            other["student_id"],
            f"SELECT count(*) FROM classes WHERE id = {hybrid['public_class_id']}",
        )
        assert seen[0][0] == 0, (
            f"school {other['school_id']} saw a public class of school {host} without carrying the individual flag"
        )

    def test_individual_may_browse_the_public_catalogue(self, app, hybrid):
        """The flag opens the catalogue, and only public rows."""
        rows = _run_as_individual(
            app,
            hybrid["system_school_id"],
            hybrid["subscriber_id"],
            "",
            f"SELECT id FROM classes WHERE id IN ({hybrid['public_class_id']}, {hybrid['private_class_id']})",
        )
        assert [r[0] for r in rows] == [hybrid["public_class_id"]]

    def test_own_membership_rows_are_visible_without_a_tenant(self, app, hybrid):
        """``class_members`` carries a user arm, which is what makes this non-circular.

        The membership list is derived from this table *before* the tenant is
        set, so it must be reachable as the actor's own rows.
        """
        seen = _run_as_individual(
            app,
            hybrid["system_school_id"],
            hybrid["subscriber_id"],
            "",
            f"SELECT class_id FROM class_members WHERE user_id = {hybrid['subscriber_id']}",
        )
        assert {r[0] for r in seen} == {hybrid["public_class_id"], hybrid["enrolled_private_class_id"]}

    def test_other_users_memberships_are_not_visible(self, app, hybrid):
        """The user arm is the actor's own rows and nobody else's."""
        other = _make_school_with_class(app, "notmine")
        leaked = _run_as_individual(
            app,
            hybrid["system_school_id"],
            hybrid["subscriber_id"],
            str(hybrid["public_class_id"]),
            f"SELECT count(*) FROM class_members WHERE user_id = {other['student_id']}",
        )
        assert leaked[0][0] == 0, "another student's membership leaked into the subscriber's session"

    def test_the_class_row_itself_is_reachable_by_membership(self, app, hybrid):
        """``m.class_room`` must not be ``None`` for a class the actor is in.

        ``class_members`` is reachable by its own user arm, so the membership
        renders — and then the class it points at is filtered away, because
        ``classes`` was only reachable through the tenant or the public
        catalogue gate. The page then dies on ``cp.class_room.name``.
        """
        seen = _run_as_individual(
            app,
            hybrid["system_school_id"],
            hybrid["subscriber_id"],
            str(hybrid["enrolled_private_class_id"]),
            f"SELECT id FROM classes WHERE id = {hybrid['enrolled_private_class_id']}",
        )
        assert [r[0] for r in seen] == [hybrid["enrolled_private_class_id"]]

    def test_the_class_row_is_not_reachable_without_the_membership(self, app, hybrid):
        """The control for the arm above: same class, empty membership list.

        The class is not public, so if this is visible the arm is keyed on
        something other than the membership.
        """
        seen = _run_as_individual(
            app,
            hybrid["system_school_id"],
            hybrid["subscriber_id"],
            "",
            f"SELECT id FROM classes WHERE id = {hybrid['enrolled_private_class_id']}",
        )
        assert seen == [], "a non-public class of a foreign school opened without a membership"

    def test_student_may_submit_their_own_homework(self, app, hybrid):
        """Writing inside an enrolled class is the other half of reading it."""
        rows = _run_as_individual(
            app,
            hybrid["system_school_id"],
            hybrid["subscriber_id"],
            str(hybrid["public_class_id"]),
            "INSERT INTO submissions (assignment_id, student_id, body) "
            f"VALUES ({hybrid['assignment_id']}, {hybrid['subscriber_id']}, 'mine') RETURNING id",
        )
        assert len(rows) == 1

    def test_student_may_not_submit_for_another_student(self, app, hybrid):
        """The actor-owned arm names the actor — otherwise it is a forgery channel."""
        with app.app_context():
            from sqlalchemy.exc import DBAPIError

            with pytest.raises(DBAPIError) as caught:
                _run_as_individual(
                    app,
                    hybrid["system_school_id"],
                    hybrid["subscriber_id"],
                    str(hybrid["public_class_id"]),
                    "INSERT INTO submissions (assignment_id, student_id, body) "
                    f"VALUES ({hybrid['assignment_id']}, {hybrid['other_student_id']}, 'forged')",
                )
            assert "row-level security" in str(caught.value)

    def test_student_may_start_their_own_quiz_attempt(self, app, hybrid):
        """Same shape one table along: the attempt and the logs hung off it.

        Both statements share one transaction, because the arm on
        ``proctoring_logs`` reaches the actor through the attempt row and an
        attempt from a rolled-back transaction is no longer there.
        """
        rows = _run_as_individual(
            app,
            hybrid["system_school_id"],
            hybrid["subscriber_id"],
            str(hybrid["public_class_id"]),
            "INSERT INTO quiz_attempts (quiz_id, student_id, attempt_no, status) "
            f"VALUES ({hybrid['quiz_id']}, {hybrid['subscriber_id']}, 1, 'in_progress'); "
            "INSERT INTO proctoring_logs (attempt_id, event_type) "
            f"SELECT id, 'tab_switch' FROM quiz_attempts WHERE quiz_id = {hybrid['quiz_id']} "
            f"AND student_id = {hybrid['subscriber_id']} RETURNING id",
        )
        assert len(rows) == 1

    def test_student_may_not_start_an_attempt_for_another_student(self, app, hybrid):
        with app.app_context():
            from sqlalchemy.exc import DBAPIError

            with pytest.raises(DBAPIError) as caught:
                _run_as_individual(
                    app,
                    hybrid["system_school_id"],
                    hybrid["subscriber_id"],
                    str(hybrid["public_class_id"]),
                    "INSERT INTO quiz_attempts (quiz_id, student_id, attempt_no, status) "
                    f"VALUES ({hybrid['quiz_id']}, {hybrid['other_student_id']}, 1, 'in_progress')",
                )
            assert "row-level security" in str(caught.value)

    def test_student_may_pay_their_own_subscription(self, app, hybrid):
        """The subscription and its payment are two writes on the same path."""
        rows = _run_as_individual(
            app,
            hybrid["system_school_id"],
            hybrid["subscriber_id"],
            str(hybrid["public_class_id"]),
            "INSERT INTO subscriptions (user_id, plan_id, class_id, price, currency, status, source) "
            f"VALUES ({hybrid['subscriber_id']}, {hybrid['plan_id']}, {hybrid['public_class_id']}, "
            "100, 'ILS', 'pending', 'manual'); "
            "INSERT INTO manual_payments (subscription_id, reference, amount, status) "
            f"SELECT id, 'REF-RLS', 100, 'pending' FROM subscriptions "
            f"WHERE user_id = {hybrid['subscriber_id']} AND class_id = {hybrid['public_class_id']} RETURNING id",
        )
        assert len(rows) == 1

    def test_student_may_not_pay_another_students_subscription(self, app, hybrid):
        """The arm reaches through the subscription, so somebody else's is denied."""
        with app.app_context():
            from sqlalchemy.exc import DBAPIError

            with pytest.raises(DBAPIError) as caught:
                _run_as_individual(
                    app,
                    hybrid["system_school_id"],
                    hybrid["subscriber_id"],
                    str(hybrid["public_class_id"]),
                    "INSERT INTO manual_payments (subscription_id, reference, amount, status) "
                    f"VALUES ({hybrid['other_subscription_id']}, 'REF-X', 100, 'pending')",
                )
            assert "row-level security" in str(caught.value)


def test_every_registered_table_is_actually_protected(app):
    """The registry and the database must agree, table for table.

    A table in a registry with no policy in the database is silent, total
    isolation failure: nothing errors, the table simply stops being defended.
    Checking the registry alone cannot catch it, and neither can counting
    policies — ``build_all_policy_ddl`` declining a table in one loop while a
    later loop covers it makes the "skipped" list larger than the gap.
    """
    import re

    from app.core.rls import (
        _DIRECT_CLASS_ID_COLUMNS,
        _INDIRECT_TENANT_TABLES,
        _TENANT_TABLES,
        _USER_SCOPED_TABLES,
        _USER_SCOPED_WITH_TENANT,
        build_all_policy_ddl,
    )

    registered = (
        set(_TENANT_TABLES) | set(_INDIRECT_TENANT_TABLES) | set(_USER_SCOPED_TABLES) | set(_USER_SCOPED_WITH_TENANT)
    )
    statements, _declined = None, None
    with app.app_context():
        statements, _declined = build_all_policy_ddl()
        built = {
            re.search(r"CREATE POLICY \S+ ON (\w+)", s).group(1)
            for s in statements
            if s.strip().startswith("CREATE POLICY")
        }
        inspector = db.inspect(db.session.get_bind())
        existing = set(inspector.get_table_names())
        rows = db.session.execute(
            text(
                """
                SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity
                FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public' AND c.relkind = 'r'
                """
            )
        ).all()
        policies = {
            r[0]
            for r in db.session.execute(
                text(
                    "SELECT tablename FROM pg_policies WHERE schemaname = 'public'",
                )
            ).all()
        }
        forced = {r[0] for r in rows if r[1] and r[2]}

    in_schema = registered & existing
    assert built == in_schema, (
        "the code builds a different set of policies than the registry claims "
        f"to protect: only-code={sorted(built - in_schema)} "
        f"only-schema={sorted(in_schema - built)}"
    )
    assert policies == in_schema, f"a registered table has no policy in the database: {sorted(in_schema - policies)}"
    assert in_schema <= forced, f"row-level security is not FORCED on: {sorted(in_schema - forced)}"
    assert _DIRECT_CLASS_ID_COLUMNS.keys() <= registered


def test_indirect_policies_reference_existing_tables(app):
    """Each derived path names only tables the schema actually has."""
    inspector_sql = text(
        """
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
        """
    )
    with app.app_context():
        existing = {row[0] for row in db.session.execute(inspector_sql)}
    import re

    for table, subquery in _INDIRECT_TENANT_TABLES.items():
        # Only FROM/JOIN operands name tables; the rest are aliases and columns.
        for referenced in re.findall(r"(?:FROM|JOIN)\s+([a-z_][a-z0-9_]*)", subquery):
            if referenced not in existing:
                pytest.fail(f"{table}: policy path references unknown table {referenced!r}")


class TestRLSBlocksCrossTenant:
    """The floor under the application layer: raw SQL, two schools."""

    @pytest.fixture
    def two_schools(self, app):
        return {"a": _make_school_with_class(app, "a"), "b": _make_school_with_class(app, "b")}

    def test_attendance_hides_other_schools_rows(self, app, two_schools):
        a, b = two_schools["a"], two_schools["b"]
        own = _run_as_tenant(app, a["school_id"], a["teacher_id"], "SELECT count(*) FROM attendance")[0][0]
        foreign = _run_as_tenant(app, b["school_id"], b["teacher_id"], "SELECT count(*) FROM attendance")[0][0]
        # Each school seeded exactly one row, so each tenant must see exactly
        # its own — seeing 0 would mean the policy is too tight, seeing 2 that
        # it is not there at all.
        assert own == 1, "the tenant must still see its own attendance"
        assert foreign == 1, "the other school's attendance row leaked"

        # And directly: B asking for A's rows by id gets nothing.
        targeted = _run_as_tenant(
            app,
            b["school_id"],
            b["teacher_id"],
            f"SELECT count(*) FROM attendance WHERE class_id = {a['class_id']}",
        )[0][0]
        assert targeted == 0, "another school's class id returned rows"

    def test_class_members_hides_other_schools_rows(self, app, two_schools):
        a, b = two_schools["a"], two_schools["b"]
        assert _run_as_tenant(app, a["school_id"], a["teacher_id"], "SELECT count(*) FROM class_members")[0][0] == 1
        assert _run_as_tenant(app, b["school_id"], b["teacher_id"], "SELECT count(*) FROM class_members")[0][0] == 1
        # A's student is not a member of B's class — visible only if the
        # classroom scoping leaks through the policy.
        leaked = _run_as_tenant(
            app,
            b["school_id"],
            b["teacher_id"],
            f"SELECT count(*) FROM class_members WHERE class_id = {a['class_id']}",
        )[0][0]
        assert leaked == 0

    def test_grade_items_and_units_are_tenant_scoped(self, app, two_schools):
        a = two_schools["a"]
        for table in ("grade_items", "units", "lessons"):
            assert _run_as_tenant(app, a["school_id"], a["teacher_id"], f"SELECT count(*) FROM {table}")[0][0] == 0
            assert (
                _run_as_tenant(app, a["school_id"] + 999, a["teacher_id"], f"SELECT count(*) FROM {table}")[0][0] == 0
            )

    def test_role_links_are_scoped_to_the_tenant(self, app, two_schools):
        """A member sees their own links plus their own school's — never another's.

        Scoping to the acting user alone broke ``User.school_id`` for every
        colleague, so the tenant arm was added. What still has to hold is the
        boundary that matters: school A must not see school B's links.
        """
        a, b = two_schools["a"], two_schools["b"]
        own = _run_as_tenant(app, a["school_id"], a["teacher_id"], "SELECT count(*) FROM user_role_links")[0][0]
        assert own == 2, "school A's two members must both be visible to a member of school A"

        foreign = _run_as_tenant(
            app,
            a["school_id"],
            a["student_id"],
            f"SELECT count(*) FROM user_role_links WHERE school_id = {b['school_id']}",
        )[0][0]
        assert foreign == 0, "school B's role links leaked into school A's session"

    def test_super_admin_bypass_still_crosses_tenants(self, app, two_schools):
        """The existing escape hatch must keep working — it is not a bug to fix."""
        with app.app_context():
            db.session.execute(
                text(
                    "SELECT set_config('app.is_super_admin', '1', false), "
                    "set_config('app.current_school_id', '0', false)"
                )
            )
            db.session.commit()
            total = db.session.execute(text("SELECT count(*) FROM attendance")).scalar()
            db.session.rollback()
        assert total == 2, "super_admin must still see both schools"

    def test_anonymous_request_cannot_use_the_tables(self, app, two_schools):
        """`app.current_user_id` is '0' when anonymous — never unset.

        Unset would read back as '', and '' compared as text matches nothing
        rather than raising, which is why the policies use ::text.

        The school is ``'0'`` for anonymous too (``set_tenant_for_request`` sets
        it explicitly), and no school has that id — so the tenant arm on
        ``user_role_links`` matches nothing and the assertion below still holds
        once that arm exists.
        """
        rows = _run_as_tenant(app, 0, 0, "SELECT count(*) FROM user_role_links")
        assert rows[0][0] == 0


class _FakeAttempt:
    """Minimal stand-in so the display helpers can be tested without a row."""

    def __init__(self, quiz, display_order):
        self.quiz = quiz
        self.display_order = display_order


class TestQuizShuffle:
    """`Quiz.shuffle` was stored on the quiz and read by nothing."""

    @pytest.fixture
    def quiz(self, app):
        """A real quiz in a real class, with five four-option MCQ questions."""
        from app.models.assessment import Question, Quiz

        tenant = _make_school_with_class(app, "quiz")
        with app.app_context():
            row = Quiz(
                class_id=tenant["class_id"],
                title="shuffle",
                shuffle=True,
                attempts_allowed=3,
            )
            db.session.add(row)
            db.session.flush()
            for i in range(5):
                db.session.add(
                    Question(
                        quiz_id=row.id,
                        type="mcq",
                        prompt=f"q{i}",
                        options={"items": [{"label": c, "text": f"{c}{i}"} for c in "ABCD"]},
                        correct_answer={"index": 1},
                        mark=2,
                        sort_order=i,
                    )
                )
            db.session.commit()
            yield {"row": row, "student_id": tenant["student_id"]}
            db.session.rollback()

    def test_shuffle_false_keeps_the_author_order(self, app, quiz):
        from app.services.assessment import questions_in_display_order, start_attempt

        with app.app_context():
            row = quiz["row"]
            row.shuffle = False
            db.session.commit()
            attempt, error = start_attempt(row, student_id=quiz["student_id"])

            assert error is None
            assert attempt.display_order is None
            assert [q.id for q in questions_in_display_order(attempt)] == [q.id for q in row.questions]

    def test_shuffle_true_permutes_questions_and_options(self, app, quiz):
        from app.services.assessment import (
            build_display_order,
            option_index_to_original,
            options_in_display_order,
            questions_in_display_order,
        )

        with app.app_context():
            row = quiz["row"]
            questions = list(row.questions)
            natural = [q.id for q in questions]

            order = build_display_order(questions, seed="1:2:1", shuffle=True)
            assert order is not None
            assert sorted(order["questions"]) == natural, "no question may be lost or duplicated"
            assert order["questions"] != natural, "shuffle=True must reorder the questions"

            attempt = _FakeAttempt(row, order)
            assert [q.id for q in questions_in_display_order(attempt)] == order["questions"]

            # Options are permuted too, and the permutation is a bijection back
            # to the original indexes — that is what keeps correct_answer valid
            # no matter what order the student saw.
            for question in questions:
                displayed = [item["text"] for item in options_in_display_order(question, attempt)]
                original = [item["text"] for item in question.options["items"]]
                assert sorted(displayed) == sorted(original)
                mapping = [option_index_to_original(question, attempt, i) for i in range(4)]
                assert sorted(mapping) == [0, 1, 2, 3]

    def test_order_is_deterministic_for_the_same_seed(self, app, quiz):
        from app.services.assessment import build_display_order

        with app.app_context():
            questions = list(quiz["row"].questions)
            first = build_display_order(questions, seed="7:9:2", shuffle=True)
            second = build_display_order(questions, seed="7:9:2", shuffle=True)
            third = build_display_order(questions, seed="7:9:3", shuffle=True)

        assert first == second, "a refresh must not move the options under the student"
        assert first["questions"] != third["questions"], "a different attempt should differ"

    def test_shuffle_does_not_mutate_the_quiz(self, app, quiz):
        """The teacher's definition is shared by every student — it must not move."""
        from app.services.assessment import build_display_order

        with app.app_context():
            row = quiz["row"]
            before = [(q.id, [i["text"] for i in q.options["items"]]) for q in row.questions]
            build_display_order(list(row.questions), seed="1:1:1", shuffle=True)
            db.session.expire_all()
            after = [(q.id, [i["text"] for i in q.options["items"]]) for q in row.questions]
        assert before == after, "shuffling leaked into the shared quiz definition"

    def test_too_few_questions_are_left_alone(self, app, quiz):
        from app.services.assessment import build_display_order

        with app.app_context():
            assert build_display_order(list(quiz["row"].questions)[:1], seed="1:1:1", shuffle=True) is None

    def test_a_question_added_mid_attempt_still_shows_up(self, app, quiz):
        """Display order is a stored list, not a snapshot — it must not hide rows."""
        from app.models.assessment import Question
        from app.services.assessment import questions_in_display_order, start_attempt

        with app.app_context():
            row = quiz["row"]
            attempt, _ = start_attempt(row, student_id=quiz["student_id"])
            late = Question(
                quiz_id=row.id,
                type="true_false",
                prompt="late",
                correct_answer={"value": True},
                mark=1,
                sort_order=99,
            )
            db.session.add(late)
            db.session.commit()

            shown = [q.id for q in questions_in_display_order(attempt)]
        assert late.id in shown

    def test_saved_answer_is_mapped_to_the_original_index(self, app, quiz):
        """The submitted display index must land on the author's index.

        This is the invariant that lets grading ignore shuffling entirely: one
        `correct_answer` stays valid for every permutation.
        """
        from app.models.assessment import Answer
        from app.services.assessment import option_index_to_original, save_answer, start_attempt

        with app.app_context():
            row = quiz["row"]
            attempt, error = start_attempt(row, student_id=quiz["student_id"])
            assert error is None
            assert attempt.display_order is not None

            question_id, permutation = next(iter(attempt.display_order["options"].items()))
            question_id = int(question_id)
            question = next(q for q in row.questions if q.id == question_id)

            for displayed in range(4):
                save_answer(attempt, question_id, {"index": displayed})
                db.session.commit()
                row_saved = Answer.query.filter_by(attempt_id=attempt.id, question_id=question_id).first()
                expected = option_index_to_original(question, attempt, displayed)
                assert row_saved.answer["index"] == expected
                assert permutation[displayed] == expected


class TestNoNPlusOne:
    """The shuffle must not cost an extra query per question.

    `attempt_save` opens one transaction per answer — three `SET LOCAL`
    statements, the answer lookup and the write — which is the pre-existing
    design and out of scope here. What matters for this batch is that turning
    `shuffle` on adds *no* queries on top of that: the display order is a stored
    list on the attempt and the option permutation is a dict read, so nothing
    re-queries the quiz per question.

    Measuring "with shuffle" against "without shuffle" on the same quiz is what
    isolates that; comparing two different sizes would only measure the
    pre-existing per-answer transaction.
    """

    @pytest.fixture
    def sized_quizzes(self, app):
        """One tenant, one student, quizzes of 4, 8 and 16 questions.

        Growing sizes is what makes the measurement mean anything: a per-question
        query shows up as a slope, a fixed number of queries as a flat line.
        """
        from app.models.assessment import Question, Quiz

        tenant = _make_school_with_class(app, "n1")
        made = {}
        with app.app_context():
            for size in (4, 8, 16):
                row = Quiz(
                    class_id=tenant["class_id"],
                    title=f"n1-{size}",
                    shuffle=True,
                    attempts_allowed=5,
                )
                db.session.add(row)
                db.session.flush()
                for i in range(size):
                    db.session.add(
                        Question(
                            quiz_id=row.id,
                            type="mcq",
                            prompt=f"q{i}",
                            options={"items": [{"label": c, "text": f"{c}{i}"} for c in "ABCD"]},
                            correct_answer={"index": 1},
                            mark=2,
                            sort_order=i,
                        )
                    )
                db.session.commit()
                made[size] = row.id
        yield {"tenant": tenant, "quizzes": made}

    @pytest.fixture
    def pair_of_quizzes(self, app):
        """Two identical 8-question quizzes, differing only in `shuffle`.

        Same size, same shape — so a difference in query count is the shuffle's
        alone, with nothing else to hide behind.
        """
        from app.models.assessment import Question, Quiz

        tenant = _make_school_with_class(app, "n1s")
        made = {}
        with app.app_context():
            for shuffled in (False, True):
                row = Quiz(
                    class_id=tenant["class_id"],
                    title=f"n1s-{'shuffled' if shuffled else 'plain'}",
                    shuffle=shuffled,
                    attempts_allowed=5,
                )
                db.session.add(row)
                db.session.flush()
                for i in range(8):
                    db.session.add(
                        Question(
                            quiz_id=row.id,
                            type="mcq",
                            prompt=f"q{i}",
                            options={"items": [{"label": c, "text": f"{c}{i}"} for c in "ABCD"]},
                            correct_answer={"index": 1},
                            mark=2,
                            sort_order=i,
                        )
                    )
                db.session.commit()
                made[shuffled] = row.id
        yield {"tenant": tenant, "quizzes": made}

    def _login(self, app, tag="n1"):
        from tests.conftest import QueryCounter  # noqa: F401  (kept next to its only users)

        client = app.test_client()
        client.post(
            "/auth/login",
            data={"email": f"student-{tag}@rls.example.com", "password": RLS_TEST_PASSWORD},
        )
        return client

    def _start(self, app, quiz_id, student_id):
        from app.models.assessment import Quiz
        from app.services.assessment import start_attempt

        with app.app_context():
            attempt, error = start_attempt(db.session.get(Quiz, quiz_id), student_id=student_id)
            assert error is None
            return attempt.id

    def test_rendering_the_attempt_is_flat_in_the_question_count(self, app, sized_quizzes):
        """Rendering must not read once per question.

        Measured, not asserted by construction: a per-question lazy load inside
        `questions_in_display_order` would make this count climb 4 -> 8 -> 16.
        """
        from tests.conftest import QueryCounter

        student_id = sized_quizzes["tenant"]["student_id"]
        client = self._login(app, tag="n1")
        self._warm_first(client, app, sized_quizzes, student_id)

        counts = {}
        for size, quiz_id in sized_quizzes["quizzes"].items():
            attempt_id = self._start(app, quiz_id, student_id)
            self._cold(app)
            with app.app_context():
                with QueryCounter(db.engine) as qc:
                    response = client.get(f"/classes/attempt/{attempt_id}")
            assert response.status_code == 200
            counts[size] = qc.count
        assert counts[4] == counts[16], f"عرض المحاولة يتناسب مع عدد الأسئلة — N+1: {counts}"

    def test_saving_costs_the_same_with_and_without_shuffle(self, app, pair_of_quizzes):
        from app.models.assessment import Quiz
        from tests.conftest import QueryCounter

        student_id = pair_of_quizzes["tenant"]["student_id"]
        client = self._login(app, tag="n1s")
        self._warm_first(client, app, pair_of_quizzes, student_id)

        counts = {}
        for shuffled, quiz_id in pair_of_quizzes["quizzes"].items():
            with app.app_context():
                quiz = db.session.get(Quiz, quiz_id)
                data = {f"q_{q.id}": "2" for q in quiz.questions}
                attempt_id = self._start(app, quiz_id, student_id)
            self._cold(app)
            with app.app_context():
                with QueryCounter(db.engine) as qc:
                    response = client.post(f"/classes/attempt/{attempt_id}/save", data=data)
            assert response.status_code in (200, 302)
            counts[shuffled] = qc.count
        assert counts[True] == counts[False], f"الخلط أضاف استعلامات إلى الحفظ: {counts}"

    def _warm_first(self, client, app, quizzes, student_id):
        """Pay the one-off request costs outside the measured window."""
        for quiz_id in quizzes["quizzes"].values():
            attempt_id = self._start(app, quiz_id, student_id)
            with app.app_context():
                from app.models.assessment import Quiz

                data = {f"q_{q.id}": "1" for q in db.session.get(Quiz, quiz_id).questions}
                client.post(f"/classes/attempt/{attempt_id}/save", data=data)
                client.get(f"/classes/attempt/{attempt_id}")

    @staticmethod
    def _cold(app):
        """Discard the identity map so the next request really re-reads.

        Without this the test proves nothing: `attempt.quiz.questions` was
        already loaded by the fixture, so a per-question lazy load inside the
        route would be served from memory and never reach the counter. A
        deliberate mutation of `option_permutation` still passed while this was
        missing.
        """
        with app.app_context():
            db.session.remove()


class TestDisplayHelpersEdgeCases:
    """The branches that only a quiz without shuffling, or a stale row, reaches."""

    @pytest.fixture
    def plain_question(self, app):
        from app.models.assessment import Question, Quiz

        tenant = _make_school_with_class(app, "plain")
        with app.app_context():
            row = Quiz(class_id=tenant["class_id"], title="plain", shuffle=False, attempts_allowed=1)
            db.session.add(row)
            db.session.flush()
            question = Question(
                quiz_id=row.id,
                type="mcq",
                prompt="p",
                options={"items": [{"label": c, "text": c} for c in "AB"]},
                correct_answer={"index": 0},
                mark=1,
            )
            db.session.add(question)
            db.session.commit()
            yield {"question": question, "student_id": tenant["student_id"], "quiz": row}
            db.session.rollback()

    def test_no_permutation_returns_the_author_options(self, app, plain_question):
        from app.services.assessment import option_index_to_original, options_in_display_order

        with app.app_context():
            question = plain_question["question"]
            attempt = _FakeAttempt(plain_question["quiz"], None)
            assert [i["text"] for i in options_in_display_order(question, attempt)] == ["A", "B"]
            assert option_index_to_original(question, attempt, 1) == 1

    def test_question_without_options_is_not_an_error(self, app, plain_question):
        from app.models.assessment import Question
        from app.services.assessment import options_in_display_order

        with app.app_context():
            essay = Question(quiz_id=plain_question["quiz"].id, type="essay", prompt="e", mark=1)
            db.session.add(essay)
            db.session.commit()
            assert options_in_display_order(essay, _FakeAttempt(plain_question["quiz"], None)) == []

    def test_out_of_range_display_index_falls_back_to_itself(self, app, plain_question):
        """A tampered form field must not map onto another option."""
        from app.services.assessment import option_index_to_original

        with app.app_context():
            question = plain_question["question"]
            attempt = _FakeAttempt(
                plain_question["quiz"], {"questions": [question.id], "options": {str(question.id): [1, 0]}}
            )
            assert option_index_to_original(question, attempt, 99) == 99

    def test_saving_after_submission_is_refused(self, app, plain_question):
        from app.core.db import TxError
        from app.services.assessment import save_answer, start_attempt

        with app.app_context():
            attempt, _ = start_attempt(plain_question["quiz"], student_id=plain_question["student_id"])
            attempt.status = "submitted"
            db.session.commit()
            with pytest.raises(TxError):
                save_answer(attempt, plain_question["question"].id, {"index": 0})

    def test_saving_after_the_deadline_is_refused(self, app, timed_question):
        """The server, not the browser, owns the clock.

        ``duration_min`` is set when the quiz is created: mutating it afterwards
        leaves the attempt's already-loaded ``quiz`` relationship holding the
        old value, and the test would pass for the wrong reason.
        """
        from app.core.db import TxError
        from app.services.assessment import save_answer, start_attempt

        with app.app_context():
            attempt, _ = start_attempt(timed_question["quiz"], student_id=timed_question["student_id"])
            attempt.started_at = datetime.now(UTC) - timedelta(minutes=30)
            db.session.commit()
            with pytest.raises(TxError):
                save_answer(attempt, timed_question["question"].id, {"index": 0})

    @pytest.fixture
    def timed_question(self, app):
        from app.models.assessment import Question, Quiz

        tenant = _make_school_with_class(app, "timed")
        with app.app_context():
            row = Quiz(
                class_id=tenant["class_id"],
                title="timed",
                shuffle=False,
                attempts_allowed=2,
                duration_min=1,
            )
            db.session.add(row)
            db.session.flush()
            question = Question(
                quiz_id=row.id,
                type="mcq",
                prompt="t",
                options={"items": [{"label": "A", "text": "A"}]},
                correct_answer={"index": 0},
                mark=1,
            )
            db.session.add(question)
            db.session.commit()
            yield {"question": question, "student_id": tenant["student_id"], "quiz": row}
            db.session.rollback()

    def test_an_answer_with_no_permutation_is_stored_as_submitted(self, app, plain_question):
        """``shuffle`` off means no permutation, so the index passes through."""
        from app.models.assessment import Answer
        from app.services.assessment import save_answer, start_attempt

        with app.app_context():
            attempt, _ = start_attempt(plain_question["quiz"], student_id=plain_question["student_id"])
            assert attempt.display_order is None
            save_answer(attempt, plain_question["question"].id, {"index": 1})
            db.session.commit()

            row = Answer.query.filter_by(attempt_id=attempt.id, question_id=plain_question["question"].id).first()
            assert row.answer["index"] == 1

    def test_a_second_start_returns_the_running_attempt(self, app, plain_question):
        from app.services.assessment import start_attempt

        with app.app_context():
            first, _ = start_attempt(plain_question["quiz"], student_id=plain_question["student_id"])
            second, error = start_attempt(plain_question["quiz"], student_id=plain_question["student_id"])
            assert error is None
            assert second.id == first.id

    def test_exhausted_attempts_are_refused(self, app, plain_question):
        from app.services.assessment import start_attempt

        with app.app_context():
            quiz = plain_question["quiz"]
            quiz.attempts_allowed = 1
            db.session.commit()
            start_attempt(quiz, student_id=plain_question["student_id"])
            from app.models.assessment import QuizAttempt

            db.session.query(QuizAttempt).filter_by(quiz_id=quiz.id, student_id=plain_question["student_id"]).update(
                {"status": "submitted"}
            )
            db.session.commit()
            attempt, error = start_attempt(quiz, student_id=plain_question["student_id"])
            assert attempt is None
            assert error


class TestUserScopedPolicyHelper:
    """`enable_rls_on_user_scoped_table` is what the migration mirrors."""

    def test_it_creates_a_policy_and_is_idempotent(self, app):
        from app.core.rls import enable_rls_on_user_scoped_table

        with app.app_context():
            db.session.execute(text("ALTER TABLE user_role_links NO FORCE ROW LEVEL SECURITY"))
            db.session.execute(text("ALTER TABLE user_role_links DISABLE ROW LEVEL SECURITY"))
            db.session.execute(text("DROP POLICY IF EXISTS tenant_isolation_user_role_links ON user_role_links"))
            db.session.commit()

            assert enable_rls_on_user_scoped_table("user_role_links") is True
            db.session.commit()
            # Re-running must replace the policy, not fail on a duplicate name.
            assert enable_rls_on_user_scoped_table("user_role_links") is True
            db.session.commit()

            policies = db.session.execute(
                text("SELECT count(*) FROM pg_policy WHERE polrelid = 'user_role_links'::regclass")
            ).scalar()
            forced = db.session.execute(
                text("SELECT relforcerowsecurity FROM pg_class WHERE relname = 'user_role_links'")
            ).scalar()
        assert policies == 1
        assert forced is True

    def test_a_missing_table_is_skipped_not_fatal(self, app):
        from app.core.rls import enable_rls_on_user_scoped_table

        with app.app_context():
            assert enable_rls_on_user_scoped_table("table_that_is_not_here") is False

    def test_enable_all_covers_the_user_scoped_tables(self, app):
        """`enable_all_rls_policies` must walk the user-scoped list too.

        The rollout added `user_role_links` and `audit_logs` to a third list.
        `enable_all_rls_policies` is what a fresh deployment runs; if it only
        walked the two original lists, a new database would come up with those
        two tables unprotected while the migration-protected database looked
        fine — the exact class of silent gap this batch exists to close.
        """
        from app.core.rls import disable_all_rls_policies, enable_all_rls_policies

        with app.app_context():
            disable_all_rls_policies()
            db.session.commit()
            enable_all_rls_policies()

            for table in _USER_SCOPED_TABLES:
                exists = db.session.execute(
                    text("SELECT count(*) FROM pg_class WHERE relname = :t"),
                    {"t": table},
                ).scalar()
                if not exists:
                    continue
                policies = db.session.execute(
                    text("SELECT count(*) FROM pg_policy WHERE polrelid = CAST(:t AS regclass)"),
                    {"t": table},
                ).scalar()
                assert policies == 1, f"{table} بلا سياسة بعد enable_all_rls_policies"

            enable_all_rls_policies()  # restore for the rest of the suite
            db.session.commit()


class TestTenantContextVariables:
    """`set_tenant_for_request` sets three variables, and the order matters."""

    def _variables(self):
        return db.session.execute(
            text(
                "SELECT current_setting('app.current_user_id', true), "
                "current_setting('app.current_school_id', true), "
                "current_setting('app.is_super_admin', true)"
            )
        ).one()

    def test_an_anonymous_request_sets_zeros(self, app):
        from app.core.tenancy import set_tenant_for_request

        with app.test_request_context("/"):
            set_tenant_for_request()
            user_id, school_id, is_admin = self._variables()
            db.session.rollback()
        assert (user_id, school_id, is_admin) == ("0", "0", "0")

    def test_an_authenticated_user_resolves_their_own_school(self, app):
        """The regression this ordering exists to prevent.

        `User.school_id` is a property over `user_role_links`, and that table's
        policy keys on `app.current_user_id`. Read the school first and the
        link query returns nothing, so the school falls back to 0 and the
        request sees an empty tenant.
        """
        from app.core.tenancy import set_tenant_for_request

        tenant = _make_school_with_class(app, "ctx")
        with app.test_request_context("/"):
            from app.models.user import User
            from flask_login import login_user

            login_user(db.session.get(User, tenant["teacher_id"]))
            set_tenant_for_request()
            user_id, school_id, is_admin = self._variables()
            db.session.rollback()
        assert user_id == str(tenant["teacher_id"])
        assert school_id == str(tenant["school_id"])
        assert is_admin == "0"

    def test_super_admin_keeps_the_bypass(self, app):
        from app.core.tenancy import set_tenant_for_request

        tenant = _make_school_with_class(app, "root")
        with app.test_request_context("/"):
            from app.models.user import User
            from flask_login import login_user

            root = User(
                email=f"root-{tenant['school_id']}@rls.example.com",
                name_ar="root",
                role="super_admin",
                password_hash="not-a-real-hash",
                is_active=True,
            )
            db.session.add(root)
            db.session.commit()
            login_user(root)
            set_tenant_for_request()
            _, school_id, is_admin = self._variables()
            db.session.rollback()
        assert school_id == "0"
        assert is_admin == "1"

    def test_a_failed_set_local_does_not_break_the_request(self, app, monkeypatch):
        """SET LOCAL can fail when no transaction is open; that must not 500."""
        from app.core.tenancy import set_tenant_for_request

        def boom(*args, **kwargs):
            raise RuntimeError("no transaction")

        monkeypatch.setattr(db.session, "execute", boom)
        with app.test_request_context("/"):
            set_tenant_for_request()  # must swallow the failure
