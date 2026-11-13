"""Complete RLS coverage on the remaining tenant tables (Phase 1 hardening)

Revision ID: x7y8z9a0b1c2
Revises: w6x7y8z9a0b1
Create Date: 2026-11-13 00:00:00.000000

Why this migration exists
-------------------------
``docs/SYSTEM_SPECIFICATION.md`` §5.2 flagged 18 tables as lacking
Row-Level Security. Most of them already received policies in
``l5m6n7o8p9q0`` / ``g1h2i3j4k5l6``, but ``wallet_topup_requests`` (which
carries a direct ``school_id``) never did, and a fresh audit could not
prove the other 17 were actually protected on every database. This
migration is idempotent: it (re)applies ``USING`` + ``WITH CHECK``
policies to all 18 tables so that, regardless of which prior migrations
ran, every one of them ends up with exactly one policy, null-safe GUC
handling, and (for tables without a direct ``school_id``) a subquery-based
policy against its parent tenant.

Tables covered
--------------
Direct (school_id column): announcements*, assignments*, attendance*,
class_members*, grade_categories*, grade_items*, lessons*, lesson_attachments*,
manual_payments*, offline_downloads*, payment_receipts*, rubric_criteria*,
student_progress*, subscriptions*, units*, video_progress*, wallet_topup_requests.
Indirect (subquery): as listed in app.core.rls._INDIRECT_TENANT_TABLES.
User-scoped: audit_logs.

* Some of these carry both a school_id column and a class_id foreign key;
  the direct policy on school_id is authoritative (matches _TENANT_TABLES).
"""

import sqlalchemy as sa
from alembic import op

from app.core.rls import (
    _CLASS_ID_EXPRESSIONS,
    _INDIRECT_TENANT_TABLES,
    _USER_SCOPED_TABLES,
)

revision = "x7y8z9a0b1c2"
down_revision = "w6x7y8z9a0b1"
branch_labels = None
depends_on = None

_TABLES = [
    "announcements",
    "assignments",
    "attendance",
    "audit_logs",
    "class_members",
    "grade_categories",
    "grade_items",
    "lesson_attachments",
    "lessons",
    "manual_payments",
    "offline_downloads",
    "payment_receipts",
    "rubric_criteria",
    "student_progress",
    "subscriptions",
    "units",
    "video_progress",
    "wallet_topup_requests",
]


def _table_exists(table_name: str) -> bool:
    return table_name in sa.inspect(op.get_bind()).get_table_names()


def _enable_direct(table_name: str) -> None:
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


def _enable_indirect(table_name: str, subquery: str) -> None:
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
                OR ({subquery})::text = current_setting('app.current_school_id', true)
            )
            WITH CHECK (
                current_setting('app.is_super_admin', true) = '1'
                OR ({subquery})::text = current_setting('app.current_school_id', true)
            )
        """
    )


def _enable_user_scoped(table_name: str) -> None:
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
                OR user_id::text = current_setting('app.current_user_id', true)
            )
            WITH CHECK (
                current_setting('app.is_super_admin', true) = '1'
                OR user_id::text = current_setting('app.current_user_id', true)
            )
        """
    )


def upgrade() -> None:
    for table in _TABLES:
        if not _table_exists(table):
            continue
        if table in _USER_SCOPED_TABLES:
            _enable_user_scoped(table)
            continue
        if table in _INDIRECT_TENANT_TABLES:
            _enable_indirect(table, _INDIRECT_TENANT_TABLES[table])
            continue
        # Direct tenant table (school_id column present).
        _enable_direct(table)


def downgrade() -> None:
    for table in _TABLES:
        if not _table_exists(table):
            continue
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON {table}")
        # Only disable RLS if no other policy remains (conservative: leave enabled).
