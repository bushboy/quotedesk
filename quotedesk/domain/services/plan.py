"""The next step for a conversation, chosen from the case and the published playbook."""

import re
from collections.abc import Mapping
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict

from quotedesk.domain.case.case_file import CaseFact, CaseFile, Job, price_ready, quote_issued, ready_values, status_of
from quotedesk.domain.case.contradictions import Clash, spec_choice, unresolved_clashes
from quotedesk.domain.case.facts import CaseFacts, ExtractionFacts, JobKind, SegmentationFacts
from quotedesk.domain.policy.playbook import BusinessPlaybook, FactDefinition, FactOption
from quotedesk.domain.policy.rules import Outcome, Policy
from quotedesk.domain.services.confidence import ConfidenceChecks, SizeSource
from quotedesk.domain.services.decide import decide
from quotedesk.domain.services.finish import chosen_sheet
from quotedesk.domain.shared.errors import PolicyViolation

_ASK = "What should I quote for you?"
_QUOTE = "I'll price that from the rate card."
STANDS = "The quote above still stands."
_REVISE = re.compile(r"\b(?:revise|revision|change|instead|different)\b", re.IGNORECASE)
_TWICE = "I've asked twice, so I won't ask again."
_UNSURE = "You don't know that, so I won't ask again."
_GREETING = re.compile(r"^(?:hi|hello|hey|good morning|good afternoon|good evening)\b", re.IGNORECASE)
_ORDER = {"escalate": 0, "inspection": 1, "confirm": 2, "ask": 3, "quote": 4}
_DECIDES = {"outcome": 0, "both": 1, "price": 2}
_EASE = {"easy": 0, "needs_tape": 1, "needs_expert": 2}
_PHOTO = " Or send a photo and I'll tell you what I see."
_CONFIDENCE = ("required_fields", "agreement", "measurement", "media_usable", "rate_card")
_TRUE = frozenset({"true", "yes", "y"})


class StepKind(str, Enum):
    ASK = "ask"
    CONFIRM = "confirm"
    QUOTE = "quote"
    INSPECTION = "inspection"
    ESCALATE = "escalate"


