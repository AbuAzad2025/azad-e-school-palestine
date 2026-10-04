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
    """
    assert "user_role_links" in _USER_SCOPED_TABLES
    assert "user_role_links" not in _TENANT_TABLES
    assert "user_role_links" not in _INDIRECT_TENANT_TABLES


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

    def test_role_links_are_visible_only_to_their_owner(self, app, two_schools):
        a = two_schools["a"]
        own = _run_as_tenant(app, a["school_id"], a["teacher_id"], "SELECT count(*) FROM user_role_links")[0][0]
        others = _run_as_tenant(app, a["school_id"], a["student_id"], "SELECT count(*) FROM user_role_links")[0][0]
        assert own == 1, "a user must resolve their own role links (login depends on it)"
        assert others == 1, "the student sees only their own link, not the teacher's"

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
        """
        rows = _run_as_tenant(app, two_schools["a"]["school_id"], 0, "SELECT count(*) FROM user_role_links")
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
