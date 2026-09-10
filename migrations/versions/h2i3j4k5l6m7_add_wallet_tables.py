"""wallet tables — create wallets & wallet_transactions (were missing from schema)

Revision ID: h2i3j4k5l6m7
Revises: g1h2i3j4k5l6
Create Date: 2026-09-09

P1-WALLET-02: جدولا المحفظة لم يُنشآ في أي migration سابق رغم وجود
الموديلات والخدمة — هذا الإصلاح يضيفهما مع الفهارس والقيود.
يعمل بشكل idempotent (يتخطى إن وُجدت الجداول).
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "h2i3j4k5l6m7"
down_revision = "g1h2i3j4k5l6"
branch_labels = None
depends_on = None


def _inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def _table_exists(table_name: str) -> bool:
    return table_name in _inspector().get_table_names()


def upgrade() -> None:
    if not _table_exists("wallets"):
        op.create_table(
            "wallets",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("school_id", sa.BigInteger(), nullable=False),
            sa.Column("user_id", sa.BigInteger(), nullable=False),
            sa.Column("balance", sa.Numeric(10, 2), nullable=False, server_default="0"),
            sa.Column("currency", sa.String(length=8), nullable=False, server_default="ILS"),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["school_id"], ["schools.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("school_id", "user_id", "currency", name="uq_wallet_owner"),
        )
        op.create_index("ix_wallets_school", "wallets", ["school_id"])
        op.create_index("ix_wallets_user", "wallets", ["user_id"])

    if not _table_exists("wallet_transactions"):
        op.create_table(
            "wallet_transactions",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("school_id", sa.BigInteger(), nullable=False),
            sa.Column("source_wallet_id", sa.BigInteger(), nullable=True),
            sa.Column("destination_wallet_id", sa.BigInteger(), nullable=True),
            sa.Column("amount", sa.Numeric(10, 2), nullable=False),
            sa.Column("currency", sa.String(length=8), nullable=False, server_default="ILS"),
            sa.Column("transaction_type", sa.String(length=40), nullable=False),
            sa.Column("transaction_hash", sa.String(length=64), nullable=True),
            sa.Column("idempotency_key", sa.String(length=120), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("reference_type", sa.String(length=60), nullable=True),
            sa.Column("reference_id", sa.BigInteger(), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="completed"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["school_id"], ["schools.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["source_wallet_id"], ["wallets.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["destination_wallet_id"], ["wallets.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("idempotency_key", name="uq_wallet_tx_idempotency"),
            sa.CheckConstraint("amount >= 0", name="ck_wallet_tx_amount_nonneg"),
        )
        op.create_index("ix_wallet_tx_school", "wallet_transactions", ["school_id"])
        op.create_index("ix_wallet_tx_source", "wallet_transactions", ["source_wallet_id"])
        op.create_index("ix_wallet_tx_dest", "wallet_transactions", ["destination_wallet_id"])
        op.create_index("ix_wallet_tx_idem", "wallet_transactions", ["idempotency_key"])


def downgrade() -> None:
    if _table_exists("wallet_transactions"):
        op.drop_table("wallet_transactions")
    if _table_exists("wallets"):
        op.drop_table("wallets")
