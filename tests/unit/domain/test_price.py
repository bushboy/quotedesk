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


def test_a_per_square_metre_item_uses_the_measured_area():
    card = RateCard(
        vat_inclusive=True,
        site_visit_fee=Money("750.00"),
        items=(
            RateCardItem(
                item_code="SHEET-ECO",
                description="Economy sheeting",
                unit_price=Money("8500.00"),
                unit="per m²",
            ),
        ),
    )
    priced = price(
        decision(Outcome.INDICATIVE_RANGE, rule_id="FAB-R02"),
        PriceFacts(
            items=(RequestedItem(item_code="SHEET-ECO", quantity=Decimal("1")),),
            discount_percent=Decimal("0"),
            width_m=Decimal("5"),
            length_m=Decimal("7"),
        ),
        card,
    )
    assert priced.range_min == priced.range_max == Money("297500.00")


def _install_card(*extra: RateCardItem) -> RateCard:
    return RateCard(
        vat_inclusive=True,
        site_visit_fee=Money("750.00"),
        items=(
            RateCardItem(
                item_code="TANK-5000",
                description="5000 L tank",
                unit_price=Money("4250.00"),
                role="product",
                applies_to="both",
            ),
            RateCardItem(
                item_code="STAND",
                description="Stand and base",
                unit_price=Money("900.00"),
                role="frame",
                applies_to="new",
            ),
            RateCardItem(
                item_code="FIT-NEW",
                description="New connection",
                unit_price=Money("400.00"),
                role="installation",
                applies_to="new",
            ),
            *extra,
        ),
    )


def _worked(work: str) -> PriceFacts:
    return PriceFacts(
        items=(RequestedItem(item_code="TANK-5000", quantity=Decimal("1")),),
        discount_percent=Decimal("0"),
        roles=("frame", "installation"),
        work=work,
    )


def test_a_swap_prices_the_material_and_leaves_out_new_lines():
    priced = price(decision(Outcome.FIXED_OFFER), _worked("swap"), _install_card())
    assert [line.item_code for line in priced.lines] == ["TANK-5000"]
    assert priced.lines[0].total == Money("4250.00")


def test_a_new_installation_adds_the_frame_and_the_new_labour():
    priced = price(decision(Outcome.FIXED_OFFER), _worked("new"), _install_card())
    assert [line.item_code for line in priced.lines] == ["TANK-5000", "STAND", "FIT-NEW"]
    assert sum((line.total.amount for line in priced.lines), start=Decimal("0")) == Decimal("5550.00")


def test_a_swap_adds_swap_labour_when_that_row_exists():
    card = _install_card(
        RateCardItem(
            item_code="FIT-SWAP",
            description="Refit on the existing stand",
            unit_price=Money("150.00"),
            role="installation",
            applies_to="swap",
        )
    )
    priced = price(decision(Outcome.FIXED_OFFER), _worked("swap"), card)
    assert [line.item_code for line in priced.lines] == ["TANK-5000", "FIT-SWAP"]
    assert "STAND" not in [line.item_code for line in priced.lines]
    assert "FIT-NEW" not in [line.item_code for line in priced.lines]


def test_a_range_adds_the_shared_lines_to_both_ends():
    card = RateCard(
        vat_inclusive=True,
        site_visit_fee=Money("750.00"),
        items=(
            RateCardItem(
                item_code="SHEET-ECO",
                description="Economy sheeting",
                unit_price=Money("180.00"),
                unit="per m²",
                role="product",
                applies_to="both",
            ),
            RateCardItem(
                item_code="SHEET-POLY",
                description="Polycarbonate sheeting",
                unit_price=Money("260.00"),
                unit="per m²",
                role="product",
                applies_to="both",
            ),
            RateCardItem(
                item_code="FRAME",
                description="Steel frame",
                unit_price=Money("50.00"),
                unit="per m²",
                role="frame",
                applies_to="new",
            ),
        ),
    )
    priced = price(
        decision(Outcome.INDICATIVE_RANGE, rule_id="FAB-R02"),
        PriceFacts(
            items=(
                RequestedItem(item_code="SHEET-ECO", quantity=Decimal("1")),
                RequestedItem(item_code="SHEET-POLY", quantity=Decimal("1")),
            ),
            discount_percent=Decimal("0"),
            width_m=Decimal("5"),
            length_m=Decimal("7"),
            roles=("frame",),
            work="new",
        ),
        card,
    )
    assert priced.price_type == "range"
    assert priced.lines == ()
    assert priced.range_min == Money("8050.00")
    assert priced.range_max == Money("10850.00")
    assert priced.included == ("Steel frame",)


def test_a_card_with_only_products_prices_as_before():
    priced = price(decision(Outcome.FIXED_OFFER), _worked("new"), rate_card())
    assert [line.item_code for line in priced.lines] == ["TANK-5000"]
    assert priced.lines[0].total == Money("4250.00")


def test_price_composes_the_roles_a_pivot_door_adds():
    card = RateCard(
        vat_inclusive=True,
        site_visit_fee=Money("750.00"),
        items=(
            RateCardItem(item_code="DOOR-PIVOT", description="Pivot door", unit_price=Money("1000.00"), role="product"),
            RateCardItem(item_code="FRAME", description="Frame", unit_price=Money("200.00"), role="frame"),
            RateCardItem(item_code="HANDLE", description="Handle", unit_price=Money("50.00"), role="hardware"),
            RateCardItem(item_code="INSTALL", description="Installation", unit_price=Money("300.00"), role="installation"),
            RateCardItem(item_code="DELIVER", description="Delivery", unit_price=Money("100.00"), role="delivery"),
        ),
    )
    priced = price(
        decision(Outcome.FIXED_OFFER),
        PriceFacts(
            items=(RequestedItem(item_code="DOOR-PIVOT", quantity=Decimal("1")),),
            discount_percent=Decimal("0"),
            roles=("product", "frame", "hardware", "installation", "delivery"),
        ),
        card,
    )
    assert [line.item_code for line in priced.lines] == ["DOOR-PIVOT", "FRAME", "HANDLE", "INSTALL", "DELIVER"]
    assert sum((line.total.amount for line in priced.lines), start=Decimal("0")) == Decimal("1650.00")


