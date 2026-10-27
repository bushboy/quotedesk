from __future__ import annotations

from decimal import Decimal

import pytest

from quotedesk.domain.policy.rules import Decision, Outcome
from quotedesk.domain.services.confidence import ConfidenceBand
from quotedesk.domain.shared.errors import PolicyViolation
from quotedesk.domain.shared.ids import PolicyVersionId, RuleId
from tests.unit.domain.assertions import expect_domain


def _bind():
    global ClauseFacts, ClausePolicy, ClauseTemplate, select_clauses
    from quotedesk.domain.policy.clauses import ClauseFacts, ClausePolicy, ClauseTemplate
    from quotedesk.domain.services.select_clauses import select_clauses


@pytest.fixture(autouse=True)
def _implemented():
    _bind()


E03 = "Please isolate the power near the water, and stay clear of it until we've checked the site."
RANGE_TEMPLATE = "We can send a price range for this carport."
IDS = (
    "CARPORT-A1",
    "CARPORT-A2",
    "CARPORT-A3",
    "CARPORT-A4",
    "CARPORT-A5",
    "CARPORT-A6",
    "CARPORT-X1",
    "CARPORT-X2",
    "GEN-V1",
    "GEN-V2",
    "GEN-S1",
)
ROWS = (
    (
        "CARPORT-A1",
        "assumption",
        "Size {width_m} m x {length_m} m ({area_m2} m²) as stated",
        "Re-quote at the rate-card price for the actual size",
        None,
    ),
    (
        "CARPORT-A2",
        "assumption",
        "Clearance height up to the rate card's standard height",
        "Height surcharge from the rate card; above its maximum, site measure",
        "HEIGHT-EXTRA",
    ),
    (
        "CARPORT-A3",
        "assumption",
        "Freestanding posts fixed to existing paving or concrete",
        "Footing variation from the rate card; soil or slope, site measure",
        None,
    ),
    (
        "CARPORT-A4",
        "assumption",
        "Level site with vehicle access for installation",
        "Site measure",
        None,
    ),
    (
        "CARPORT-A5",
        "assumption",
        "Roof covering is one of the options in the range",
        "Range narrows to the chosen covering",
        None,
    ),
    (
        "CARPORT-A6",
        "assumption",
        "No existing structure to remove",
        "Removal priced separately",
        None,
    ),
    (
        "CARPORT-X1",
        "exclusion",
        "Excludes municipal building plan approval, where required",
        "Customer's responsibility; stated, not handled",
        None,
    ),
    (
        "CARPORT-X2",
        "exclusion",
        "Excludes electrical work and gate automation",
        "Separate quote",
        None,
    ),
    (
        "GEN-V1",
        "validity",
        "This price is valid for {validity_days} days.",
        "After expiry, re-quote at the current rate card",
        None,
    ),
    (
        "GEN-V2",
        "validity",
        "A range or default-based price becomes fixed only after site measure confirms the assumptions",
        "Final price follows the measured assumptions",
        None,
    ),
    (
        "GEN-S1",
        "schedule",
        "No installation date is reserved until the {deposit_percent}% deposit is paid.",
        "See scheduling rules",
        None,
    ),
)


def clause_policy(
    *,
    version: str = "1",
    codes: tuple[str, ...] = ("HEIGHT-EXTRA",),
    settings: dict[str, int] | None = None,
) -> ClausePolicy:
    chosen = {"deposit_percent": 30, "validity_days": 14} if settings is None else settings
    templates = tuple(
        ClauseTemplate(
            clause_id=clause_id,
            clause_version=version,
            kind=kind,
            text=text,
            if_not_true=if_not_true,
            variation_item_code=variation,
        )
        for clause_id, kind, text, if_not_true, variation in ROWS
    )
    return ClausePolicy(templates=templates, settings=chosen, rate_card_codes=codes)


def carport_decision() -> Decision:
    return Decision(
        outcome=Outcome.INDICATIVE_RANGE,
        rule_id=RuleId("FAB-R01"),
        policy_version=PolicyVersionId("fab-policy-v1.0"),
        reasons=("Roof covering not chosen.",),
        confidence_band=ConfidenceBand.HIGH,
        customer_template=RANGE_TEMPLATE,
    )


def size_only(roof_covering: str | None = None) -> ClauseFacts:
    return ClauseFacts(width_m=Decimal("6.0"), length_m=Decimal("7.0"), roof_covering=roof_covering)


def test_clauses_for_the_carport_with_only_a_size():
    selection = select_clauses(carport_decision(), size_only(), "carport", clause_policy())
    assert tuple(item.clause_id for item in selection.conditions) == IDS
    assert selection.conditions[0].text == "Size 6.0 m x 7.0 m (42 m²) as stated"
    assert "6.0 m x 7.0 m" in selection.conditions[0].text
    assert selection.customer_template == RANGE_TEMPLATE


def test_clauses_omit_a_confirmed_assumption():
    selection = select_clauses(carport_decision(), size_only("sheet"), "carport", clause_policy())
    ids = tuple(item.clause_id for item in selection.conditions)
    assert "CARPORT-A5" not in ids
    assert ids == tuple(item for item in IDS if item != "CARPORT-A5")
    assumptions = tuple(item.clause_id for item in selection.conditions if item.kind == "assumption")
    assert assumptions == ("CARPORT-A1", "CARPORT-A2", "CARPORT-A3", "CARPORT-A4", "CARPORT-A6")


def test_clauses_fill_placeholders():
    selection = select_clauses(carport_decision(), size_only(), "carport", clause_policy())
    texts = tuple(item.text for item in selection.conditions)
    assert "This price is valid for 14 days." in texts
    assert "No installation date is reserved until the 30% deposit is paid." in texts
    assert all("{deposit_percent}" not in text for text in texts)
    assert all("{validity_days}" not in text for text in texts)
    missing = clause_policy(settings={"validity_days": 14})
    expect_domain(
        lambda: select_clauses(carport_decision(), size_only(), "carport", missing),
        PolicyViolation,
        "policy.violation",
        "A clause placeholder has no setting.",
    )


def test_clauses_pin_version():
    first = select_clauses(carport_decision(), size_only(), "carport", clause_policy(version="1"))
    second = select_clauses(carport_decision(), size_only(), "carport", clause_policy(version="2"))
    assert {item.clause_version for item in first.conditions} == {"1"}
    assert {item.clause_version for item in second.conditions} == {"2"}
    assert first.conditions[0].clause_version == "1"


def test_clauses_name_a_real_variation_item():
    policy = clause_policy()
    selection = select_clauses(carport_decision(), size_only(), "carport", policy)
    extra = next(item for item in selection.conditions if item.clause_id == "CARPORT-A2")
    assert extra.variation_item_code == "HEIGHT-EXTRA"
    assert extra.variation_item_code in policy.rate_card_codes
    expect_domain(
        lambda: select_clauses(carport_decision(), size_only(), "carport", clause_policy(codes=())),
        PolicyViolation,
        "policy.violation",
        "That variation item is not on the rate card.",
    )


def test_escalation_still_gets_its_customer_sentence():
    choice = Decision(
        outcome=Outcome.ESCALATION,
        rule_id=RuleId("WATER-E03"),
        policy_version=PolicyVersionId("water-policy-v1.0"),
        reasons=("Exposed wiring or active flooding was recorded.",),
        confidence_band=ConfidenceBand.HIGH,
        customer_template=E03,
    )
    selection = select_clauses(choice, size_only(), "carport", clause_policy())
    assert selection.customer_template == E03
    assert selection.conditions == ()
