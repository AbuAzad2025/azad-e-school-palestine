"""PostgreSQL Row Level Security (RLS) — دفاع الطابق الثاني.

RLS يفرض عزل التينانتس على مستوى قاعدة البيانات نفسها. حتى لو خانت
التطبيق طبقة scope_by_school()، فإن PostgreSQL نفسها ترفض إرجاع بيانات
مدرسة أخرى.

الآلية:
  1. كل جدول يحمل school_id يُفعَّل عليه RLS مع سياسة بسيطة:
     WHERE school_id = current_setting('app.current_school_id')::bigint
  2. قبل كل طلب، يُضبط المتغير عبر SET LOCAL داخل نفس المعاملة.
  3. super_admin يتخطى RLS عبر bypass_policy.

P3-01: RLS as secondary fail-safe behind scope_by_school().
P3-02: Session-level variable set via SET LOCAL (auto-reset on transaction end).
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import event, inspect, text

from app.core.logging import get_logger
from app.extensions import db

logger = get_logger(__name__)


def _table_exists(table_name: str) -> bool:
    """حماية زمن التشغيل: الجدول قد لا يكون موجوداً (اختبارات/ترحيل قديم)."""
    try:
        return inspect(db.session.get_bind()).has_table(table_name)
    except Exception:  # noqa: BLE001 — لا يوجد اتصال/جدول
        return False


def _has_column(table_name: str, column_name: str) -> bool:
    """فحص وجود عمود قبل بناء سياسة تعتمد عليه (مثل school_id)."""
    try:
        cols = inspect(db.session.get_bind()).get_columns(table_name)
        return column_name in {c["name"] for c in cols}
    except Exception:  # noqa: BLE001
        return False


# ─── Tables that carry school_id and MUST have RLS ─────────────────────
_TENANT_TABLES: list[str] = [
    "academic_events",
    "announcements",
    "assignments",
    "attendance",
    "audit_logs",
    "class_members",
    "classes",
    "certificate_templates",
    "discount_codes",
    "grade_categories",
    "grade_items",
    "grades",
    "lessons",
    "lesson_attachments",
    "onboarding_progress",
    "question_bank",
    "rubric_criteria",
    "rubric_templates",
    "school_settings",
    "student_progress",
    "whatsapp_links",
    "subscription_plans",
    "subscriptions",
    "tenant_quotas",
    "units",
    "video_progress",
    "offline_downloads",
    "manual_payments",
    "payment_receipts",
    "wallets",
    "wallet_transactions",
]

# Tables scoped by the acting user rather than by tenant.
#
# ``audit_logs`` is scoped by ``app.current_user_id``: a row records what *one*
# actor did, so each user reads their own trail and ``super_admin`` reads
# everything.
#
# ``user_role_links`` is the table that *derives* the user's school, so a
# purely school-scoped policy would be circular — the query that resolves the
# tenant would be filtered by the tenant it is resolving. It is scoped by
# ``app.current_user_id`` *and* by ``app.current_school_id``. The second arm is
# not circular: the tenant is resolved from the actor's own links (which the
# user arm already exposes) and only then widens visibility inside that
# school. Without it an administrator sees nobody's links but their own, so
# ``User.school_id`` is empty for every colleague and the same-school access
# checks deny legitimate requests.
#
# The comparison is on ``::text`` on purpose: ``current_setting`` of an unset
# custom GUC returns ``''``, and ``''::bigint`` raises ``invalid input syntax``
# for every row of the table. Text comparison is total, so an unset variable
# simply matches nothing instead of exploding. PostgreSQL does not guarantee the
# evaluation order of the ``OR`` branches, so the safe form must be the one in
# both branches.
_USER_SCOPED_TABLES: list[str] = ["audit_logs"]

# ``user_role_links`` needs the extra tenant arm, so it is kept out of the
# registry above — only this table gets it.
_USER_SCOPED_WITH_TENANT: list[str] = ["user_role_links"]


# ══════════════════════════════════════════════════════════════════════════
# Hybrid tenancy — individuals reading a school they have no role link to
# ══════════════════════════════════════════════════════════════════════════
#
# The system school has no role link to the schools whose public classes an
# individual subscribes to, so a single ``app.current_school_id`` hides every
# page of that feature: the catalogue is empty, ``db.session.get(ClassRoom, …)``
# returns ``None``, and the subscribe view refuses a class that is right there.
# One session variable cannot express "my school *or* the classes I am in", so
# two more carry the rest:
#
#   app.current_class_ids — comma-separated ids of the classes the actor is an
#       *active member* of. Read paths of the content graph grow an arm for
#       them. ``set_tenant_for_request`` derives it from ``class_members``,
#       which stays readable for the actor's own rows because that policy has
#       a ``user_id`` arm — so the derivation cannot be filtered by the very
#       tenant it is deriving.
#
#   app.is_individual — set only for users flagged ``is_individual``. Browsing
#       the catalogue needs cross-school *read* on ``classes``; that widening
#       must not reach ordinary school tenants, who keep their own school only.
#
# Write paths deliberately do **not** get the class arm. It would let a student
# author lessons, units and assignments inside a class they are merely enrolled
# in. Only the two tables a subscriber legitimately writes to —
# ``class_members`` and ``subscriptions`` — get a ``user_id`` arm, and both are
# keyed by the actor, so the arm grants nothing about anybody else's row.
_CLASS_IDS_GUC = "app.current_class_ids"
_INDIVIDUAL_GUC = "app.is_individual"

# How each indirect table reaches its class. Parallel to
# ``_INDIRECT_TENANT_TABLES`` above and navigates the same joins, so a row
# reaches the same ``classes`` row its tenant check does.
_CLASS_ID_EXPRESSIONS: dict[str, str] = {
    "announcements": "announcements.class_id",
    "assignments": "assignments.class_id",
    "attendance": "attendance.class_id",
    "class_members": "class_members.class_id",
    "grade_categories": "grade_categories.class_id",
    "grade_items": "grade_items.class_id",
    "lessons": "lessons.class_id",
    "lesson_attachments": "SELECT l.class_id FROM lessons l WHERE l.id = lesson_attachments.lesson_id",
    "student_progress": "student_progress.class_id",
    "subscriptions": "subscriptions.class_id",
    "units": "units.class_id",
    "video_progress": "video_progress.class_id",
    "offline_downloads": "SELECT l.class_id FROM lessons l WHERE l.id = offline_downloads.lesson_id",
    "manual_payments": "SELECT s.class_id FROM subscriptions s WHERE s.id = manual_payments.subscription_id",
    "payment_receipts": (
        "SELECT s.class_id FROM subscriptions s JOIN manual_payments mp ON mp.subscription_id = s.id "
        "WHERE mp.id = payment_receipts.manual_payment_id"
    ),
    "quiz_attempts": "SELECT q.class_id FROM quizzes q WHERE q.id = quiz_attempts.quiz_id",
    "answers": (
        "SELECT q.class_id FROM quizzes q JOIN quiz_attempts qa ON qa.quiz_id = q.id WHERE qa.id = answers.attempt_id"
    ),
    "quizzes": "quizzes.class_id",
    "grade_entries": "SELECT gi.class_id FROM grade_items gi WHERE gi.id = grade_entries.grade_item_id",
    "submissions": "SELECT a.class_id FROM assignments a WHERE a.id = submissions.assignment_id",
    "proctoring_logs": (
        "SELECT q.class_id FROM quizzes q JOIN quiz_attempts qa ON qa.quiz_id = q.id "
        "WHERE qa.id = proctoring_logs.attempt_id"
    ),
}

# Direct-``school_id`` tables that are nonetheless reachable through a class.
#
# ``classes`` reaches itself: a member of a class in a school they hold no role
# link to must be able to read *that* row. Without the arm the membership
# itself is visible (``class_members``) while the class it points at is not, so
# ``m.class_room`` is ``None`` and every class-scoped page renders as a
# half-populated list. Read-only, exactly like every other membership arm.
_DIRECT_CLASS_ID_COLUMNS: dict[str, str] = {
    "classes": "classes.id",
    "subscription_plans": "subscription_plans.class_id",
}

# Tables keyed by the actor: a subscriber must always read and write their own
# rows there, whichever school the row's class belongs to. Both carry
# ``user_id``, so the arm implies nothing about anybody else's row.
_USER_OWNED_TABLES: list[str] = ["class_members", "subscriptions"]


# Rows a student authors inside a class they belong to. Read is already covered
# by the membership arm; ``WITH CHECK`` needs its own, or the assignment a
# student submits and the attempt a student starts are rejected by the very
# school isolation that lets them read the page they are acting on. Each arm
# names the actor, so it grants nothing about anybody else's row: the grade a
# teacher writes back still needs the tenant arm, and stays denied here.
def _attempt_owned_arm(table: str) -> str:
    return (
        f"EXISTS (SELECT 1 FROM quiz_attempts qa WHERE qa.id = {table}.attempt_id "
        f"AND qa.student_id::text = current_setting('app.current_user_id', true))"
    )


def _subscription_owned_arm(table: str, fk: str) -> str:
    hops = {
        "subscription_id": f"s.id = {table}.subscription_id",
        "manual_payment_id": f"mp.id = {table}.manual_payment_id",
    }[fk]
    join = "" if fk == "subscription_id" else " JOIN manual_payments mp ON mp.subscription_id = s.id"
    return (
        f"EXISTS (SELECT 1 FROM subscriptions s{join} WHERE {hops} "
        f"AND s.user_id::text = current_setting('app.current_user_id', true))"
    )


def _class_ids_match(class_id_expr: str) -> str:
    """SQL predicate: this row's class is one the actor is an active member of.

    Both sides are ``::text``. An unset custom GUC reads back as ``''``, and
    ``''::bigint`` raises ``invalid input syntax`` for every row of the table;
    text comparison is total, so an unset variable simply matches nothing. It
    cannot be pushed into the ``OR``'s other branch either, because PostgreSQL
    does not promise to evaluate ``OR`` left to right.
    """
    return f"({class_id_expr})::text = ANY(string_to_array(current_setting('{_CLASS_IDS_GUC}', true), ','))"


def build_policy_ddl(
    table_name: str,
    tenant_expr: str,
    read_arms: list[str],
    write_arms: list[str],
) -> list[str]:
    """Build the statements that put one table under its isolation policy.

    Pure — no session, no bind — so the Alembic migration that ships these
    policies and the runtime path that re-applies them cannot drift apart.
    Drift is not hypothetical here: the four failures this replaced all came
    from a migration and a runtime helper disagreeing about what a policy says.

    ``read_arms`` may widen ``USING``; ``write_arms`` widens ``WITH CHECK``.
    Keep that split honest — see ``_CLASS_IDS_GUC``.
    """

    def _clause(arms: list[str]) -> str:
        return "current_setting('app.is_super_admin', true) = '1'" + "".join(
            f"\n                    OR {a}" for a in [tenant_expr, *arms]
        )

    using = _clause(read_arms)
    with_check = _clause(write_arms)
    policy_name = f"tenant_isolation_{table_name}"
    return [
        f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY",
        f"DROP POLICY IF EXISTS {policy_name} ON {table_name}",
        f"""
    CREATE POLICY {policy_name} ON {table_name}
        FOR ALL
        USING ({using})
        WITH CHECK ({with_check})
    """,
    ]


def _user_id_arm(col_expr: str = "user_id") -> str:
    """Predicate matching a row keyed by the acting user.

    ``::text`` on both sides: an unset custom GUC reads back as ``''`` and
    ``''::bigint`` would raise for every row of the table.
    """
    return f"{col_expr}::text = current_setting('app.current_user_id', true)"


_ACTOR_OWNED_WRITE_ARMS: dict[str, str] = {
    "submissions": _user_id_arm("submissions.student_id"),
    "quiz_attempts": _user_id_arm("quiz_attempts.student_id"),
    "answers": _attempt_owned_arm("answers"),
    "proctoring_logs": _attempt_owned_arm("proctoring_logs"),
    "manual_payments": _subscription_owned_arm("manual_payments", "subscription_id"),
    "payment_receipts": _subscription_owned_arm("payment_receipts", "manual_payment_id"),
}


def build_all_policy_ddl(bind=None) -> tuple[list[str], list[str]]:
    """DDL for every registered policy, plus the tables no policy was built for.

    ``bind`` is only used to filter out tables that are not in this database.

    The second return value means *unprotected*, and reading it as anything
    narrower will mislead: a table that traces its tenant through a join is
    listed in ``_TENANT_TABLES`` as well as ``_INDIRECT_TENANT_TABLES``, so it
    is declined by the first loop (no ``school_id`` column) and covered by the
    second. It appears in this list while still ending up with a policy. What
    must hold is the invariant that
    ``test_every_registered_table_is_actually_protected`` checks: every table
    that exists and is registered carries exactly one policy.
    """
    from sqlalchemy import inspect as _inspect

    bind = bind if bind is not None else db.session.get_bind()

    def present(table: str, *, needs_school_id: bool) -> bool:
        try:
            insp = _inspect(bind)
            if not insp.has_table(table):
                return False
            if needs_school_id:
                return "school_id" in {c["name"] for c in insp.get_columns(table)}
            return True
        except Exception:  # noqa: BLE001 — no bind / unreadable catalogue
            return False

    statements: list[str] = []
    skipped: list[str] = []

    for table in _TENANT_TABLES:
        if not present(table, needs_school_id=True):
            skipped.append(table)
            continue
        read_arms: list[str] = []
        if expr := _DIRECT_CLASS_ID_COLUMNS.get(table):
            read_arms.append(_class_ids_match(expr))
        if table == "classes":
            read_arms.append(f"(current_setting('{_INDIVIDUAL_GUC}', true) = '1' AND is_public = true)")
        statements += build_policy_ddl(
            table,
            "school_id::text = current_setting('app.current_school_id', true)",
            read_arms,
            [],
        )

    for table, subquery in _INDIRECT_TENANT_TABLES.items():
        if not present(table, needs_school_id=False):
            skipped.append(table)
            continue
        tenant_expr = f"({subquery})::text = current_setting('app.current_school_id', true)"
        read_arms = []
        if expr := _CLASS_ID_EXPRESSIONS.get(table):
            read_arms.append(_class_ids_match(expr))
        write_arms = []
        if table in _USER_OWNED_TABLES:
            read_arms.append(_user_id_arm())
            write_arms.append(_user_id_arm())
        if actor_arm := _ACTOR_OWNED_WRITE_ARMS.get(table):
            write_arms.append(actor_arm)
        statements += build_policy_ddl(table, tenant_expr, read_arms, write_arms)

    for table in _USER_SCOPED_TABLES:
        if not present(table, needs_school_id=False):
            skipped.append(table)
            continue
        statements += build_policy_ddl(table, _user_id_arm(), [], [])

    for table in _USER_SCOPED_WITH_TENANT:
        if not present(table, needs_school_id=False):
            skipped.append(table)
            continue
        statements += build_policy_ddl(
            table,
            _user_id_arm(),
            ["school_id::text = current_setting('app.current_school_id', true)"],
            ["school_id::text = current_setting('app.current_school_id', true)"],
        )

    return statements, skipped


# Tables that reference school_id via a JOIN through another table
# (indirect tenancy — RLS policy uses subquery)
_INDIRECT_TENANT_TABLES: dict[str, str] = {
    # Table: school_id derivation SQL
    #
    # Most of these predate a school_id column: they hang off ``classes`` (or
    # a table that does), and RLS used to skip them with a warning, which left
    # attendance, grades and billing with a single line of defence. The path
    # below restores the database-level floor without duplicating school_id
    # across the schema — a copied column drifts the moment a class moves.
    "announcements": "SELECT c.school_id FROM classes c WHERE c.id = announcements.class_id",
    "assignments": "SELECT c.school_id FROM classes c WHERE c.id = assignments.class_id",
    "attendance": "SELECT c.school_id FROM classes c WHERE c.id = attendance.class_id",
    "class_members": "SELECT c.school_id FROM classes c WHERE c.id = class_members.class_id",
    "grade_categories": "SELECT c.school_id FROM classes c WHERE c.id = grade_categories.class_id",
    "grade_items": "SELECT c.school_id FROM classes c WHERE c.id = grade_items.class_id",
    "lessons": "SELECT c.school_id FROM classes c WHERE c.id = lessons.class_id",
    # ``lessons.class_id`` is NOT NULL; ``lessons.unit_id`` is not. A lesson
    # outside any unit — which is what a draft first draft of a course is —
    # has to keep its own attachments and downloads reachable, so the class is
    # taken from the lesson's own foreign key rather than from its unit.
    "lesson_attachments": (
        "SELECT c.school_id FROM classes c JOIN lessons l ON l.class_id = c.id "
        "WHERE l.id = lesson_attachments.lesson_id"
    ),
    "rubric_criteria": ("SELECT t.school_id FROM rubric_templates t WHERE t.id = rubric_criteria.template_id"),
    "student_progress": "SELECT c.school_id FROM classes c WHERE c.id = student_progress.class_id",
    "subscriptions": "SELECT c.school_id FROM classes c WHERE c.id = subscriptions.class_id",
    "units": "SELECT c.school_id FROM classes c WHERE c.id = units.class_id",
    "video_progress": "SELECT c.school_id FROM classes c WHERE c.id = video_progress.class_id",
    "offline_downloads": (
        "SELECT c.school_id FROM classes c JOIN lessons l ON l.class_id = c.id WHERE l.id = offline_downloads.lesson_id"
    ),
    "manual_payments": (
        "SELECT c.school_id FROM classes c JOIN subscriptions s ON s.class_id = c.id "
        "WHERE s.id = manual_payments.subscription_id"
    ),
    "payment_receipts": (
        "SELECT c.school_id FROM classes c JOIN subscriptions s ON s.class_id = c.id "
        "JOIN manual_payments mp ON mp.subscription_id = s.id "
        "WHERE mp.id = payment_receipts.manual_payment_id"
    ),
    "quiz_attempts": (
        "SELECT c.school_id FROM classes c JOIN quizzes q ON q.class_id = c.id WHERE q.id = quiz_attempts.quiz_id"
    ),
    "answers": (
        "SELECT c.school_id FROM classes c "
        "JOIN quizzes q ON q.class_id = c.id "
        "JOIN quiz_attempts qa ON qa.quiz_id = q.id "
        "WHERE qa.id = answers.attempt_id"
    ),
    "quizzes": "SELECT c.school_id FROM classes c WHERE c.id = quizzes.class_id",
    "grade_entries": (
        "SELECT c.school_id FROM classes c "
        "JOIN grade_items gi ON gi.class_id = c.id "
        "WHERE gi.id = grade_entries.grade_item_id"
    ),
    "submissions": (
        "SELECT c.school_id FROM classes c "
        "JOIN assignments a ON a.class_id = c.id "
        "WHERE a.id = submissions.assignment_id"
    ),
    "proctoring_logs": (
        "SELECT c.school_id FROM classes c "
        "JOIN quizzes q ON q.class_id = c.id "
        "JOIN quiz_attempts qa ON qa.quiz_id = q.id "
        "WHERE qa.id = proctoring_logs.attempt_id"
    ),
}


def set_tenant_context(school_id: int | None) -> None:
    """Set the PostgreSQL session variable for RLS.

    Must be called within an active transaction (before any queries).
    Uses SET LOCAL so the variable auto-resets when the transaction ends.

    Args:
        school_id: The tenant's school ID, or None for super_admin bypass.
    """
    if school_id is None:
        # super_admin: bypass RLS by setting to 0 (no school has id=0)
        db.session.execute(text("SET LOCAL app.current_school_id = '0'"))
        db.session.execute(text("SET LOCAL app.is_super_admin = '1'"))
    else:
        db.session.execute(
            text("SET LOCAL app.current_school_id = :sid"),
            {"sid": str(school_id)},
        )
        db.session.execute(text("SET LOCAL app.is_super_admin = '0'"))
    # A class list inherited from an earlier scope in the same transaction would
    # keep granting that scope's content; pin it to empty unless the caller
    # re-derives it. ``''`` splits to {''}, which matches no id.
    db.session.execute(text(f"SET LOCAL {_CLASS_IDS_GUC} = ''"))
    db.session.execute(text(f"SET LOCAL {_INDIVIDUAL_GUC} = '0'"))


def reset_tenant_context() -> None:
    """Reset the session variables (defensive — SET LOCAL auto-resets)."""
    try:
        db.session.execute(text("RESET app.current_school_id"))
        db.session.execute(text("RESET app.is_super_admin"))
        db.session.execute(text(f"RESET {_CLASS_IDS_GUC}"))
        db.session.execute(text(f"RESET {_INDIVIDUAL_GUC}"))
    except Exception:
        pass  # Non-critical: SET LOCAL auto-resets on transaction end


def enable_rls_on_table(
    table_name: str,
    *,
    class_id_expr: str | None = None,
    individual_catalogue: bool = False,
) -> bool:
    """Enable RLS and create the tenant isolation policy for a single table.

    ``class_id_expr`` widens *reads* only: a row whose class the actor is an
    active member of stays visible even when the class belongs to another
    school. Writes keep the plain tenant check, because read access to a class
    is not authority to author inside it.

    ``individual_catalogue`` widens reads to public classes — and only for
    actors flagged ``is_individual``, so ordinary school tenants keep seeing
    their own school alone.

    Idempotent: safe to run multiple times.

    Returns True when a policy was (re)created, False when the table was
    skipped (missing table or missing school_id column — same guard as the
    g1h2i3j4k5l6 migration, so enable_all can never crash at runtime).
    """
    if not _table_exists(table_name):
        logger.warning("rls_skipped", table=table_name, reason="table does not exist")
        return False
    if not _has_column(table_name, "school_id"):
        # BUGFIX: several registry entries predate a schema decision (e.g.
        # announcements traces tenancy via classes, not a school_id column).
        # Building a policy against a missing column raises UndefinedColumn.
        logger.warning("rls_skipped", table=table_name, reason="missing school_id column")
        return False

    read_arms: list[str] = []
    if expr := class_id_expr or _DIRECT_CLASS_ID_COLUMNS.get(table_name):
        read_arms.append(_class_ids_match(expr))
    if individual_catalogue:
        read_arms.append(f"(current_setting('{_INDIVIDUAL_GUC}', true) = '1' AND is_public = true)")

    _apply(
        build_policy_ddl(
            table_name,
            "school_id::text = current_setting('app.current_school_id', true)",
            read_arms,
            [],
        )
    )
    logger.info("rls_policy_created", table=table_name, policy=f"tenant_isolation_{table_name}")
    return True


def _apply(statements: list[str]) -> None:
    for statement in statements:
        db.session.execute(text(statement))


def enable_rls_on_indirect_table(
    table_name: str,
    subquery: str,
    *,
    class_id_expr: str | None = None,
) -> bool:
    """Enable RLS on a table where school_id is derived via subquery.

    Used for tables like quiz_attempts that don't directly have school_id
    but can be traced to one through joins.

    ``class_id_expr`` widens *reads* only, and never widens a table's writes to
    somebody else's row: see ``_CLASS_IDS_GUC``.

    Returns True when a policy was (re)created, False when skipped.
    """
    if not _table_exists(table_name):
        logger.warning("rls_skipped", table=table_name, reason="table does not exist")
        return False

    read_arms: list[str] = []
    write_arms: list[str] = []
    if expr := class_id_expr or _CLASS_ID_EXPRESSIONS.get(table_name):
        read_arms.append(_class_ids_match(expr))
    if table_name in _USER_OWNED_TABLES:
        read_arms.append(_user_id_arm())
        write_arms.append(_user_id_arm())
    if actor_arm := _ACTOR_OWNED_WRITE_ARMS.get(table_name):
        write_arms.append(actor_arm)

    _apply(
        build_policy_ddl(
            table_name,
            f"({subquery})::text = current_setting('app.current_school_id', true)",
            read_arms,
            write_arms,
        )
    )
    logger.info("rls_policy_created_indirect", table=table_name, policy=f"tenant_isolation_{table_name}")
    return True


def enable_rls_on_user_scoped_table(
    table_name: str,
    include_tenant_arm: bool = False,
    include_class_arm: str | None = None,
) -> bool:
    """Enable RLS for a table scoped by the acting user, not by tenant.

    Used for ``audit_logs`` (a row records what one actor did) and for
    ``user_role_links`` (the table the tenant is derived from — a purely
    school-scoped policy there would be circular). ``super_admin`` keeps full
    visibility.

    ``include_tenant_arm`` adds the ``app.current_school_id`` branch, which
    ``user_role_links`` needs: scoping it to the actor alone hides every
    colleague's links, so ``User.school_id`` comes back empty for anyone else
    and same-school access checks deny legitimate requests. It is not circular,
    because the tenant is resolved from the actor's own links — visible through
    the user arm — before the school arm is ever consulted.

    ``include_class_arm`` adds the membership branch to reads, which is how an
    individual reaches content in a school they hold no role link to. It is
    added to ``USING`` only: this table's writes are the tenant's own rows, and
    being able to *read* a class is not authority to author inside it.

    The identity comparison uses ``::text`` so an unset ``app.current_user_id``
    (empty string) matches nothing instead of raising ``invalid input syntax``
    for every row — and it cannot be pushed into the ``OR``'s other branch,
    because PostgreSQL does not promise to evaluate ``OR`` left to right.

    Returns True when a policy was (re)created, False when skipped.
    """
    if not _table_exists(table_name):
        logger.warning("rls_skipped", table=table_name, reason="table does not exist")
        return False

    school_arm = "school_id::text = current_setting('app.current_school_id', true)"
    read_arms = [school_arm] if include_tenant_arm else []
    if include_class_arm:
        read_arms.append(_class_ids_match(include_class_arm))
    write_arms = [school_arm] if include_tenant_arm else []

    _apply(build_policy_ddl(table_name, _user_id_arm(), read_arms, write_arms))
    logger.info("rls_policy_created_user_scoped", table=table_name, policy=f"tenant_isolation_{table_name}")
    return True


def enable_all_rls_policies() -> None:
    """Enable RLS on all tenant-scoped tables.  Call from Alembic migration.

    The DDL is built by ``build_all_policy_ddl`` — the same function the
    migration calls — so a table cannot end up with one policy in the database
    and another in the code that claims to describe it.
    """
    statements, skipped = build_all_policy_ddl()
    _apply(statements)
    db.session.commit()
    logger.info("all_rls_policies_enabled", tables=len(statements) // 4)
    if skipped:
        # Declined by one loop and covered by another is the normal case here;
        # what this warns about is a table that ends up with no policy at all.
        logger.info("rls_declined_by_a_loop", tables=sorted(skipped))


# ══════════════════════════════════════════════════════════════════════════
# Platform scope — writes that belong to the platform, not to any tenant
# ══════════════════════════════════════════════════════════════════════════
#
# A few rows belong to the platform rather than to a school: the system
# school's own grade levels, for instance. Seeding them is what
# ``get_or_create_system_school`` does, and an anonymous registration request
# has no tenant to seed them as — it 500s with "new row violates row-level
# security policy for table grades", pointing at the schema instead of at the
# request that had nothing to do with a tenant.
#
# The obvious fix — a policy arm granting anyone access to rows whose school
# has ``is_system`` — trades a 500 for a hole, because that arm would also let
# an ordinary tenant write into the system school. So the elevation is scoped
# to the operation instead of to the data, and the data keeps its policy.
#
# Re-pinning matters as much as the initial SET: ``tx()`` commits and hands the
# connection back to the pool, so the next statement may land on a connection
# with the variables unset. Setting them once on the session is the bug this
# pattern exists to not have.
_platform_scope = threading.local()


@contextmanager
def platform_scope() -> Iterator[None]:
    """Run a block as the platform rather than as any tenant.

    Grants full RLS visibility for the duration. Intended for platform-owned
    writes only — never wrap user input in it.
    """
    depth = getattr(_platform_scope, "depth", 0)
    _platform_scope.depth = depth + 1
    try:
        db.session.execute(text("SET LOCAL app.is_super_admin = '1'"))
        db.session.execute(text("SET LOCAL app.current_school_id = '0'"))
        db.session.execute(text(f"SET LOCAL {_CLASS_IDS_GUC} = ''"))
        yield
    finally:
        _platform_scope.depth = depth
        if depth == 0:
            try:
                # Ending the transaction drops every SET LOCAL above, so no
                # elevated session is left open for a later borrower.
                db.session.rollback()
            except Exception:
                logger.exception("platform_rls_scope_reset_failed")


@event.listens_for(db.session, "after_begin")
def _repin_platform_scope(session, transaction, connection) -> None:
    """Re-apply the elevation to every transaction begun inside the scope."""
    if not getattr(_platform_scope, "depth", 0):
        return
    connection.execute(text("SET LOCAL app.is_super_admin = '1'"))
    connection.execute(text("SET LOCAL app.current_school_id = '0'"))


def disable_all_rls_policies() -> None:
    """Disable RLS on all tables.  Used for rollback migration."""
    all_tables = _TENANT_TABLES + list(_INDIRECT_TENANT_TABLES.keys()) + _USER_SCOPED_TABLES + _USER_SCOPED_WITH_TENANT
    for table in all_tables:
        policy_name = f"tenant_isolation_{table}"
        try:
            db.session.execute(text(f"DROP POLICY IF EXISTS {policy_name} ON {table}"))
            db.session.execute(text(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY"))
        except Exception:
            pass  # Table may not exist in test environment
    db.session.commit()
