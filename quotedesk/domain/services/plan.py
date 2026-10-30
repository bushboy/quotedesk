"""The next step for a conversation, chosen from the case and the published playbook."""

import re
from collections.abc import Mapping
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict

from quotedesk.domain.case.case_file import CaseFile, Job
from quotedesk.domain.case.facts import CaseFacts, ExtractionFacts, JobKind, SegmentationFacts
from quotedesk.domain.policy.playbook import BusinessPlaybook
from quotedesk.domain.policy.rules import Outcome, Policy
from quotedesk.domain.services.confidence import ConfidenceChecks, SizeSource
from quotedesk.domain.services.decide import decide
from quotedesk.domain.shared.errors import PolicyViolation

_ASK = "What should I quote for you?"
_QUOTE = "I'll price that from the rate card."
_TWICE = "I've asked twice, so I won't ask again."
_UNSURE = "You don't know that, so I won't ask again."
_GREETING = re.compile(r"^(?:hi|hello|hey|good morning|good afternoon|good evening)\b", re.IGNORECASE)
_ORDER = {"escalate": 0, "inspection": 1, "ask": 2, "quote": 3}
_CONFIDENCE = ("required_fields", "agreement", "measurement", "media_usable", "rate_card")
_TRUE = frozenset({"true", "yes", "y"})


class StepKind(str, Enum):
    ASK = "ask"
    QUOTE = "quote"
    INSPECTION = "inspection"
    ESCALATE = "escalate"


