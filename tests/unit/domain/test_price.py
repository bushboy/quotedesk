from __future__ import annotations

from decimal import Decimal

import pytest

from quotedesk.domain.policy.rules import Decision, Outcome
from quotedesk.domain.services.confidence import ConfidenceBand
from quotedesk.domain.shared.errors import PolicyViolation
from quotedesk.domain.shared.ids import PolicyVersionId, RuleId
from quotedesk.domain.shared.money import Money
from tests.unit.domain.assertions import expect_domain


def _bind():
    global PriceFacts, PricedQuote, RateCard, RateCardItem, RequestedItem, price
    from quotedesk.domain.services.price import (
        PriceFacts,
        PricedQuote,
        RateCard,
        RateCardItem,
        RequestedItem,
        price,
    )


@pytest.fixture(autouse=True)
def _implemented():
    _bind()


GROSS = Money("4887.50")


def rate_card() -> RateCard:
    return RateCard(
        vat_inclusive=True,
        site_visit_fee=Money("750.00"),
        items=(
            RateCardItem(
                item_code="TANK-5000",
                description="5000 L tank",
                unit_price=Money("4250.00"),
            ),
            RateCardItem(
                item_code="ROOF-SHADE",
                description="Shade net covering",
                unit_price=Money("8500.00"),
            ),
            RateCardItem(
                item_code="ROOF-SHEET",
                description="Sheet covering",
                unit_price=Money("12400.00"),
            ),
            RateCardItem(
                item_code="HEIGHT-EXTRA",
                description="Extra clearance height",
                unit_price=Money("600.00"),
            ),
        ),
    )


def decision(
    outcome: Outcome,
    band: ConfidenceBand = ConfidenceBand.HIGH,
    rule_id: str = "WATER-F01",
) -> Decision:
    return Decision(
        outcome=outcome,
        rule_id=RuleId(rule_id),
        policy_version=PolicyVersionId("water-policy-v1.0"),
        reasons=("A test decision.",),
        confidence_band=band,
        customer_template="A test template.",
    )


def facts(*pairs: tuple[str, str], discount: str = "10") -> PriceFacts:
    return PriceFacts(
        items=tuple(RequestedItem(item_code=code, quantity=Decimal(quantity)) for code, quantity in pairs),
        discount_percent=Decimal(discount),
    )


def card_price(code: str) -> Money:
    return next(item.unit_price for item in rate_card().items if item.item_code == code)


def expect_price_refused(call, sentence: str) -> PolicyViolation:
    error = expect_domain(call, PolicyViolation, "policy.violation", sentence)
    assert not hasattr(error, "lines")
    assert not hasattr(error, "line_items")
    return error


def test_price_fixed_offer_line_items():
    card = rate_card()
    choice = decision(Outcome.FIXED_OFFER)
    single = price(choice, facts(("TANK-5000", "1")), card)
    assert type(single) is PricedQuote
    assert single.price_type == "fixed"
    assert len(single.lines) == 1
    line = single.lines[0]
    assert line.item_code == "TANK-5000"
    assert line.description == "5000 L tank"
    assert line.quantity == Decimal("1")
    assert type(line.quantity) is Decimal
    assert line.unit_price == card_price("TANK-5000")
    assert line.unit_price == Money("4250.00")
    assert line.unit_price != GROSS
    assert line.total == Money("4250.00")
    several = price(choice, facts(("TANK-5000", "2.5")), card)
    priced = several.lines[0]
    assert priced.unit_price == Money("4250.00")
    assert priced.total == Money("10625.00")
    assert choice.outcome == Outcome.FIXED_OFFER


def test_price_range_has_min_and_max():
    card = rate_card()
    priced = price(
        decision(Outcome.INDICATIVE_RANGE, rule_id="WATER-R01"),
        facts(("ROOF-SHEET", "1"), ("ROOF-SHADE", "1")),
        card,
    )
    assert priced.price_type == "range"
    assert priced.lines == ()
    assert priced.range_min == card_price("ROOF-SHADE")
    assert priced.range_max == card_price("ROOF-SHEET")
    assert priced.range_min == Money("8500.00")
    assert priced.range_max == Money("12400.00")
    assert priced.range_min.amount <= priced.range_max.amount


def test_price_range_collapses_when_min_equals_max():
    priced = price(
        decision(Outcome.INDICATIVE_RANGE, rule_id="WATER-R01"),
        facts(("ROOF-SHADE", "1")),
        rate_card(),
    )
    assert priced.price_type == "range"
    assert priced.lines == ()
    assert priced.range_min == priced.range_max == Money("8500.00")


def test_price_site_visit_fee_only():
    priced = price(
        decision(Outcome.SITE_ASSESSMENT, rule_id="WATER-S02"),
        facts(),
        rate_card(),
    )
    assert priced.price_type == "none"
    assert priced.site_visit_fee == Money("750.00")
    assert priced.lines == ()
    assert priced.range_min is None
    assert priced.range_max is None
    assert priced.deposit is None


def test_price_escalation_has_no_amount():
    priced = price(
        decision(Outcome.ESCALATION, rule_id="WATER-E03"),
        facts(("NO-SUCH", "1")),
        rate_card(),
    )
    assert priced.price_type == "none"
    assert priced.lines == ()
    assert priced.range_min is None
    assert priced.range_max is None
    assert priced.site_visit_fee is None
    assert priced.deposit is None
    assert priced.discount_percent == Decimal("0")


def test_price_unknown_item_code():
    card = rate_card()
    fixed = decision(Outcome.FIXED_OFFER)
    expect_price_refused(
        lambda: price(fixed, facts(("NO-SUCH", "1")), card),
        "That item is not on the rate card.",
    )
    expect_price_refused(
        lambda: price(fixed, facts(("TANK-5000", "1"), ("NO-SUCH", "1")), card),
        "That item is not on the rate card.",
    )


def test_price_rejects_zero_quantity():
    card = rate_card()
    fixed = decision(Outcome.FIXED_OFFER)
    for quantity in ("0", "-1"):
        expect_price_refused(
            lambda quantity=quantity: price(fixed, facts(("TANK-5000", quantity)), card),
            "A quantity must be greater than zero.",
        )


def test_price_does_not_apply_a_discount():
    priced = price(
        decision(Outcome.FIXED_OFFER),
        facts(("TANK-5000", "1"), discount="10"),
        rate_card(),
    )
    assert priced.discount_percent == Decimal("0")
    assert type(priced.discount_percent) is Decimal
    assert priced.lines[0].total == Money("4250.00")


def test_price_refuses_low_confidence_fixed_decision():
    choice = decision(Outcome.FIXED_OFFER, ConfidenceBand.LOW)
    expect_price_refused(
        lambda: price(choice, facts(("TANK-5000", "1")), rate_card()),
        "A fixed quote needs a higher confidence band.",
    )
    assert choice.outcome == Outcome.FIXED_OFFER
    assert choice.confidence_band == ConfidenceBand.LOW
