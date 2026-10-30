"""Conditions are data. A new business does not need a new predicate."""

from decimal import Decimal

from quotedesk.domain.case.facts import CaseFacts, ExtractionFacts, SegmentationFacts
from quotedesk.domain.policy.rules import Outcome, Policy, PolicyRule
from quotedesk.domain.policy.when import FactView, When, all_of, eq, matches, one_of, unknown
from quotedesk.domain.services.confidence import ConfidenceChecks
from quotedesk.domain.services.decide import decide
from quotedesk.domain.shared.ids import PolicyVersionId, RuleId


def _checks() -> ConfidenceChecks:
    return ConfidenceChecks(
        required_fields=True,
        agreement=True,
        measurement=True,
        media_usable=True,
        rate_card=True,
    )


def test_a_new_opening_needs_a_site_measure_with_no_new_predicate():
    policy = Policy(
        version=PolicyVersionId("door-policy-v1.0"),
        sam_score_threshold=Decimal("0.80"),
        rate_card_codes=("DOOR-PIVOT",),
        rules=(
            PolicyRule(
                rule_id=RuleId("FAB-S09"),
                priority=0,
                outcome=Outcome.SITE_ASSESSMENT,
                customer_template="A new opening needs a site measure.",
                reason="The opening is new.",
                when=one_of("opening", ("new", "widened")),
            ),
        ),
    )
    case = CaseFacts(checks=_checks(), opening="new")
    decision = decide(case, ExtractionFacts(), SegmentationFacts(), policy)
    assert decision.rule_id.value == "FAB-S09"
    assert decision.outcome is Outcome.SITE_ASSESSMENT
    assert decision.customer_template == "A new opening needs a site measure."


def test_is_unknown_and_greater_than_are_data():
    facts = FactView(
        values={"width_m": "4"},
        numbers={"width_m": Decimal("4"), "budget": Decimal("100"), "range_minimum": Decimal("850")},
        missing=(),
        unknown=("length_m",),
    )
    assert matches(unknown("length_m"), facts)
    assert not matches(unknown("width_m"), facts)
    assert matches(When(op="greater_than", fact="range_minimum", value="fact:budget"), facts)
    assert matches(all_of(eq("width_m", "4"), unknown("length_m")), facts)
    assert not matches(When(op="is_missing", fact="width_m"), facts)
