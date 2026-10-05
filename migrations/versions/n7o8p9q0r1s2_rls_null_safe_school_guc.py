"""Make the g1h2i3j4k5l6 policies null-safe when the tenant GUC is unset

Revision ID: n7o8p9q0r1s2
Revises: m6n7o8p9q0r1
Create Date: 2026-10-04 00:00:00.000000

Why this migration exists
-------------------------
g1h2i3j4k5l6 built its policies by casting the tenant variable to bigint::

    school_id = current_setting('app.current_school_id', true)::bigint

`current_setting(..., true)` returns the *text* ``''`` for a custom GUC that
was never set, and ``''::bigint`` raises ``invalid input syntax``. Because
PostgreSQL gives no guarantee about which arm of an ``OR`` it evaluates, that
cast was reached even when the super-admin arm was already true — so a session
that had not called ``set_tenant_for_request`` did not merely fail to see
tenant rows, it raised::

    DataError: invalid input syntax for type bigint: ""

This is reachable outside the request cycle (background jobs, CLI scripts,
anything using the app's own engine), so it is a production bug and not only a
test-fixture problem.

The fix is the same shape l5m6n7o8p9q0 already adopted for the tables it
touched: compare as text, so an unset variable simply matches nothing instead
of exploding. ``school_id::text = current_setting(...)`` is total over the
inputs a tenant id can actually take.

Scope is deliberately limited to the tables g1h2i3j4k5l6 created with the
bigint cast, plus ``whatsapp_links`` — k5l6m7n8o9p0 introduced that table
afterwards and copied the same cast into its policy, so it has the same
latent failure. l5m6n7o8p9q0 rewrote a later batch already, and re-issuing
those here would be a no-op at best.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "n7o8p9q0r1s2"
down_revision = "m6n7o8p9q0r1"
branch_labels = None
depends_on = None

# Mirrors g1h2i3j4k5l6's own lists — the same tables, in the same order.
_DIRECT_TENANT_TABLES = [
    "academic_events",
    "assignments",
    "attendance",
    "certificate_templates",
    "class_members",
    "classes",
    "discount_codes",
    "grade_categories",
    "grade_entries",
    "grade_items",
    "grades",
    "lesson_attachments",
    "lessons",
    "manual_payments",
    "offline_downloads",
    "onboarding_progress",
    "payment_receipts",
    "question_bank",
    "rubric_criteria",
    "rubric_templates",
    "school_settings",
    "student_progress",
    "subscription_plans",
    "subscriptions",
    "tenant_quotas",
    "units",
    "video_progress",
    "wallets",
    "wallet_transactions",
]

_INDIRECT_TENANT_TABLES = {
    # k5l6m7n8o9p0 added whatsapp_links after g1h2i3j4k5l6 ran, and gave it the
    # same bigint-cast policy. Listed here so it is rewritten too.
    "whatsapp_links": None,
    "quizzes": "SELECT c.school_id FROM classes c WHERE c.id = quizzes.class_id",
    "quiz_attempts": (
        "SELECT c.school_id FROM classes c "
        "JOIN quizzes q ON q.class_id = c.id "
        "WHERE q.id = quiz_attempts.quiz_id"
    ),
    "answers": (
        "SELECT c.school_id FROM classes c "
        "JOIN quizzes q ON q.class_id = c.id "
        "JOIN quiz_attempts qa ON qa.quiz_id = q.id "
        "WHERE qa.id = answers.attempt_id"
    ),
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


def _table_exists(table_name: str) -> bool:
    return table_name in sa.inspect(op.get_bind()).get_table_names()


def _has_column(table_name: str, column_name: str) -> bool:
    """g1h2i3j4k5l6 only enabled its direct policies on tables that actually
    carry ``school_id``; entries without it were skipped. Rewriting them would
    raise UndefinedColumn, so the same guard applies here."""
    return column_name in {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table_name)}


def _rewrite_direct(table_name: str) -> None:
    policy = f"tenant_isolation_{table_name}"
    op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS {policy} ON {table_name}")
    op.execute(
        f"""
        CREATE POLICY {policy} ON {table_name}
            FOR ALL
            USING (
                current_setting('app.is_super_admin', true) = '1'
                OR school_id::text = current_setting('app.current_school_id', true)
            )
            WITH CHECK (
                current_setting('app.is_super_admin', true) = '1'
                OR school_id::text = current_setting('app.current_school_id', true)
            )
        """
    )


def _rewrite_indirect(table_name: str, subquery: str | None) -> None:
    # A None subquery means the table carries school_id directly; only its
    # policy text came from a different migration.
    school_expr = "school_id::text" if subquery is None else f"({subquery})::text"
    policy = f"tenant_isolation_{table_name}"
    op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS {policy} ON {table_name}")
    op.execute(
        f"""
        CREATE POLICY {policy} ON {table_name}
            FOR ALL
            USING (
                current_setting('app.is_super_admin', true) = '1'
                OR {school_expr} = current_setting('app.current_school_id', true)
            )
            WITH CHECK (
                current_setting('app.is_super_admin', true) = '1'
                OR {school_expr} = current_setting('app.current_school_id', true)
            )
        """
    )


def _rewrite_bigint_policies() -> None:
    for table in _DIRECT_TENANT_TABLES:
        if _table_exists(table) and _has_column(table, "school_id"):
            _rewrite_direct(table)
    for table, subquery in _INDIRECT_TENANT_TABLES.items():
        if _table_exists(table):
            _rewrite_indirect(table, subquery)


def upgrade() -> None:
    _rewrite_bigint_policies()


def downgrade() -> None:
    """Restore the bigint cast exactly as g1h2i3j4k5l6 left it."""
    for table in _DIRECT_TENANT_TABLES:
        if not _table_exists(table) or not _has_column(table, "school_id"):
            continue
        policy = f"tenant_isolation_{table}"
        op.execute(f"DROP POLICY IF EXISTS {policy} ON {table}")
        op.execute(
            f"""
            CREATE POLICY {policy} ON {table}
                FOR ALL
                USING (
                    current_setting('app.is_super_admin', true) = '1'
                    OR school_id = current_setting('app.current_school_id', true)::bigint
                )
                WITH CHECK (
                    current_setting('app.is_super_admin', true) = '1'
                    OR school_id = current_setting('app.current_school_id', true)::bigint
                )
            """
        )
    for table, subquery in _INDIRECT_TENANT_TABLES.items():
        if not _table_exists(table):
            continue
        school_expr = "school_id" if subquery is None else f"({subquery})"
        policy = f"tenant_isolation_{table}"
        op.execute(f"DROP POLICY IF EXISTS {policy} ON {table}")
        op.execute(
            f"""
            CREATE POLICY {policy} ON {table}
                FOR ALL
                USING (
                    current_setting('app.is_super_admin', true) = '1'
                    OR {school_expr} = current_setting('app.current_school_id', true)::bigint
                )
                WITH CHECK (
                    current_setting('app.is_super_admin', true) = '1'
                    OR {school_expr} = current_setting('app.current_school_id', true)::bigint
                )
            """
        )