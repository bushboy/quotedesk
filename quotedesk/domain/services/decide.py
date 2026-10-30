"""Match the first rule whose condition the facts satisfy.

The condition is data on the rule. This function does not look at which business
published the policy, and it does not keep a predicate per rule id.
"""

from decimal import Decimal

from quotedesk.domain.case.facts import CaseFacts, ExtractionFacts, SegmentationFacts
from quotedesk.domain.policy.rules import Decision, Policy, PolicyRule
from quotedesk.domain.policy.when import FactView, When, matches
from quotedesk.domain.services.confidence import derive_confidence, rate_card_match
from quotedesk.domain.services.injection import classify_injection_claims
from quotedesk.domain.shared.errors import PolicyViolation

_STAND_HAZARD_WORDS = ("leaning", "cracked", "sagging")


def decide(
    case_facts: CaseFacts,
    extraction_facts: ExtractionFacts,
    segmentation_facts: SegmentationFacts,
    policy: Policy,
) -> Decision:
    facts = _facts(case_facts, extraction_facts, policy)
    indexed = sorted(enumerate(policy.rules), key=lambda item: (item[1].priority, item[0]))
    for _, rule in indexed:
        if rule.when is not None and matches(rule.when, facts):
            return _decision(rule, case_facts, policy)
    raise PolicyViolation(code="policy.violation", sentence="The policy matched no rule.")


def _decision(rule: PolicyRule, case_facts: CaseFacts, policy: Policy) -> Decision:
    return Decision(
        outcome=rule.outcome,
        rule_id=rule.rule_id,
        policy_version=policy.version,
        reasons=(rule.reason,),
        confidence_band=derive_confidence(case_facts.checks),
        customer_template=rule.customer_template,
    )


def _facts(case: CaseFacts, extraction: ExtractionFacts, policy: Policy) -> FactView:
    values: dict[str, str] = {}
    numbers: dict[str, Decimal] = {}
    missing: list[str] = []

    def text(key: str, value: object, *, blank_missing: bool = False) -> None:
        if value is None:
            missing.append(key)
            return
        rendered = getattr(value, "value", None)
        rendered = str(value) if rendered is None else str(rendered)
        if blank_missing and rendered.strip() == "":
            missing.append(key)
            return
        values[key] = rendered

    def flag(key: str, value: bool) -> None:
        values[key] = "true" if value else "false"

    def number(key: str, value: Decimal | int | None) -> None:
        if value is None:
            missing.append(key)
            values[f"{key}_known"] = "false"
            return
        amount = Decimal(value)
        numbers[key] = amount
        values[key] = format(amount, "f")
        values[f"{key}_known"] = "true"

    text("job", case.job)
    text("size_source", case.size_source)
    text("stand_condition", extraction.stand_condition)
    text("opening", case.opening)
    text("finish", case.finish, blank_missing=True)
    text("job_type", case.job_type)
    number("size_litres", case.size_litres)
    number("width_m", case.width_m)
    number("length_m", case.length_m)
    number("budget", case.budget)
    number("range_minimum", policy.range_minimum)
    values["size_known"] = values.get("size_litres_known", "false")
    values["width_known"] = values.get("width_m_known", "false")
    values["length_known"] = values.get("length_m_known", "false")
    values["budget_known"] = values.get("budget_known", "false")
    values["range_known"] = "true" if "range_minimum" in numbers else "false"
    values["finish_chosen"] = "false" if "finish" in missing else "true"
    if case.simple_swap is None:
        missing.append("simple_swap")
    else:
        flag("simple_swap", case.simple_swap)
    for key, value in (
        ("existing_level_base", case.existing_level_base),
        ("installation_damaged", case.installation_damaged),
        ("base_unconfirmed", case.base_unconfirmed),
        ("new_tank_and_pump", case.new_tank_and_pump),
        ("sloped_ground", case.sloped_ground),
        ("pipe_run_unknown", case.pipe_run_unknown),
        ("elevated", extraction.elevated),
        ("structure_damage", extraction.structure_damage),
        ("exposed_wiring", extraction.exposed_wiring),
        ("active_flooding", extraction.active_flooding),
        ("lintel_cracked", extraction.lintel_cracked),
        ("glass_broken", extraction.glass_broken),
        ("possible_asbestos", extraction.possible_asbestos),
        ("above_ground_floor", case.above_ground_floor),
        ("multi_unit", case.multi_unit),
        ("standard_band", case.standard_band),
    ):
        flag(key, value)
    if case.item_codes:
        values["items_chosen"] = "true"
        values["item_codes"] = ",".join(case.item_codes)
    else:
        values["items_chosen"] = "false"
        missing.append("item_codes")
    flag("rate_card_match", rate_card_match(case.item_codes, set(policy.rate_card_codes)))
    values["confidence"] = derive_confidence(case.checks).value
    flag("injection", _injection(case, extraction))
    flag("stand_hazard_mentioned", _stand_hazard(case))
    return FactView(values=values, numbers=numbers, missing=tuple(missing))


def _injection(case: CaseFacts, extraction: ExtractionFacts) -> bool:
    for text in (case.customer_text, case.voice_transcript, extraction.image_text):
        flags = classify_injection_claims(text)
        if flags.instruction or flags.claimed_approval:
            return True
    return False


def _stand_hazard(case: CaseFacts) -> bool:
    for text in (case.customer_text, case.voice_transcript):
        if text is None:
            continue
        folded = text.casefold()
        if any(word in folded for word in _STAND_HAZARD_WORDS):
            return True
    return False


def parse_when(raw: object) -> When | None:
    if not isinstance(raw, dict):
        return None
    nested = raw.get("of") or ()
    values = raw.get("values") or ()
    return When(
        op=str(raw.get("op") or ""),
        fact=str(raw.get("fact") or ""),
        value="" if raw.get("value") is None else str(raw.get("value")),
        values=tuple(str(item) for item in values),
        of=tuple(item for item in (parse_when(part) for part in nested) if item is not None),
    )
