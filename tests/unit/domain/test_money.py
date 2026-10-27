from decimal import Decimal

import pytest

from quotedesk.domain.shared.money import Money
from tests.unit.domain.assertions import expect_validation

FLOAT_SENTENCE = "A price must be a decimal amount, not a floating-point number."
NEGATIVE_SENTENCE = "A price cannot be negative."
BLANK_SENTENCE = "A price is required."
CURRENCY_SENTENCE = "Prices are in ZAR."
INVALID_SENTENCE = "That amount cannot be used as a price."


def test_money_accepts_decimal_int_and_numeric_string():
    twelve_fifty = [
        Money(Decimal("12.50")),
        Money("12.50"),
        Money.parse(Decimal("12.50")),
        Money.parse("12.50"),
    ]
    for amount in twelve_fifty:
        assert type(amount.amount) is Decimal
        assert amount.amount == Decimal("12.50")
        assert amount.currency == "ZAR"
        assert amount == twelve_fifty[0]

    twelve = Money(12)
    assert twelve.amount == Decimal("12.00")
    assert twelve == Money("12.00")
    assert twelve != Money("12.50")

    zeros = [
        Money("0"),
        Money("0.00"),
        Money(0),
        Money(Decimal("0")),
        Money.parse(0),
    ]
    for amount in zeros:
        assert amount.amount == Decimal("0.00")
        assert amount == zeros[0]

    original = Money("12.50")
    with pytest.raises(Exception):
        original.amount = Decimal("1.00")
    assert original.amount == Decimal("12.50")


def test_money_rejects_float():
    for value in (0.1, 1.0, 12.50):
        expect_validation(lambda value=value: Money(value), "money.float", FLOAT_SENTENCE)
        expect_validation(
            lambda value=value: Money.parse(value),
            "money.float",
            FLOAT_SENTENCE,
        )
    expect_validation(
        lambda: Money("1.00") * 1.5,
        "money.float",
        FLOAT_SENTENCE,
    )


def test_money_rejects_negative_and_blank():
    for value in (-1, Decimal("-1"), Decimal("-0.01"), "-0.01"):
        expect_validation(
            lambda value=value: Money(value),
            "money.negative",
            NEGATIVE_SENTENCE,
        )
    for value in (None, "", " ", "   "):
        expect_validation(lambda value=value: Money(value), "money.blank", BLANK_SENTENCE)
    expect_validation(lambda: Money("1.00") * -1, "money.negative", NEGATIVE_SENTENCE)


def test_money_quantizes_half_even():
    assert Money("1.004").amount == Decimal("1.00")
    assert Money("1.005").amount == Decimal("1.00")
    assert Money("1.006").amount == Decimal("1.01")
    assert Money("1.015").amount == Decimal("1.02")


def test_money_addition_and_multiplication_stay_decimal():
    left = Money("0.10")
    added = left + Money("0.20")
    assert type(added.amount) is Decimal
    assert added.amount == Decimal("0.30")
    assert left.amount == Decimal("0.10")

    assert (Money("0.10") * 3).amount == Decimal("0.30")
    assert (3 * Money("0.10")).amount == Decimal("0.30")
    assert (Money("0.10") * Decimal("2.5")).amount == Decimal("0.25")
    assert (Decimal("2.5") * Money("0.10")).amount == Decimal("0.25")
    assert (Money("0.10") * 0).amount == Decimal("0.00")

    expect_validation(lambda: Money("0.10") + 1, "money.invalid", INVALID_SENTENCE)
    expect_validation(
        lambda: Money("0.10") * Money("0.20"),
        "money.invalid",
        INVALID_SENTENCE,
    )
    unusable = (
        True,
        False,
        Decimal("NaN"),
        Decimal("Infinity"),
        "abc",
        " 12.50",
        "1e2",
        "+12",
        "R 1",
        "1,000",
    )
    for value in unusable:
        expect_validation(lambda value=value: Money(value), "money.invalid", INVALID_SENTENCE)


def test_money_rejects_mixed_currency():
    expect_validation(
        lambda: Money("1.00", currency="USD"),
        "money.currency",
        CURRENCY_SENTENCE,
    )
    expect_validation(
        lambda: Money.parse(Decimal("1.00"), currency="EUR"),
        "money.currency",
        CURRENCY_SENTENCE,
    )
    total = Money("1.00") + Money("2.50")
    assert total.currency == "ZAR"
    assert total.amount == Decimal("3.50")