def _row(code: str, role: str, price: str, **extra) -> RateCardItem:
    return RateCardItem(
        item_code=code,
        description=code,
        unit_price=Money(price),
        role=role,
        **extra,
    )


def test_only_one_base_row_for_a_5000_l_tank():
    from quotedesk.domain.policy.when import all_of, any_of, eq, missing, one_of, unknown

    not_level = any_of(eq("existing_level_base", "false"), missing("existing_level_base"), unknown("existing_level_base"))
    card = RateCard(
        vat_inclusive=True,
        site_visit_fee=Money("750.00"),
        items=(
            _row("TANK-5000", "product", "4250.00"),
            _row("BASE-SLAB-S", "frame", "950.00", job_types=("new_system",), when=all_of(one_of("size_litres", ("1000", "2500")), not_level)),
            _row("BASE-SLAB-L", "frame", "1850.00", job_types=("new_system",), when=all_of(one_of("size_litres", ("5000", "10000")), not_level)),
        ),
    )
    priced = price(
        decision(Outcome.FIXED_OFFER),
        PriceFacts(
            items=(RequestedItem(item_code="TANK-5000", quantity=Decimal("1")),),
            discount_percent=Decimal("0"),
            roles=("frame",),
            work="new",
            job_type="new_system",
            values={"size_litres": "5000", "existing_level_base": "false"},
        ),
        card,
    )
    assert [line.item_code for line in priced.lines] == ["TANK-5000", "BASE-SLAB-L"]


def test_gutters_are_added_only_when_gutters_are_yes():
    from quotedesk.domain.policy.when import eq

    card = RateCard(
        vat_inclusive=True,
        site_visit_fee=Money("750.00"),
        items=(
            _row("SHEET-POLY", "product", "260.00", unit="per m²"),
            _row("GUTTER", "hardware", "165.00", unit="per metre", job_types=("carport",), when=eq("gutters", "yes")),
        ),
    )
    bare = PriceFacts(
        items=(RequestedItem(item_code="SHEET-POLY", quantity=Decimal("1")),),
        discount_percent=Decimal("0"),
        roles=("hardware",),
        job_type="carport",
        length_m=Decimal("6"),
    )
    without = price(decision(Outcome.FIXED_OFFER, rule_id="FAB-F02"), bare, card)
    assert [line.item_code for line in without.lines] == ["SHEET-POLY"]
    with_gutter = price(
        decision(Outcome.FIXED_OFFER, rule_id="FAB-F02"),
        bare.model_copy(update={"values": {"gutters": "yes"}}),
        card,
    )
    assert [line.item_code for line in with_gutter.lines] == ["SHEET-POLY", "GUTTER"]
    assert with_gutter.lines[1].quantity == Decimal("6")


def test_swap_only_rows_are_absent_on_a_new_install():
    card = RateCard(
        vat_inclusive=True,
        site_visit_fee=Money("750.00"),
        items=(
            _row("SHEET-ECO", "product", "180.00"),
            _row("REMOVE-SHEET", "installation", "45.00", job_types=("carport",), applies_to="swap"),
            _row("INSTALL-CARPORT", "installation", "120.00", job_types=("carport",)),
        ),
    )
    priced = price(
        decision(Outcome.FIXED_OFFER, rule_id="FAB-F02"),
        PriceFacts(
            items=(RequestedItem(item_code="SHEET-ECO", quantity=Decimal("1")),),
            discount_percent=Decimal("0"),
            roles=("installation",),
            work="new",
            job_type="carport",
        ),
        card,
    )
    assert [line.item_code for line in priced.lines] == ["SHEET-ECO", "INSTALL-CARPORT"]


def test_a_shade_net_carport_uses_the_shade_frame():
    from quotedesk.domain.policy.when import eq, one_of

    sheets = ("SHEET-ECO", "SHEET-POLY", "SHEET-COLOUR", "SHEET-INSUL")
    card = RateCard(
        vat_inclusive=True,
        site_visit_fee=Money("750.00"),
        items=(
            _row("SHADE-NET", "product", "145.00"),
            _row("FRAME-STEEL", "frame", "650.00", job_types=("carport",), when=one_of("sheet", sheets)),
            _row("FRAME-SHADE", "frame", "390.00", job_types=("carport",), when=eq("sheet", "SHADE-NET")),
        ),
    )
    priced = price(
        decision(Outcome.FIXED_OFFER, rule_id="FAB-F02"),
        PriceFacts(
            items=(RequestedItem(item_code="SHADE-NET", quantity=Decimal("1")),),
            discount_percent=Decimal("0"),
            roles=("frame",),
            job_type="carport",
            values={"sheet": "SHADE-NET"},
        ),
        card,
    )
    assert [line.item_code for line in priced.lines] == ["SHADE-NET", "FRAME-SHADE"]


def test_price_refuses_low_confidence_fixed_decision():
    choice = decision(Outcome.FIXED_OFFER, ConfidenceBand.LOW)
    expect_price_refused(
        lambda: price(choice, facts(("TANK-5000", "1")), rate_card()),
        "A fixed quote needs a higher confidence band.",
    )
    assert choice.outcome == Outcome.FIXED_OFFER
    assert choice.confidence_band == ConfidenceBand.LOW