class Assumption(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    fact_key: str
    fact_label: str
    value_label: str
    evidence: str = ""


class Choice(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    label: str
    hint: str = ""


class NextStep(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: StepKind
    sentence: str
    job_id: str = ""
    job_label: str = ""
    fact_key: str = ""
    reason: str = ""
    rule_id: str = ""
    assumptions: tuple[Assumption, ...] = ()
    choices: tuple[Choice, ...] = ()


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
        steps = tuple(_job_step(job, case, playbook, policy, counts, customer_text) for job in case.jobs)
        step = min(steps, key=lambda item: _ORDER[item.kind.value])
    return _blur_notice(_phrase(step, playbook, customer_text), case)


def _opening(playbook: BusinessPlaybook) -> NextStep:
    if len(playbook.job_types) == 1:
        job = playbook.job_types[0]
        for fact in _ranked(job.facts):
            if fact.required and fact.question.strip() and _relevant(fact, job.key, {}):
                return _ask(job.key, _job_label(job), fact, False)
    if playbook.job_types:
        names = ", ".join(_job_label(job) for job in playbook.job_types[:4])
        return NextStep(kind=StepKind.ASK, sentence=f"What can we help with: {names}?", fact_key="job_type")
    return NextStep(kind=StepKind.ASK, sentence=_ASK, fact_key="job_type")


def wants_revision(text: str) -> bool:
    """The customer asked to change the quoted options. Anything else leaves the quote."""
    return _REVISE.search(text or "") is not None


def _job_step(
    job: Job,
    case: CaseFile,
    playbook: BusinessPlaybook,
    policy: Policy,
    asked: dict[str, int],
    customer_text: str = "",
) -> NextStep:
    if quote_issued(case, job.job_id) and not wants_revision(customer_text):
        return NextStep(kind=StepKind.ASK, sentence=STANDS, job_id=job.job_id)
    current = _current(case, job.job_id)
    play = _play_for(playbook, job)
    required = () if play is None else tuple(fact for fact in play.facts if fact.required)
    missing = None
    unknown = None
    inferred: list[tuple[FactDefinition, CaseFact]] = []
    seen = _has_photo(case)
    if play is not None:
        for fact in _ranked(required):
            if not _relevant(fact, job.job_type or "", current):
                continue
            active = case.active_fact(job.job_id, fact.key)
            if fact.key == "sheet" and _sheet_known(current, fact) and (active is None or status_of(active) not in ("inferred", "unknown")):
                continue
            if active is not None and status_of(active) == "unknown":
                unknown = unknown or fact
                continue
            if active is not None and status_of(active) == "inferred":
                if _confident(active, fact):
                    inferred.append((fact, active))
                elif missing is None:
                    missing = fact
                continue
            if active is None or not active.value.strip():
                if missing is None:
                    missing = fact
    decision = _decision(job, current, case, policy, () if play is None else _sheet_options(play))
    if decision is not None and not _fallback(decision.rule_id.value):
        step = _from_decision(decision, job.job_id)
        if step.kind in (StepKind.ESCALATE, StepKind.INSPECTION):
            return step
    waiting = unresolved_clashes(case, job.job_id)
    if waiting:
        return _clash_step(job.job_id, _job_label(play) if play is not None else "", waiting[0], play)
    if inferred:
        return _confirm(job.job_id, _job_label(play) if play is not None else "", inferred[:3])
    if missing is not None and asked.get(missing.key, 0) < 2:
        return _ask(job.job_id, _job_label(play) if play is not None else "", missing, seen)
    if missing is not None or unknown is not None:
        pending = missing or unknown
        if _ranges(pending, seen) and decision is not None:
            return _from_decision(decision, job.job_id)
        return _unsure(playbook, job.job_id, pending, missing is not None, seen, asked)
    if play is not None and not _ready(case, job, play, current):
        return NextStep(kind=StepKind.ASK, sentence=_ASK, job_id=job.job_id)
    if decision is None:
        return NextStep(kind=StepKind.QUOTE, sentence=_QUOTE, job_id=job.job_id)
    if decision.outcome is Outcome.FIXED_OFFER and spec_choice(case, job.job_id) is not True:
        if spec_choice(case, job.job_id) is False:
            return _declined(job, current, case, policy, () if play is None else _sheet_options(play), decision)
        return _replay(job.job_id, _job_label(play) if play is not None else "", case, play)
    return _from_decision(decision, job.job_id)


def _unsure(playbook: BusinessPlaybook, job_id: str, fact, twice: bool, seen: bool, asked: dict[str, int]) -> NextStep:
    mode = getattr(fact, "if_unsure", "inspection")
    if mode in ("ask_photo", "photo_then_range") and not seen and asked.get(fact.key, 0) < 2:
        return NextStep(
            kind=StepKind.ASK,
            sentence="A photo of that would help.",
            job_id=job_id,
            fact_key=fact.key,
        )
    if mode == "range" or (mode == "photo_then_range" and seen):
        return NextStep(kind=StepKind.QUOTE, sentence=_QUOTE, job_id=job_id)
    return _stop(playbook, job_id, fact, twice)


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


_BLUR = "That photo is hard to read. Do you have another picture?"


def _blur_notice(step: NextStep, case: CaseFile) -> NextStep:
    """A blur or an unreadable photo asks for another picture. It does not block a quote."""
    if step.kind not in (StepKind.ASK, StepKind.CONFIRM) or not step.job_id:
        return step
    if not any(job.job_id == step.job_id for job in case.jobs):
        return step
    fact = case.active_fact(step.job_id, "media_usable")
    if fact is None or fact.value.strip().casefold() not in ("false", "no", "n"):
        return step
    if _BLUR in step.sentence:
        return step
    return step.model_copy(update={"sentence": f"{step.sentence} {_BLUR}"})


def _phrase(step: NextStep, playbook: BusinessPlaybook, text: str) -> NextStep:
    outside = _outside(playbook, text)
    if outside and step.kind in (StepKind.ASK, StepKind.CONFIRM, StepKind.QUOTE):
        return NextStep(
            kind=StepKind.ESCALATE,
            sentence=outside,
            job_id=step.job_id,
            reason="This is outside what the business does.",
        )
    if step.kind not in (StepKind.ASK, StepKind.CONFIRM) or not text.strip():
        return step
    folded = text.casefold()
    for question in playbook.questions:
        topic = question.topic.strip().casefold()
        if topic and topic in folded and question.answer.strip():
            return step.model_copy(update={"sentence": f"{question.answer.strip()} {step.sentence}".strip()})
    if _GREETING.match(text.strip()) and playbook.hours.strip():
        return step.model_copy(update={"sentence": f"{playbook.hours.strip()} {step.sentence}".strip()})
    return step


_NAMED_TANK = frozenset(
    {
        "replacement",
        "swap",
        "tank_swap",
        "new_system",
        "new",
        "installation",
        "new_installation",
        "new_install",
    }
)


def _play_for(playbook: BusinessPlaybook, job: Job):
    key = job.job_type or ""
    found = next((item for item in playbook.job_types if item.key == key), None)
    if found is not None:
        return found
    if key == "tank":
        return next((item for item in playbook.job_types if item.key == "replacement"), None)
    return None


def fact_applies(key: str, job_key: str, current: Mapping[str, str] | None = None) -> bool:
    """Whether a playbook fact still has to be known for this job."""
    return _relevant(FactDefinition(key=key), job_key, dict(current or {}))


def _relevant(fact: FactDefinition, job_key: str, current: dict[str, str]) -> bool:
    """The stand and frame questions are skipped once the case has already said which."""
    if fact.key == "stand_present":
        named = (job_key or current.get("job_type") or "").casefold().replace("-", "_").replace(" ", "_")
        return named not in _NAMED_TANK
    if fact.key == "existing_frame":
        return not (current.get("opening") or "").strip()
    if fact.key == "stand":
        size = _whole(current.get("size_litres"))
        return size in (1000, 2500)
    if fact.key == "rain_harvest":
        return (current.get("supply") or "").strip().casefold() == "rainwater"
    return True


def _ranked(facts: tuple[FactDefinition, ...]) -> tuple[FactDefinition, ...]:
    ordered = sorted(enumerate(facts), key=lambda pair: (_DECIDES[pair[1].decides], _EASE[pair[1].ease], pair[0]))
    return tuple(fact for _, fact in ordered)


def _job_label(job) -> str:
    if job is None:
        return ""
    if job.label.strip():
        return job.label.strip()
    if job.description.strip():
        return job.description.strip()
    return job.key.replace("_", " ")


def _ask(job_id: str, job_label: str, fact: FactDefinition, seen: bool) -> NextStep:
    options = fact.options or tuple(FactOption(value=item, label=item) for item in fact.allowed)
    shown = options[:4]
    lines = [fact.question.strip() or _ASK]
    for index, option in enumerate(shown, start=1):
        hint = f" – {option.hint}" if option.hint else ""
        lines.append(f"{index}. {option.label}{hint}")
    sentence = "\n".join(lines)
    if fact.photo_can_answer and not seen:
        photo = _PHOTO.strip()
        sentence = f"{sentence}\n{photo}" if shown else f"{sentence} {_PHOTO.strip()}"
    return NextStep(
        kind=StepKind.ASK,
        sentence=sentence,
        job_id=job_id,
        job_label=job_label,
        fact_key=fact.key,
        choices=tuple(Choice(label=option.label, hint=option.hint) for option in shown),
    )


def _clash_step(job_id: str, job_label: str, clash: Clash, play) -> NextStep:
    customer = _clash_label(play, clash.key, clash.customer_value)
    evidence = _clash_label(play, clash.key, clash.evidence_value)
    why = f" ({clash.evidence})" if clash.evidence else ""
    return NextStep(
        kind=StepKind.CONFIRM,
        sentence=f"You said {customer}. The photo looks like {evidence}{why}. Which should I price?",
        job_id=job_id,
        job_label=job_label,
        fact_key=clash.key,
    )


def _replay(job_id: str, job_label: str, case: CaseFile, play) -> NextStep:
    parts: list[str] = []
    if play is not None:
        current = _current(case, job_id)
        for fact in play.facts:
            if not fact.required or not _relevant(fact, play.key, current):
                continue
            if fact.key == "sheet" and _sheet_known(current, fact):
                active = case.active_fact(job_id, "item_codes")
            else:
                active = case.active_fact(job_id, fact.key)
            if active is None or status_of(active) not in ("stated", "confirmed") or not active.value.strip():
                continue
            label = fact.label.strip() if fact.label.strip() else fact.key.replace("_", " ")
            parts.append(f"{label} {_plain(fact, active.value)}")
    for clash in clashes_settled(case, job_id):
        chosen = _clash_label(play, clash.key, clash.chosen_value)
        customer = _clash_label(play, clash.key, clash.customer_value)
        evidence = _clash_label(play, clash.key, clash.evidence_value)
        parts.append(f"You said {customer}. The photo looks like {evidence}. You confirmed {chosen}")
    body = ", ".join(parts) if parts else "the details you gave me"
    notes = [
        fact.value.strip()
        for fact in case.facts(job_id)
        if fact.key == "photo_note" and fact.superseded_by is None and fact.value.strip()
    ]
    noted = f" The photo notes: {'; '.join(notes)}." if notes else ""
    return NextStep(
        kind=StepKind.CONFIRM,
        sentence=f"I'll price this as: {body}.{noted} Is that the spec to price?",
        job_id=job_id,
        job_label=job_label,
        fact_key="spec_confirmed",
    )


def clashes_settled(case: CaseFile, job_id: str) -> tuple[Clash, ...]:
    from quotedesk.domain.case.contradictions import clashes_of

    return tuple(clash for clash in clashes_of(case, job_id) if clash.chosen_side)


def _clash_label(play, key: str, value: str) -> str:
    if play is None:
        return value
    for fact in play.facts:
        if fact.key == key:
            return _value_label(fact, value)
    return value


def _declined(job: Job, current: dict[str, str], case: CaseFile, policy: Policy, options, decision) -> NextStep:
    ranged = _decision(job, current, case, policy, options, force_open=True)
    if ranged is not None and ranged.outcome is not Outcome.FIXED_OFFER:
        return _from_decision(ranged, job.job_id)
    return NextStep(
        kind=StepKind.QUOTE,
        sentence="I won't send a fixed price until you confirm that spec.",
        job_id=job.job_id,
        reason=decision.reasons[0] if decision.reasons else "",
        rule_id=decision.rule_id.value,
    )


def _confirm(job_id: str, job_label: str, pairs: list[tuple[FactDefinition, CaseFact]]) -> NextStep:
    assumptions = tuple(
        Assumption(
            fact_key=fact.key,
            fact_label=fact.label or fact.question or fact.key,
            value_label=_value_label(fact, active.value),
            evidence=active.evidence,
        )
        for fact, active in pairs
    )
    parts = []
    for item in assumptions:
        why = f" ({item.evidence})" if item.evidence else ""
        parts.append(f"{item.fact_label} looks like {item.value_label}{why}")
    sentence = "From what I can see, " + ", and ".join(parts) + ". Is that right?"
    return NextStep(
        kind=StepKind.CONFIRM,
        sentence=sentence,
        job_id=job_id,
        job_label=job_label,
        fact_key=assumptions[0].fact_key,
        assumptions=assumptions,
    )


def _plain(fact: FactDefinition, value: str) -> str:
    folded = value.strip().casefold()
    if folded in ("true", "yes", "y"):
        return "yes"
    if folded in ("false", "no", "n"):
        return "no"
    return _value_label(fact, value)


def _value_label(fact: FactDefinition, value: str) -> str:
    for option in fact.options:
        if option.value == value:
            return option.label
    return value


def _confident(active: CaseFact, fact: FactDefinition) -> bool:
    if active.confidence is None:
        return False
    if fact.min_confidence is None:
        return True
    return active.confidence >= fact.min_confidence


def _has_photo(case: CaseFile) -> bool:
    for job in case.jobs:
        for fact in job.facts:
            if fact.source in ("photo_extraction", "video_extraction"):
                return True
    return False


def _outside(playbook: BusinessPlaybook, text: str) -> str | None:
    raw = playbook.does_not.strip()
    if not raw or not text.strip():
        return None
    words = re.findall(r"[a-z]{5,}", raw.casefold())
    if any(word in text.casefold() for word in words):
        return raw
    return None


def _ready(case: CaseFile, job: Job, play, current: dict[str, str]) -> bool:
    keys = []
    for fact in play.facts:
        if not fact.required:
            continue
        if not _relevant(fact, job.job_type or "", current):
            continue
        if fact.key == "sheet" and _sheet_known(current, fact):
            continue
        keys.append(fact.key)
    return price_ready(case, job.job_id, tuple(keys))


def _ranges(fact, seen: bool) -> bool:
    mode = getattr(fact, "if_unsure", "inspection")
    return mode == "range" or (mode == "photo_then_range" and seen)


def _sheet_options(job):
    for fact in job.facts:
        if fact.key == "sheet":
            return fact.options
    return ()


def _sheet_known(current: dict[str, str], fact: FactDefinition) -> bool:
    return chosen_sheet(current, fact.options) is not None


def _decision(job: Job, current: dict[str, str], case: CaseFile, policy: Policy, options=(), force_open: bool = False):
    if not policy.rules:
        return None
    try:
        facts = _case_facts(job, current, case, options)
        if force_open:
            facts = facts.model_copy(
                update={"checks": facts.checks.model_copy(update={"required_fields": False})}
            )
        return decide(facts, _extraction(current), SegmentationFacts(), policy)
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


def _case_facts(job: Job, current: dict[str, str], case: CaseFile, options=()) -> CaseFacts:
    confirmed = ready_values(case.facts(job.job_id)) if job.job_id else {}
    size = _whole(confirmed.get("size_litres"))
    source = confirmed.get("size_source")
    if source not in ("photo_inferred", "customer_stated", "reference_object") and size is not None:
        source = "customer_stated"
    opening = confirmed.get("opening")
    return CaseFacts(
        checks=_checks(current, case.facts(job.job_id) if job.job_id else ()),
        job=_job_kind(confirmed.get("job_type") or job.job_type),
        customer_text=current.get("customer_text"),
        size_litres=size,
        size_source=None if source is None else SizeSource(source),
        existing_level_base=_flag(confirmed, "existing_level_base"),
        installation_damaged=_flag(current, "installation_damaged"),
        simple_swap=_optional(confirmed, "simple_swap"),
        base_unconfirmed=_flag(confirmed, "base_unconfirmed"),
        new_tank_and_pump=_flag(confirmed, "new_tank_and_pump"),
        sloped_ground=_flag(current, "sloped_ground"),
        pipe_run_unknown=_flag(current, "pipe_run_unknown"),
        item_codes=_sheet_codes(confirmed, options),
        width_m=_decimal(confirmed.get("width_m")),
        length_m=_decimal(confirmed.get("length_m")),
        finish=_finish(confirmed, options),
        opening=opening if opening in ("existing", "new", "widened") else None,
        above_ground_floor=_flag(current, "above_ground_floor"),
        multi_unit=_flag(current, "multi_unit"),
        standard_band=_flag(confirmed, "standard_band"),
        budget=_decimal(confirmed.get("budget")),
        job_type=_sheet_job(confirmed.get("job_type") or job.job_type),
        pump=(confirmed.get("pump") or "").strip() or None,
    )


def _checks(current: dict[str, str], facts: tuple[CaseFact, ...] = ()) -> ConfidenceChecks:
    photo = any(
        fact.source in ("photo_extraction", "video_extraction") and fact.superseded_by is None and not fact.contested
        for fact in facts
    )
    if all(key not in current for key in _CONFIDENCE):
        met = not photo
        return ConfidenceChecks(
            required_fields=met,
            agreement=met,
            measurement=met,
            media_usable=met,
            rate_card=met,
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


def _sheet_codes(current: dict[str, str], options) -> tuple[str, ...]:
    found = chosen_sheet(current, options)
    if found is not None:
        return (found.code,)
    return _codes(current.get("item_codes"))


def _finish(current: dict[str, str], options) -> str | None:
    stated = current.get("finish")
    if stated is not None and stated.strip():
        return stated
    found = chosen_sheet(current, options)
    if found is not None:
        return found.label
    return None


def _job_kind(raw: str | None) -> JobKind:
    folded = (raw or "").casefold().replace("-", "_").replace(" ", "_")
    if folded in ("replacement", "swap", "tank_swap"):
        return JobKind.REPLACEMENT
    if folded in ("new_system", "new", "installation", "new_installation", "new_install"):
        return JobKind.NEW_SYSTEM
    if folded == "borehole":
        return JobKind.BOREHOLE
    if folded == "pump":
        return JobKind.PUMP
    return JobKind.UNKNOWN


def _sheet_job(raw: str | None) -> str | None:
    if raw in ("carport", "window", "door", "shutter"):
        return raw
    return None
