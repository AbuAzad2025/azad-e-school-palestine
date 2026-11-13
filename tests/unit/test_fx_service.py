from decimal import Decimal

from app.services.fx_service import convert


def test_same_currency_rate_one():
    r = convert("100", "ILS", "ILS")
    assert r.converted == Decimal("100.00")
    assert r.rate == Decimal(1)


def test_cross_currency_rounding():
    r = convert(Decimal("10"), "USD", "ILS", rate=Decimal("3.7"))
    assert r.converted == Decimal("37.00")


def test_jod_precision():
    r = convert(Decimal("1"), "USD", "JOD", rate=Decimal("0.709"))
    assert r.to_precision == 3
    assert r.converted == Decimal("0.709")


def test_negative_amount_rejected():
    import pytest

    with pytest.raises(ValueError):
        convert(-1, "USD", "ILS", rate=Decimal("3.7"))


def test_unknown_currency_rejected():
    import pytest

    with pytest.raises(ValueError):
        convert(1, "XYZ", "ILS", rate=Decimal("3.7"))


def test_rate_provider_callable():
    r = convert(Decimal("5"), "EUR", "USD", rate_provider=lambda b, q: Decimal("1.08"))
    assert r.converted == Decimal("5.40")


def test_audit_metadata():
    r = convert(Decimal("1"), "USD", "ILS", rate=Decimal("3.7"))
    assert r.audit["from"] == "USD"
    assert r.audit["to"] == "ILS"
    assert "timestamp" in r.audit