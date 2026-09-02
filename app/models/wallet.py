"""Wallet & Ledger — Double-entry accounting for student balances and tutor payouts.

P7-01: Wallet model with Decimal(10,2) balance per user per school.
P7-02: WalletTransaction double-entry ledger with idempotency.
P7-03: All monetary fields use Numeric(10,2) — never float.
P7-04: school_id on both models for tenancy isolation.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, ForeignKey, Index, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db

from .mixins import PKMixin

if TYPE_CHECKING:
    from app.models.school import School
    from app.models.user import User


class Wallet(PKMixin, db.Model):
    """User wallet — holds balance for a specific school/currency.

    Each user has one wallet per school per currency.
    Balance is Decimal(10,2) — never float for financial data.
    """

    __tablename__ = "wallets"
    __table_args__ = (
        UniqueConstraint("school_id", "user_id", "currency", name="uq_wallet_school_user_currency"),
        Index("ix_wallets_user_id", "user_id"),
        Index("ix_wallets_school_id", "school_id"),
    )

    school_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("schools.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    balance: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=0.00)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="ILS")
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="active")  # active / frozen / closed

    # Relationships
    user: Mapped[User] = relationship("User", foreign_keys=[user_id])
    school: Mapped[School] = relationship("School", foreign_keys=[school_id])

    def __repr__(self) -> str:
        return f"<Wallet {self.id} user={self.user_id} school={self.school_id} balance={self.balance} {self.currency}>"


class WalletTransaction(PKMixin, db.Model):
    """Double-entry ledger transaction.

    Every transfer creates TWO entries (source debit + destination credit)
    linked by the same transaction_hash for audit trail.

    transaction_type categories:
        - transfer: User-to-user transfer
        - tutor_commission: Platform commission from tutoring
        - tutor_payout: Tutor withdrawal
        - subscription_credit: Credit from subscription payment
        - admin_adjustment: Admin manual adjustment
        - refund: Refund from cancelled subscription
    """

    __tablename__ = "wallet_transactions"
    __table_args__ = (
        Index("ix_wallet_tx_school_id", "school_id"),
        Index("ix_wallet_tx_source", "source_wallet_id"),
        Index("ix_wallet_tx_dest", "destination_wallet_id"),
        Index("ix_wallet_tx_idempotency", "idempotency_key", unique=True),
        Index("ix_wallet_tx_hash", "transaction_hash"),
    )

    school_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("schools.id"), nullable=False)
    source_wallet_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("wallets.id"), nullable=True)
    destination_wallet_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("wallets.id"), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="ILS")
    transaction_type: Mapped[str] = mapped_column(String(30), nullable=False)
    transaction_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    reference_type: Mapped[str | None] = mapped_column(String(50))
    reference_id: Mapped[int | None] = mapped_column(BigInteger)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(
        String(10), nullable=False, default="completed"
    )  # completed / reversed / pending

    # Relationships
    source_wallet: Mapped[Wallet | None] = relationship("Wallet", foreign_keys=[source_wallet_id])
    destination_wallet: Mapped[Wallet | None] = relationship("Wallet", foreign_keys=[destination_wallet_id])
    school: Mapped[School] = relationship("School", foreign_keys=[school_id])

    def __repr__(self) -> str:
        return f"<WalletTransaction {self.id} type={self.transaction_type} amount={self.amount} {self.currency}>"
