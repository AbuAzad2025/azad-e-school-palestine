"""Let a tenant's members read each other's role links

Revision ID: o8p9q0r1s2t3
Revises: n7o8p9q0r1s2
Create Date: 2026-10-04 00:00:00.000000

Why this migration exists
-------------------------
l5m6n7o8p9q0 scoped ``user_role_links`` by the acting user alone, to avoid the
circularity of a tenant policy on the table the tenant is derived from. The
circularity is real but the conclusion was too strong: scoping by user *only*
means an administrator cannot see anybody's links but their own.

``User.school_id`` and ``User.belongs_to_school`` read ``self.role_links``, and
``assert_user_belongs_to_accessible_school`` compares a target user's link
schools against the caller's. With only the actor's own links visible, every
colleague resolves to an empty set, so ``/api/v1/users/<id>`` aborted 403 for a
student in the administrator's *own* school — a real denial of legitimate
access, not a test artifact.

The policy therefore gains a tenant arm alongside the user arm. This is not
circular: ``app.current_school_id`` is derived from the actor's own links,
which the user arm already exposes, and is only then used to widen visibility
*within* that school. Resolution still cannot bootstrap from a school it has
not yet resolved.

``audit_logs`` is deliberately left alone. A row there records what one actor
did, and the same widening would hand every teacher the ability to read every
other teacher's trail. Only the membership table is widened.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "o8p9q0r1s2t3"
down_revision = "n7o8p9q0r1s2"
branch_labels = None
depends_on = None

TABLE = "user_role_links"
POLICY = f"tenant_isolation_{TABLE}"

# The user arm comes first so the actor's own links stay visible even if no
# tenant has been resolved yet (super_admin resolves to school 0).
_WIDENED = """
    USING (
        current_setting('app.is_super_admin', true) = '1'
        OR user_id::text = current_setting('app.current_user_id', true)
        OR school_id::text = current_setting('app.current_school_id', true)
    )
    WITH CHECK (
        current_setting('app.is_super_admin', true) = '1'
        OR user_id::text = current_setting('app.current_user_id', true)
        OR school_id::text = current_setting('app.current_school_id', true)
    )
"""

_USER_ONLY = """
    USING (
        current_setting('app.is_super_admin', true) = '1'
        OR user_id::text = current_setting('app.current_user_id', true)
    )
    WITH CHECK (
        current_setting('app.is_super_admin', true) = '1'
        OR user_id::text = current_setting('app.current_user_id', true)
    )
"""


def _table_exists() -> bool:
    return TABLE in sa.inspect(op.get_bind()).get_table_names()


def _recreate(body: str) -> None:
    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS {POLICY} ON {TABLE}")
    op.execute(
        f"""
        CREATE POLICY {POLICY} ON {TABLE}
            FOR ALL{body}
        """
    )


def upgrade() -> None:
    if _table_exists():
        _recreate(_WIDENED)


def downgrade() -> None:
    if _table_exists():
        _recreate(_USER_ONLY)