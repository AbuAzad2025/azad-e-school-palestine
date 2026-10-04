"""Close the RLS coverage gap on class-scoped, wallet and role-link tables

Revision ID: l5m6n7o8p9q0
Revises: k5l6m7n8o9p0
Create Date: 2026-10-04 00:00:00.000000

Why this migration exists
-------------------------
The first RLS rollout (g1h2i3j4k5l6) listed attendance, grades, subscriptions
and 20+ more tables as "tenant tables", then silently skipped every one of
them: they have no ``school_id`` column, so the policy could not be built and
``enable_rls_on_table`` logged a warning and moved on. The result was that the
"second line of defence" existed for 18 tables and nowhere else — attendance,
class membership, grade items, lessons, billing and progress ran on the
application filter alone.

Two ways to close that were available:

1. Add a ``school_id`` column to all of them and maintain it on every write.
2. Point their policies at the tenant they already reach through ``classes``.

This migration takes (2). A copied ``school_id`` is a second source of truth
that goes stale the moment a class is moved or a row is inserted by a path
that forgets the copy; the join is derived, so it cannot drift, and it costs
one primary-key lookup per row. The column-free schema is unchanged.

Three tables are scoped by the acting user rather than the tenant:

* ``user_role_links`` is the table the tenant is *derived from*
  (``User.school_id`` reads it). A tenant policy there is circular — the query
  that resolves the school would be filtered by the school it is resolving.
  Its policy keys on ``app.current_user_id``, which ``set_tenant_for_request``
  now sets on every request (``'0'`` when anonymous).
* ``audit_logs`` follows the same rule: a row records what one actor did.
* ``super_admin`` keeps full visibility through the existing bypass.

Both policies compare identities as text. ``current_setting`` of an unset
custom GUC returns ``''`` and ``''::bigint`` raises ``invalid input syntax``
against *every* row of the table; a text comparison simply matches nothing.
"""

import sqlalchemy as sa
from alembic import op
from app.core.rls import (
    _INDIRECT_TENANT_TABLES,
    _TENANT_TABLES,
    _USER_SCOPED_TABLES,
)

# revision identifiers, used by Alembic.
revision = "l5m6n7o8p9q0"
down_revision = "k5l6m7n8o9p0"
branch_labels = None
depends_on = None

# Tables this migration turns on for the first time. Scoped explicitly so the
# migration can never touch a table that already had a policy from g1h2i3j4k5l6,
# and so ``downgrade()`` reverts exactly what ``upgrade()`` added.
_DIRECT_NEW = ["wallets", "wallet_transactions"]
_INDIRECT_NEW = [
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
]
_USER_SCOPED_NEW = list(_USER_SCOPED_TABLES)


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
    for table in _DIRECT_NEW:
        if table in _TENANT_TABLES and _table_exists(table):
            _enable_direct(table)

    for table in _INDIRECT_NEW:
        if table in _INDIRECT_TENANT_TABLES and _table_exists(table):
            _enable_indirect(table, _INDIRECT_TENANT_TABLES[table])

    for table in _USER_SCOPED_NEW:
        if _table_exists(table):
            _enable_user_scoped(table)


def downgrade() -> None:
    for table in _DIRECT_NEW + _INDIRECT_NEW + _USER_SCOPED_NEW:
        if not _table_exists(table):
            continue
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
