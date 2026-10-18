"""wallet_topup_requests — AZ-P3-15 parent wallet top-up requests

Revision ID: v5w6x7y8z9a0
Revises: u4v5w6x7y8z9
Create Date: 2026-10-17 00:00:00.000000

Why this migration exists
-------------------------
AZ-P3-15: a linked parent can now *request* a wallet top-up for their child,
but only a school-admin/platform review credits the balance. The request is a
first-class row (payer identity + child + amount + decision trail) instead of
an improvised notification, so nothing reaches ``wallet_transactions`` — and
therefore no balance ever moves — without an explicit approval that keeps the
payer identity attached.

The table carries ``school_id`` and is registered in ``_TENANT_TABLES``, so
build_policy_ddl() (and the Alembic RLS rollout) covers it the same way every
other tenant table is covered — a table created without its policy would be a
tenant hole, which is exactly the class of bug the RLS registry exists to
prevent.

Downgrade drops the table. Rows are requests, not money: nothing in the
ledger references them (the ledger entry only exists after approval), so a
drop is lossless by construction.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect

revision = "v5w6x7y8z9a0"
down_revision = "u4v5w6x7y8z9"
branch_labels = None
depends_on = None


def _table_exists(name: str) -> bool:
    try:
        return sa_inspect(op.get_bind()).has_table(name)
    except Exception:  # pragma: no cover — unreadable catalogue
        return False


def upgrade() -> None:
    if not _table_exists("wallet_topup_requests"):
        op.create_table(
            "wallet_topup_requests",
            sa.Column("id", sa.BigInteger(), primary_key=True),
            sa.Column(
                "school_id",
                sa.BigInteger(),
                sa.ForeignKey("schools.id", name="fk_topup_req_school"),
                nullable=False,
            ),
            sa.Column(
                "parent_id",
                sa.BigInteger(),
                sa.ForeignKey("users.id", name="fk_topup_req_parent"),
                nullable=False,
            ),
            sa.Column(
                "child_user_id",
                sa.BigInteger(),
                sa.ForeignKey("users.id", name="fk_topup_req_child"),
                nullable=False,
            ),
            sa.Column("amount", sa.Numeric(10, 2), nullable=False),
            sa.Column("currency", sa.String(3), nullable=False, server_default="ILS"),
            sa.Column("status", sa.String(10), nullable=False, server_default="pending"),
            sa.Column("note", sa.Text()),
            sa.Column("handled_by", sa.BigInteger(), sa.ForeignKey("users.id", name="fk_topup_req_handler")),
            sa.Column("handled_at", sa.DateTime(timezone=True)),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_wallet_topup_school_id", "wallet_topup_requests", ["school_id"])
        op.create_index("ix_wallet_topup_child", "wallet_topup_requests", ["child_user_id"])
        op.create_index("ix_wallet_topup_pending", "wallet_topup_requests", ["school_id", "status"])


def downgrade() -> None:
    if _table_exists("wallet_topup_requests"):
        op.drop_table("wallet_topup_requests")
