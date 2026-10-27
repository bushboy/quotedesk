from quotedesk.domain.case.facts import CaseFacts, ExtractionFacts, JobKind, SegmentationFacts
from quotedesk.domain.policy.rules import Decision, Policy, PolicyRule
from quotedesk.domain.services.confidence import (
    ConfidenceBand,
    SizeSource,
    derive_confidence,
    rate_card_match,
)
from quotedesk.domain.services.injection import classify_injection_claims
from quotedesk.domain.shared.errors import PolicyViolation

_STAND_HAZARD_WORDS = ("leaning", "cracked", "sagging")
_BAD_STAND = frozenset(_STAND_HAZARD_WORDS)


def decide(
    case_facts: CaseFacts,
    extraction_facts: ExtractionFacts,
    segmentation_facts: SegmentationFacts,
    policy: Policy,
) -> Decision:
    indexed = sorted(enumerate(policy.rules), key=lambda item: (item[1].priority, item[0]))
    for _, rule in indexed:
        predicate = _PREDICATES.get(rule.rule_id.value)
        if predicate is None:
            continue
        if predicate(case_facts, extraction_facts, segmentation_facts, policy):
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


def _e01(
    case: CaseFacts,
    extraction: ExtractionFacts,
    _segmentation: SegmentationFacts,
    _policy: Policy,
) -> bool:
    for text in (case.customer_text, case.voice_transcript, extraction.image_text):
        flags = classify_injection_claims(text)
        if flags.instruction or flags.claimed_approval:
            return True
    return False


def _text_mentions_stand_hazard(case: CaseFacts) -> bool:
    for text in (case.customer_text, case.voice_transcript):
        if text is None:
            continue
        folded = text.casefold()
        if any(word in folded for word in _STAND_HAZARD_WORDS):
            return True
    return False


def _e02(
    case: CaseFacts,
    extraction: ExtractionFacts,
    _segmentation: SegmentationFacts,
    _policy: Policy,
) -> bool:
    if extraction.stand_condition in _BAD_STAND:
        return True
    if extraction.elevated and extraction.structure_damage:
        return True
    return _text_mentions_stand_hazard(case)


def _e03(
    _case: CaseFacts,
    extraction: ExtractionFacts,
    _segmentation: SegmentationFacts,
    _policy: Policy,
) -> bool:
    return extraction.exposed_wiring or extraction.active_flooding


def _s01(
    case: CaseFacts,
    _extraction: ExtractionFacts,
    _segmentation: SegmentationFacts,
    _policy: Policy,
) -> bool:
    return case.job is JobKind.BOREHOLE


def _s02(
    case: CaseFacts,
    extraction: ExtractionFacts,
    _segmentation: SegmentationFacts,
    _policy: Policy,
) -> bool:
    sound_elevated = extraction.elevated and not extraction.structure_damage
    return sound_elevated or case.sloped_ground or case.pipe_run_unknown


def _f01(
    case: CaseFacts,
    _extraction: ExtractionFacts,
    _segmentation: SegmentationFacts,
    policy: Policy,
) -> bool:
    if derive_confidence(case.checks) is not ConfidenceBand.HIGH:
        return False
    if case.job is not JobKind.REPLACEMENT:
        return False
    if case.size_litres is None or case.size_source is not SizeSource.CUSTOMER_STATED:
        return False
    if not case.existing_level_base or not case.item_codes:
        return False
    return rate_card_match(case.item_codes, set(policy.rate_card_codes))


def _r01(
    case: CaseFacts,
    _extraction: ExtractionFacts,
    _segmentation: SegmentationFacts,
    _policy: Policy,
) -> bool:
    band = derive_confidence(case.checks)
    if band not in (ConfidenceBand.MEDIUM, ConfidenceBand.HIGH):
        return False
    return case.new_tank_and_pump and case.base_unconfirmed


def _l01(
    case: CaseFacts,
    _extraction: ExtractionFacts,
    _segmentation: SegmentationFacts,
    _policy: Policy,
) -> bool:
    return derive_confidence(case.checks) is ConfidenceBand.LOW


def _l02(
    case: CaseFacts,
    _extraction: ExtractionFacts,
    _segmentation: SegmentationFacts,
    _policy: Policy,
) -> bool:
    return derive_confidence(case.checks) in (ConfidenceBand.MEDIUM, ConfidenceBand.HIGH)


_PREDICATES = {
    "WATER-E01": _e01,
    "WATER-E02": _e02,
    "WATER-E03": _e03,
    "WATER-S01": _s01,
    "WATER-S02": _s02,
    "WATER-F01": _f01,
    "WATER-R01": _r01,
    "WATER-L01": _l01,
    "WATER-L02": _l02,
}
