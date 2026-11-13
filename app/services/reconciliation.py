"""AZ-PH2: Automated payment reconciliation engine.

Compares internal ``wallet_transactions`` / ``manual_payments`` against
expected ledger totals and flags discrepancies into a structured report.
Gateway settlement ingestion is pluggable via ``SettlementSource``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol

from app.extensions import db


class SettlementSource(Protocol):
    def fetch(self, since: datetime | None = None) -> Iterable[dict]: ...


@dataclass
class ReconciliationItem:
    reference: str
    kind: str  # 'wallet_tx' | 'manual_payment' | 'gateway'
    expected: Decimal
    actual: Decimal
    discrepancy: Decimal
    status: str  # 'ok' | 'mismatch' | 'missing_internal' | 'missing_gateway'


@dataclass
class ReconciliationReport:
    generated_at: datetime
    items: list[ReconciliationItem] = field(default_factory=list)
    total_discrepancy: Decimal = Decimal("0")

    def add(self, item: ReconciliationItem) -> None:
        self.items.append(item)
        self.total_discrepancy += item.discrepancy


def _sum_wallet_tx() -> dict[str, Decimal]:
    from app.models.wallet import WalletTransaction

    rows = db.session.query(WalletTransaction).all()
    out: dict[str, Decimal] = {}
    for r in rows:
        key = r.transaction_hash or f"tx:{r.id}"
        out[key] = Decimal(str(r.amount or 0))
    return out


def _sum_manual_payments() -> dict[str, Decimal]:
    from app.models.billing import ManualPayment

    rows = db.session.query(ManualPayment).all()
    out: dict[str, Decimal] = {}
    for r in rows:
        out[f"mp:{r.id}"] = Decimal(str(r.amount or 0))
    return out


def reconcile(since: datetime | None = None, settlement_source: SettlementSource | None = None) -> ReconciliationReport:
    """Run a reconciliation pass and return a structured report."""
    report = ReconciliationReport(generated_at=datetime.now(UTC))

    internal: dict[str, tuple[str, Decimal]] = {}
    for k, v in _sum_wallet_tx().items():
        internal[k] = ("wallet_tx", v)
    for k, v in _sum_manual_payments().items():
        internal[k] = ("manual_payment", v)

    gateway: dict[str, Decimal] = {}
    if settlement_source is not None:
        for s in settlement_source.fetch(since=since):
            ref = s.get("reference") or s.get("id")
            gateway[str(ref)] = Decimal(str(s.get("amount", 0)))

    # Internal vs gateway
    all_refs = set(internal) | set(gateway)
    for ref in sorted(all_refs):
        if ref in internal and ref in gateway:
            kind, exp = internal[ref]
            act = gateway[ref]
            disc = (exp - act).copy_abs() if False else (exp - act)
            status = "ok" if exp == act else "mismatch"
            report.add(ReconciliationItem(ref, kind, exp, act, disc, status))
        elif ref in internal:
            kind, exp = internal[ref]
            report.add(ReconciliationItem(ref, kind, exp, Decimal(0), exp, "missing_gateway"))
        else:
            act = gateway[ref]
            report.add(ReconciliationItem(ref, "gateway", Decimal(0), act, act, "missing_internal"))

    return report
