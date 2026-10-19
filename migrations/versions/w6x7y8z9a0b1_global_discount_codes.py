"""كوبونات المنصة العامة — ذراع ``school_id IS NULL`` على discount_codes

Revision ID: w6x7y8z9a0b1
Revises: v5w6x7y8z9a0
Create Date: 2026-10-19 00:00:00.000000

Why this migration exists
-------------------------
A super_admin used to create coupons with a hard-coded ``school_id = 1``
fallback, because the tenant policy on ``discount_codes`` only accepts a row
whose ``school_id`` equals the caller's school. A platform-wide coupon is
instead a row with ``school_id IS NULL`` — a code that applies in every
school.

That row is invisible to every tenant under the old policy, so
``validate_discount_code`` would answer "invalid code" for a code the platform
published, and the atomic ``used_count`` increment would be rejected by
``WITH CHECK``. The runtime builder in ``app.core.rls`` now adds the
``school_id IS NULL`` arm to both arms of this table's policy:

  * reads — a tenant must be able to see and validate a global code;
  * writes — redeeming it increments the shared counter in the same statement.

No tenant-owned row becomes visible: the arm matches only rows that belong to
no school. Creating a global code is gated in the service layer (the route
passes ``None`` only for super_admin), and a school admin keeps inserting
rows scoped to their own school.

This migration replays the live builder, the pattern set by
``p9q0r1s2t3u4``: deployed databases carry exactly the policy text the
runtime enforces, so the two cannot drift apart. Downgrade rebuilds the same
policies — the actual "before" state is the previous revision of the builder,
not something a downgrade can reconstruct once the code has moved on.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "w6x7y8z9a0b1"
down_revision = "v5w6x7y8z9a0"
branch_labels = None
depends_on = None


def _rebuild() -> list[str]:
    from app.core.rls import build_all_policy_ddl

    statements, skipped = build_all_policy_ddl(op.get_bind())
    if skipped:
        print(f"[rls] tables without a policy in this database: {sorted(skipped)}")
    return statements


def upgrade() -> None:
    for statement in _rebuild():
        op.execute(statement)


def downgrade() -> None:
    for statement in _rebuild():
        op.execute(statement)
