"""AZ-PH2: Deterministic multi-currency / FX conversion service.

Provides rate lookup, precision rounding (ROUND_HALF_UP to the currency's
minor-unit precision) and audit metadata recording for cross-currency
wallet/billing operations. Rates are supplied by the caller (or a pluggable
provider) so the service stays deterministic and testable without network.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Protocol

# Minor-unit precision per ISO-4217 currency code (subset; extend as needed).
CURRENCY_PRECISION: dict[str, int] = {
    "ILS": 2,
    "USD": 2,
    "EUR": 2,
    "GBP": 2,
    "JOD": 3,
}


class RateProvider(Protocol):
    def get_rate(self, base: str, quote: str) -> Decimal: ...


@dataclass(frozen=True)
class ConversionResult:
    amount: Decimal
    from_currency: str
    to_currency: str
    rate: Decimal
    converted: Decimal
    to_precision: int
    timestamp: datetime
    audit: dict


def _q(value: Decimal, places: int) -> Decimal:
    quant = Decimal(1).scaleb(-places)  # 10^-places
    return value.quantize(quant, rounding=ROUND_HALF_UP)


def convert(
    amount: Decimal | str | int | float,
    from_currency: str,
    to_currency: str,
    rate_provider: RateProvider | Callable[[str, str], Decimal] | None = None,
    rate: Decimal | None = None,
    *,
    timestamp: datetime | None = None,
) -> ConversionResult:
    """Convert ``amount`` from ``from_currency`` to ``to_currency``.

    Either ``rate`` (explicit) or ``rate_provider`` must be supplied. When
    both currencies are identical the rate is 1 and no provider is needed.
    """
    amt = Decimal(str(amount))
    fc = from_currency.upper()
    tc = to_currency.upper()
    if amt < 0:
        raise ValueError("amount must be non-negative")
    if fc not in CURRENCY_PRECISION:
        raise ValueError(f"unknown currency: {fc}")
    if tc not in CURRENCY_PRECISION:
        raise ValueError(f"unknown currency: {tc}")

    if fc == tc:
        r = Decimal(1)
    elif rate is not None:
        r = Decimal(str(rate))
    elif rate_provider is not None:
        if hasattr(rate_provider, "get_rate"):
            r = Decimal(str(rate_provider.get_rate(fc, tc)))
        else:
            r = Decimal(str(rate_provider(fc, tc)))
    else:
        raise ValueError("rate or rate_provider required for cross-currency conversion")

    if r <= 0:
        raise ValueError("rate must be positive")

    places = CURRENCY_PRECISION[tc]
    converted = _q(amt * r, places)
    ts = timestamp or datetime.now(UTC)
    audit = {
        "from": fc,
        "to": tc,
        "input_amount": str(amt),
        "rate": str(r),
        "output_amount": str(converted),
        "precision": places,
        "timestamp": ts.isoformat(),
    }
    return ConversionResult(
        amount=amt,
        from_currency=fc,
        to_currency=tc,
        rate=r,
        converted=converted,
        to_precision=places,
        timestamp=ts,
        audit=audit,
    )