class NextStep(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: StepKind
    sentence: str
    job_id: str = ""
    fact_key: str = ""
    reason: str = ""
    rule_id: str = ""


def plan_next_step(
    case: CaseFile,
    playbook: BusinessPlaybook,
    policy: Policy,
    asked: Mapping[str, int] | None = None,
    customer_text: str = "",
) -> NextStep:
    """One step. Escalate wins, then an inspection, then a missing fact, then a quote."""
    counts = dict(asked or {})
    if not case.jobs:
        step = _opening(playbook)
    else:
        steps = tuple(_job_step(job, case, playbook, policy, counts) for job in case.jobs)
        step = min(steps, key=lambda item: _ORDER[item.kind.value])
    return _phrase(step, playbook, customer_text)


def _opening(playbook: BusinessPlaybook) -> NextStep:
    if len(playbook.job_types) == 1:
        job = playbook.job_types[0]
        for fact in job.facts:
            if fact.required and fact.question.strip():
                return NextStep(kind=StepKind.ASK, sentence=fact.question.strip(), job_id=job.key, fact_key=fact.key)
    if playbook.job_types:
        names = ", ".join(job.key for job in playbook.job_types)
        return NextStep(kind=StepKind.ASK, sentence=f"Which of these should I quote: {names}?", fact_key="job_type")
    return NextStep(kind=StepKind.ASK, sentence=_ASK, fact_key="job_type")


def _job_step(
    job: Job,
    case: CaseFile,
    playbook: BusinessPlaybook,
    policy: Policy,
    asked: dict[str, int],
) -> NextStep:
    current = _current(case, job.job_id)
    states = _states(case, job.job_id)
    play = next((item for item in playbook.job_types if item.key == (job.job_type or "")), None)
    missing = None
    unknown = None
    if play is not None:
        for fact in play.facts:
            if not fact.required:
                continue
            if states.get(fact.key) == "unknown":
                unknown = unknown or fact
                continue
            if not current.get(fact.key, "").strip() and missing is None:
                missing = fact
    decision = _decision(job, current, policy)
    if decision is not None and not _fallback(decision.rule_id.value):
        step = _from_decision(decision, job.job_id)
        if step.kind in (StepKind.ESCALATE, StepKind.INSPECTION):
            return step
    if missing is not None and asked.get(missing.key, 0) < 2:
        question = missing.question.strip() or _ASK
        return NextStep(
            kind=StepKind.ASK,
            sentence=question,
            job_id=job.job_id,
            fact_key=missing.key,
        )
    if missing is not None or unknown is not None:
        return _stop(playbook, job.job_id, missing or unknown, missing is not None)
    if decision is None:
        return NextStep(kind=StepKind.QUOTE, sentence=_QUOTE, job_id=job.job_id)
    return _from_decision(decision, job.job_id)


def _stop(playbook: BusinessPlaybook, job_id: str, fact, twice: bool) -> NextStep:
    lead = _TWICE if twice else _UNSURE
    if playbook.inspections:
        return NextStep(
            kind=StepKind.INSPECTION,
            sentence=f"{lead} We'll book an inspection.",
            job_id=job_id,
            fact_key=fact.key,
            reason="The customer could not answer a required fact.",
        )
    return NextStep(
        kind=StepKind.ESCALATE,
        sentence=f"{lead} Someone from the business will take it from here.",
        job_id=job_id,
        fact_key=fact.key,
        reason="The customer could not answer a required fact.",
    )


def _phrase(step: NextStep, playbook: BusinessPlaybook, text: str) -> NextStep:
    outside = _outside(playbook, text)
    if outside and step.kind in (StepKind.ASK, StepKind.QUOTE):
        return NextStep(
            kind=StepKind.ESCALATE,
            sentence=outside,
            job_id=step.job_id,
            reason="This is outside what the business does.",
        )
    if step.kind is not StepKind.ASK or not text.strip():
        return step
    folded = text.casefold()
    for question in playbook.questions:
        topic = question.topic.strip().casefold()
        if topic and topic in folded and question.answer.strip():
            return step.model_copy(update={"sentence": f"{question.answer.strip()} {step.sentence}".strip()})
    if _GREETING.match(text.strip()) and playbook.hours.strip():
        return step.model_copy(update={"sentence": f"{playbook.hours.strip()} {step.sentence}".strip()})
    return step


def _outside(playbook: BusinessPlaybook, text: str) -> str | None:
    raw = playbook.does_not.strip()
    if not raw or not text.strip():
        return None
    words = re.findall(r"[a-z]{5,}", raw.casefold())
    if any(word in text.casefold() for word in words):
        return raw
    return None


def _states(case: CaseFile, job_id: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for fact in case.facts(job_id):
        if fact.superseded_by is not None or fact.contested or fact.key in found:
            continue
        found[fact.key] = fact.state
    return found


def _decision(job: Job, current: dict[str, str], policy: Policy):
    if not policy.rules:
        return None
    try:
        return decide(_case_facts(job, current), _extraction(current), SegmentationFacts(), policy)
    except PolicyViolation:
        return None


def _from_decision(decision, job_id: str) -> NextStep:
    sentence = decision.customer_template.strip() or _QUOTE
    reason = decision.reasons[0] if decision.reasons else ""
    rule_id = decision.rule_id.value
    if decision.outcome is Outcome.ESCALATION:
        return NextStep(kind=StepKind.ESCALATE, sentence=sentence, job_id=job_id, reason=reason, rule_id=rule_id)
    if decision.outcome is Outcome.SITE_ASSESSMENT:
        return NextStep(kind=StepKind.INSPECTION, sentence=sentence, job_id=job_id, reason=reason, rule_id=rule_id)
    return NextStep(kind=StepKind.QUOTE, sentence=sentence, job_id=job_id, reason=reason, rule_id=rule_id)


def _fallback(rule_id: str) -> bool:
    return rule_id.endswith("-L01") or rule_id.endswith("-L02")


def _extraction(current: dict[str, str]) -> ExtractionFacts:
    stand = current.get("stand_condition")
    if stand not in ("sound", "leaning", "cracked", "sagging"):
        stand = None
    return ExtractionFacts(
        stand_condition=stand,
        elevated=_flag(current, "elevated"),
        structure_damage=_flag(current, "structure_damage"),
        exposed_wiring=_flag(current, "exposed_wiring"),
        active_flooding=_flag(current, "active_flooding"),
        lintel_cracked=_flag(current, "lintel_cracked"),
        glass_broken=_flag(current, "glass_broken"),
        possible_asbestos=_flag(current, "possible_asbestos"),
    )


def _current(case: CaseFile, job_id: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for fact in case.facts(job_id):
        if fact.superseded_by is not None or fact.contested or fact.key in values:
            continue
        values[fact.key] = fact.value
    return values


def _case_facts(job: Job, current: dict[str, str]) -> CaseFacts:
    size = _whole(current.get("size_litres"))
    source = current.get("size_source")
    if source not in ("photo_inferred", "customer_stated", "reference_object") and size is not None:
        source = "customer_stated"
    opening = current.get("opening")
    return CaseFacts(
        checks=_checks(current),
        job=_job_kind(current.get("job_type") or job.job_type),
        customer_text=current.get("customer_text"),
        size_litres=size,
        size_source=None if source is None else SizeSource(source),
        existing_level_base=_flag(current, "existing_level_base"),
        installation_damaged=_flag(current, "installation_damaged"),
        simple_swap=_optional(current, "simple_swap"),
        base_unconfirmed=_flag(current, "base_unconfirmed"),
        new_tank_and_pump=_flag(current, "new_tank_and_pump"),
        sloped_ground=_flag(current, "sloped_ground"),
        pipe_run_unknown=_flag(current, "pipe_run_unknown"),
        item_codes=_codes(current.get("item_codes")),
        width_m=_decimal(current.get("width_m")),
        length_m=_decimal(current.get("length_m")),
        finish=current.get("finish"),
        opening=opening if opening in ("existing", "new", "widened") else None,
        above_ground_floor=_flag(current, "above_ground_floor"),
        multi_unit=_flag(current, "multi_unit"),
        standard_band=_flag(current, "standard_band"),
        budget=_decimal(current.get("budget")),
        job_type=_sheet_job(current.get("job_type") or job.job_type),
    )


def _checks(current: dict[str, str]) -> ConfidenceChecks:
    if all(key not in current for key in _CONFIDENCE):
        return ConfidenceChecks(
            required_fields=True,
            agreement=True,
            measurement=True,
            media_usable=True,
            rate_card=True,
        )
    return ConfidenceChecks(
        required_fields=_flag(current, "required_fields"),
        agreement=_flag(current, "agreement"),
        measurement=_flag(current, "measurement"),
        media_usable=_flag(current, "media_usable"),
        rate_card=_flag(current, "rate_card"),
    )


def _flag(current: dict[str, str], key: str) -> bool:
    raw = current.get(key)
    if raw is None:
        return False
    return raw.strip().casefold() in _TRUE


def _optional(current: dict[str, str], key: str) -> bool | None:
    raw = current.get(key)
    if raw is None or raw.strip() == "":
        return None
    return raw.strip().casefold() in _TRUE


def _whole(raw: str | None) -> int | None:
    if raw is None:
        return None
    digits = "".join(character for character in raw if character.isdigit())
    if digits == "":
        return None
    return int(digits)


def _decimal(raw: str | None) -> Decimal | None:
    if raw is None or raw.strip() == "":
        return None
    cleaned = "".join(character for character in raw if character.isdigit() or character == ".")
    if cleaned == "" or cleaned == ".":
        return None
    return Decimal(cleaned)


def _codes(raw: str | None) -> tuple[str, ...]:
    if raw is None or raw.strip() == "":
        return ()
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def _job_kind(raw: str | None) -> JobKind:
    folded = (raw or "").casefold().replace("-", "_").replace(" ", "_")
    if folded in ("replacement", "swap", "tank_swap"):
        return JobKind.REPLACEMENT
    if folded in ("new_system", "new", "installation", "new_installation", "new_install"):
        return JobKind.NEW_SYSTEM
    if folded == "borehole":
        return JobKind.BOREHOLE
    return JobKind.UNKNOWN


def _sheet_job(raw: str | None) -> str | None:
    if raw in ("carport", "window", "door", "shutter"):
        return raw
    return None
