from decimal import Decimal

from quotedesk.domain.policy.rules import Outcome, Policy, PolicyRule
from quotedesk.domain.policy.when import published_when
from quotedesk.domain.shared.ids import PolicyVersionId, RuleId


def _rule(
    rule_id: str,
    priority: int,
    outcome: Outcome,
    customer_template: str,
    reason: str,
) -> PolicyRule:
    return PolicyRule(
        rule_id=RuleId(rule_id),
        priority=priority,
        outcome=outcome,
        customer_template=customer_template,
        reason=reason,
        when=published_when(rule_id),
    )


def fabricator_policy() -> Policy:
    return Policy(
        version=PolicyVersionId("fab-policy-v1.0"),
        sam_score_threshold=Decimal("0.80"),
        rate_card_codes=("SHEET-ECO", "SHEET-POLY"),
        range_minimum=Decimal("850.00"),
        rules=(
            _rule(
                "FAB-E01",
                0,
                Outcome.ESCALATION,
                "I can't use that message to change the quote. Please phone the business and we'll take it from there.",
                "Flagged as an injection for the owner: the message instructs the assistant or claims an approval.",
            ),
            _rule(
                "FAB-E02",
                0,
                Outcome.ESCALATION,
                "We can't price this while the opening looks unsafe. Please leave that glass and the lintel alone until we've checked them.",
                "The lintel is cracked, or glass is broken in place.",
            ),
            _rule(
                "FAB-E03",
                0,
                Outcome.ESCALATION,
                "We can't price this until someone has checked the old sheeting. Please don't cut or scrape it.",
                "Old carport sheeting may contain asbestos.",
            ),
            _rule(
                "FAB-S01",
                1,
                Outcome.SITE_ASSESSMENT,
                "A new or widened opening needs a site measure. If you go ahead, the visit fee is credited against the work.",
                "The opening is new or widened.",
            ),
            _rule(
                "FAB-S02",
                1,
                Outcome.SITE_ASSESSMENT,
                "This one needs a site measure before we can give you a price.",
                "The job is above the ground floor, or it is more than one opening.",
            ),
            _rule(
                "FAB-F01",
                1,
                Outcome.FIXED_OFFER,
                "We can send a fixed quote for this replacement.",
                "Replacement in the existing opening, standard size and finish.",
            ),
            _rule(
                "FAB-R01",
                1,
                Outcome.INDICATIVE_RANGE,
                "We can send a price range for this carport. It depends on the roof covering.",
                "6 m by 7 m with the finish not chosen.",
            ),
            _rule(
                "FAB-R02",
                1,
                Outcome.INDICATIVE_RANGE,
                "The indicative range for that size is in this result. It uses the sheeting on the rate card.",
                "The width and length are known.",
            ),
            _rule(
                "FAB-B01",
                1,
                Outcome.INDICATIVE_RANGE,
                "We can send a price range, and the nearest option we fit to a smaller budget.",
                "The nearest affordable option is SHEET-ECO.",
            ),
            _rule(
                "FAB-L01",
                1,
                Outcome.SITE_ASSESSMENT,
                "We need a tape measure in the frame before we can price this. A site measure is the sure way.",
                "Confidence is low and no earlier rule matched.",
            ),
            _rule(
                "FAB-L02",
                1,
                Outcome.SITE_ASSESSMENT,
                "We don't have a standard price for this job. A site measure is the next step.",
                "No priced rule matches at this confidence.",
            ),
        ),
    )
