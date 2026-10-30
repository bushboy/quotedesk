from decimal import Decimal

from quotedesk.domain.policy.rules import Outcome, Policy, PolicyRule
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
    )


def aquasure_policy() -> Policy:
    return Policy(
        version=PolicyVersionId("water-policy-v1.0"),
        sam_score_threshold=Decimal("0.80"),
        rate_card_codes=("TANK-2500", "TANK-5000", "TANK-10000", "PUMP-STD"),
        rules=(
            _rule(
                "WATER-E01",
                0,
                Outcome.ESCALATION,
                "I can't use that message to change the quote. Please phone the business and we'll take it from there.",
                "Flagged as an injection for the owner: the message instructs the assistant or claims an approval.",
            ),
            _rule(
                "WATER-E02",
                0,
                Outcome.SITE_ASSESSMENT,
                "We'll book an inspection. The installation is damaged, and it is not clear this is a simple tank replacement.",
                "The installation is damaged, and a simple tank replacement is not confirmed.",
            ),
            _rule(
                "WATER-E03",
                0,
                Outcome.ESCALATION,
                "Please isolate the power near the water, and stay clear of it until we've checked the site.",
                "Exposed wiring or active flooding was recorded.",
            ),
            _rule(
                "WATER-S01",
                1,
                Outcome.SITE_ASSESSMENT,
                "A borehole needs a site visit. If you go ahead, the visit fee is credited against the work.",
                "The job is a borehole.",
            ),
            _rule(
                "WATER-S02",
                1,
                Outcome.SITE_ASSESSMENT,
                "This install needs a site visit before we can give you a price.",
                "The ground, the stand, or the pipe run needs a visit.",
            ),
            _rule(
                "WATER-F01",
                1,
                Outcome.FIXED_OFFER,
                "We can send a fixed quote for this replacement.",
                "Like-for-like replacement on a level base with a stated size.",
            ),
            _rule(
                "WATER-R01",
                1,
                Outcome.INDICATIVE_RANGE,
                "We can send a price range for a new tank and pump. It assumes the base still has to be confirmed.",
                "New tank and pump with the base unconfirmed.",
            ),
            _rule(
                "WATER-R02",
                1,
                Outcome.INDICATIVE_RANGE,
                "The indicative range for that tank is in this result. It can change once we confirm the base.",
                "The tank size is known for a new installation or a swap.",
            ),
            _rule(
                "WATER-L01",
                1,
                Outcome.ESCALATION,
                "Your message is recorded for further consultation. Someone from the business will contact you.",
                "Confidence is low and no earlier rule matched, so the conversation is recorded.",
            ),
            _rule(
                "WATER-L02",
                1,
                Outcome.ESCALATION,
                "Your message is recorded for further consultation. Someone from the business will contact you.",
                "No priced rule matches, so the conversation is recorded for consultation.",
            ),
        ),
    )
