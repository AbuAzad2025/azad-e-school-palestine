"""Manual payment expiry — allow the ``expired`` status

Revision ID: s2t3u4v5w6x7
Revises: r1s2t3u4v5w6
Create Date: 2026-10-16 00:00:00.000000

Why this migration exists
-------------------------
AZ-P1-09: the pending-payment cleanup job was supposed to mark payments older
than 24 hours as ``expired``, but the job's inline script crashed on every run
(``datetime``/``timedelta`` were never imported) so no payment ever left
``pending``. Once the job is a real, tested CLI, the transition it performs must
be representable: ``ck_manual_payment_status`` (added by a7b8c9d0e1f2) allowed
only ``pending``/``approved``/``rejected`` and would have rejected the very
write the job exists to make — a constraint that silently forbids the state
machine its own code assumes.

Widening a CHECK constraint means dropping and recreating it: PostgreSQL has no
``ALTER CONSTRAINT`` for the expression. The drop is guarded so the revision is
re-runnable, and the recreate immediately follows, so no window exists in which
the table is unconstrained while a writer is active — Alembic runs migrations in
one transaction per revision.

Why the downgrade reopens rows
------------------------------
``expired`` has no representation in the old constraint, so the downgrade first
returns ``expired`` rows to ``pending`` (their state before this feature
existed, and the only value that keeps a pending subscription payable) and then
re-adds the three-value constraint. Reverting a status migration cannot be
lossless in both directions; this is the documented, non-destructive direction.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "s2t3u4v5w6x7"
down_revision = "r1s2t3u4v5w6"
branch_labels = None
depends_on = None

_OLD_VALUES = "'pending', 'approved', 'rejected'"
_NEW_VALUES = "'pending', 'approved', 'rejected', 'expired'"


def upgrade() -> None:
    op.execute("ALTER TABLE manual_payments DROP CONSTRAINT IF EXISTS ck_manual_payment_status")  # nosec B608 — ثابت
    op.execute(
        f"ALTER TABLE manual_payments ADD CONSTRAINT ck_manual_payment_status CHECK (status IN ({_NEW_VALUES}))"  # nosec B608 — قيم ثابتة في الكود لا مدخلات
    )


def downgrade() -> None:
    op.execute("UPDATE manual_payments SET status = 'pending' WHERE status = 'expired'")  # nosec B608 — ثابت
    op.execute("ALTER TABLE manual_payments DROP CONSTRAINT IF EXISTS ck_manual_payment_status")  # nosec B608 — ثابت
    op.execute(
        f"ALTER TABLE manual_payments ADD CONSTRAINT ck_manual_payment_status CHECK (status IN ({_OLD_VALUES}))"  # nosec B608 — قيم ثابتة
    )
