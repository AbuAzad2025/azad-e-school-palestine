"""Tutoring payment dual confirmation — both parties must agree

Revision ID: u4v5w6x7y8z9
Revises: t3u4v5w6x7y8
Create Date: 2026-10-17 00:00:00.000000

Why this migration exists
-------------------------
AZ-P2-13: ``session_pay`` let the *student alone* mark a private session as
``paid`` — a self-attestation on a real money path, with no ledger movement and
no consent from the tutor. The fix is dual confirmation: the student confirms
payment made to the tutor, the tutor confirms receipt, and only then does the
session close as ``paid`` and a ledger entry is written (idempotency keys, so
repeat clicks can never double-book). The two confirmation booleans must be
replicable by the state machine: they record *who agreed and when*, and the
reject action resets them — an ``expired`` paid-at-timestamp would not carry
that information.

Lifecycle of the new columns
----------------------------
The defaults are ``FALSE`` so pre-existing sessions keep their historical
``payment_status`` untouched. The finalization timestamp is only set at the
moment both confirmations exist and the ledger write succeeds.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "u4v5w6x7y8z9"
down_revision = "t3u4v5w6x7y8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tutoring_sessions",
        sa.Column("student_confirmed_payment", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "tutoring_sessions",
        sa.Column("tutor_confirmed_payment", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column("tutoring_sessions", sa.Column("payment_confirmed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    # Reverting cannot know which paid rows were dual-confirmed; the columns and
    # the timestamp are dropped, but the money status those rows already hold is
    # preserved as-is (non-destructive direction).
    op.drop_column("tutoring_sessions", "payment_confirmed_at")
    op.drop_column("tutoring_sessions", "tutor_confirmed_payment")
    op.drop_column("tutoring_sessions", "student_confirmed_payment")
