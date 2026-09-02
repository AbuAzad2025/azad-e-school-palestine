"""Add RLS tenant isolation policies

Revision ID: g1h2i3j4k5l6
Revises: a7b8c9d0e1f2
Create Date: 2026-09-01 00:00:00.000000

P3-01: Row Level Security as secondary fail-safe behind scope_by_school().
P3-02: Session variables set via SET LOCAL in app/core/tenancy.py.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "g1h2i3j4k5l6"
down_revision = "a7b8c9d0e1f2"
branch_labels = None
depends_on = None


def _inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def _table_exists(table_name: str) -> bool:
    return table_name in _inspector().get_table_names()


def _has_column(table_name: str, column_name: str) -> bool:
    try:
        cols = {c["name"] for c in _inspector().get_columns(table_name)}
        return column_name in cols
    except Exception:
        return False


def _enable_rls_direct(table_name: str) -> None:
    """Enable RLS with direct school_id comparison.

    Skips tables that don't exist or lack a school_id column.
    """
    if not _table_exists(table_name) or not _has_column(table_name, "school_id"):
        return
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
                OR school_id = current_setting('app.current_school_id', true)::bigint
            )
            WITH CHECK (
                current_setting('app.is_super_admin', true) = '1'
                OR school_id = current_setting('app.current_school_id', true)::bigint
            )
        """
    )


def _enable_rls_indirect(table_name: str, subquery: str) -> None:
    """Enable RLS with indirect school_id via subquery.

    Skips if the target table is missing.
    """
    if not _table_exists(table_name):
        return
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
                OR ({subquery}) = current_setting('app.current_school_id', true)::bigint
            )
            WITH CHECK (
                current_setting('app.is_super_admin', true) = '1'
                OR ({subquery}) = current_setting('app.current_school_id', true)::bigint
            )
        """
    )


def upgrade() -> None:
    # ── Tables with direct school_id column ──────────────────────────
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

    for table in _DIRECT_TENANT_TABLES:
        _enable_rls_direct(table)

    # ── Tables with indirect tenancy (school_id via JOIN) ────────────
    _INDIRECT_TENANT_TABLES = {
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

    for table, subquery in _INDIRECT_TENANT_TABLES.items():
        _enable_rls_indirect(table, subquery)


def downgrade() -> None:
    _ALL_TABLES = [
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
        "quizzes",
        "quiz_attempts",
        "answers",
        "submissions",
        "proctoring_logs",
    ]
    for table in _ALL_TABLES:
        if not _table_exists(table):
            continue
        policy = f"tenant_isolation_{table}"
        op.execute(f"DROP POLICY IF EXISTS {policy} ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
