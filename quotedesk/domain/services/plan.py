"""The next step for a conversation, chosen from the case and the published playbook."""

import re
from collections.abc import Mapping
from decimal import Decimal
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict

from quotedesk.domain.case.case_file import CaseFact, CaseFile, Job, price_ready, quote_issued, ready_values, status_of
from quotedesk.domain.case.checklist import (
    ChecklistItem,
    accept_checklist,
    carport_checklist,
    checklist_confirmed,
    dismissed_sizes,
)
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
YES_NO = "Reply yes or no."
VISIT_ADDRESS = "What is the address for the visit?"
WHICH_CHANGE = "Which should I change: the size, the roof sheeting, or the installation?"
_CHANGE = re.compile(r"\b(?:revise|revision|change|changed|instead|different|switch)\b", re.IGNORECASE)
_PAIR = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:m|metre|meter)?s?\s*(?:by|x)\s*(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
_WIDTH_ONLY = re.compile(r"\bwidth\b\D{0,16}(\d+(?:\.\d+)?)", re.IGNORECASE)
_LENGTH_ONLY = re.compile(r"\blength\b\D{0,16}(\d+(?:\.\d+)?)", re.IGNORECASE)
_SIZE_WORD = re.compile(r"\b(?:size|width|length|wider|longer|bigger|smaller)\b", re.IGNORECASE)
_SHEET_WORD = re.compile(r"\b(?:sheet|sheeting|roof|roofing)\b", re.IGNORECASE)
_INSTALL_WORD = re.compile(
    r"\b(?:installation|freestanding|replacement)\b|\bexisting frame\b|\bnew carport\b",
    re.IGNORECASE,
)
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


_BAY_SIZE = {"1": ("3", "6"), "2": ("6", "6"), "3": ("9", "6")}
_SURE = Decimal("0.8")
_SHEET_WORDS = frozenset({"the", "a", "an", "sheeting", "roof", "sheet", "and", "or", "with"})
_SINGLE = re.compile(r"\b(?:single|one)(?:\s+|-)(?:car|bay|garage)\b", re.IGNORECASE)
_DOUBLE = re.compile(r"\b(?:double|two)(?:\s+|-)(?:car|bay|garage)s?\b", re.IGNORECASE)
_NEW_CARPORT = re.compile(r"\bnew carport\b|\bnew altogether\b", re.IGNORECASE)


def assume_from_context(
    case: CaseFile,
    playbook: BusinessPlaybook,
    notes: tuple[str, ...] = (),
    customer_text: str = "",
) -> CaseFile:
    """Record what the photo and the customer's words already support, as inferences to confirm."""
    joined = "\n".join(note.strip() for note in notes if note and note.strip())
    case = _open_mentioned_job(case, playbook, customer_text, joined)
    if not case.jobs:
        return case
    job = case.jobs[0]
    play = _play_for(playbook, job)
    if play is None:
        return case
    event_id = uuid4()
    photo_sheet = _sheet_from_text(play, joined)
    said_sheet = _sheet_from_text(play, customer_text)
    if photo_sheet is not None and said_sheet is not None and photo_sheet[0] != said_sheet[0]:
        case = _infer(case, job.job_id, "sheet", photo_sheet[0], "photo_extraction", event_id, photo_sheet[1])
        case = _infer(case, job.job_id, "sheet", said_sheet[0], "customer_text", event_id, said_sheet[1])
    else:
        chosen = photo_sheet or said_sheet
        if chosen is not None:
            source = "photo_extraction" if photo_sheet is not None else "customer_text"
            case = _infer(case, job.job_id, "sheet", chosen[0], source, event_id, chosen[1])
    readings = _bay_readings(customer_text, joined)
    if len(readings) == 1:
        bays, evidence, source = readings[0]
        case = _infer(case, job.job_id, "bays", bays, source, event_id, evidence)
    for bays, evidence, source in readings:
        width, length = _BAY_SIZE[bays]
        case = _infer_size(case, job.job_id, width, length, source, event_id, evidence)
    for value, evidence, source in _frame_clues(customer_text, joined):
        case = _infer(case, job.job_id, "existing_frame", value, source, event_id, evidence)
    return case


def _open_mentioned_job(case: CaseFile, playbook: BusinessPlaybook, customer_text: str, notes: str) -> CaseFile:
    if case.jobs or not playbook.job_types:
        return case
    blob = f"{customer_text}\n{notes}".casefold()
    matches = []
    for job in playbook.job_types:
        names = [job.key.replace("_", " "), job.description, job.label]
        if any(name.strip() and name.casefold() in blob for name in names):
            matches.append(job)
    if len(matches) != 1:
        return case
    job = matches[0]
    return case.add_job(job.key, job.key)


def _infer(case: CaseFile, job_id: str, key: str, value: str, source: str, event_id: UUID, evidence: str) -> CaseFile:
    if case.active_fact(job_id, f"rejected:{key}") is not None:
        return case
    active = case.active_fact(job_id, key)
    if active is None or not active.value.strip() or status_of(active) == "unknown":
        return _write_inferred(case, job_id, key, value, source, event_id, evidence)
    if active.value == value:
        return case
    return _hold_second(case, job_id, key, value, source, event_id, evidence)


def _infer_size(case: CaseFile, job_id: str, width: str, length: str, source: str, event_id: UUID, evidence: str) -> CaseFile:
    """A size value is the width and the length together. A disagreement is a second pair."""
    if f"{width}x{length}" in dismissed_sizes(case, job_id):
        return case
    width_fact = case.active_fact(job_id, "width_m")
    length_fact = case.active_fact(job_id, "length_m")
    if _open_measure(width_fact) and _open_measure(length_fact):
        case = _infer(case, job_id, "width_m", width, source, event_id, evidence)
        return _infer(case, job_id, "length_m", length, source, event_id, evidence)
    if (
        not _open_measure(width_fact)
        and not _open_measure(length_fact)
        and width_fact is not None
        and length_fact is not None
        and width_fact.value == width
        and length_fact.value == length
    ):
        return case
    if not _open_measure(width_fact) and width_fact is not None and width_fact.value == width and _open_measure(length_fact):
        return _infer(case, job_id, "length_m", length, source, event_id, evidence)
    if not _open_measure(length_fact) and length_fact is not None and length_fact.value == length and _open_measure(width_fact):
        return _infer(case, job_id, "width_m", width, source, event_id, evidence)
    case = _hold_second(case, job_id, "width_m", width, source, event_id, evidence)
    return _hold_second(case, job_id, "length_m", length, source, event_id, evidence)


def _open_measure(fact: CaseFact | None) -> bool:
    return fact is None or not fact.value.strip() or status_of(fact) == "unknown"


def _write_inferred(case: CaseFile, job_id: str, key: str, value: str, source: str, event_id: UUID, evidence: str) -> CaseFile:
    return case.record_fact(
        job_id,
        uuid4(),
        key,
        value,
        source,  # type: ignore[arg-type]
        event_id,
        status="inferred",
        evidence=evidence,
        confidence=_SURE,
    )


def _hold_second(case: CaseFile, job_id: str, key: str, value: str, source: str, event_id: UUID, evidence: str) -> CaseFile:
    """The second inferred value. It does not replace the one already held."""
    alt = f"alt:{key}"
    current = case.active_fact(job_id, alt)
    if current is not None and current.value == value:
        return case
    return _write_inferred(case, job_id, alt, value, source, event_id, evidence)


def _sheet_from_text(play, notes: str) -> tuple[str, str] | None:
    folded = notes.casefold()
    best: tuple[int, str, str] | None = None
    for fact in play.facts:
        if fact.key != "sheet":
            continue
        for option in fact.options:
            words = [
                word
                for word in re.findall(r"[a-z0-9]+", option.label.casefold())
                if word not in _SHEET_WORDS and len(word) > 2
            ]
            if not words or not all(word in folded for word in words):
                continue
            score = sum(len(word) for word in words)
            line = next((item for item in notes.split("\n") if all(word in item.casefold() for word in words)), notes)
            if best is None or score > best[0]:
                best = (score, option.value, line.strip())
    if best is None:
        return None
    return best[1], best[2]


def _bay_count(text: str) -> str | None:
    counts = _bay_counts(text)
    if len(counts) == 1:
        return counts[0]
    return None


def _bay_counts(text: str) -> tuple[str, ...]:
    found: list[str] = []
    if _SINGLE.search(text or "") is not None:
        found.append("1")
    if _DOUBLE.search(text or "") is not None:
        found.append("2")
    return tuple(found)


def _bay_readings(customer_text: str, notes: str) -> tuple[tuple[str, str, str], ...]:
    """One size when the customer or the photo names it. Both, when the photo shows both."""
    said = _bay_count(customer_text)
    if said is not None:
        return ((said, _bay_evidence(said, customer_text), "customer_text"),)
    return tuple(
        (count, _bay_evidence(count, ""), "photo_extraction") for count in _bay_counts(notes)
    )


def _bay_evidence(bays: str, customer_text: str) -> str:
    width, length = _BAY_SIZE[bays]
    size = f"about {width} by {length} m"
    if bays == "1" and _SINGLE.search(customer_text or ""):
        return f"You asked for a single car. One bay is {size}"
    if bays == "2" and _DOUBLE.search(customer_text or ""):
        return f"You asked for two bays. That is {size}"
    if bays == "1":
        return f"The photo shows a single bay. That is {size}"
    return f"The photo shows two bays. That is {size}"


def _frame_clues(customer_text: str, notes: str) -> tuple[tuple[str, str, str], ...]:
    """Up to two installation readings. A photo and a sentence can disagree."""
    clues: list[tuple[str, str, str]] = []

    def add(value: str, evidence: str, source: str) -> None:
        if any(item[0] == value for item in clues):
            return
        clues.append((value, evidence, source))

    if _NEW_CARPORT.search(customer_text or ""):
        add("false", "You said this is a new carport, so this is not onto an existing frame", "customer_text")
    if re.search(r"\bexisting frame\b|\bonto the existing\b", customer_text or "", re.IGNORECASE):
        add("true", "You said this is onto the existing frame", "customer_text")
    if re.search(r"\bfreestanding\b", notes or "", re.IGNORECASE):
        add("false", "From the photo, the carport is freestanding, so this is not onto an existing frame", "photo_extraction")
    return tuple(clues[:2])


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


def ask_for_visit_address(case: CaseFile, step: NextStep) -> NextStep:
    """A visit is offered with its reason. The address is asked before it is booked."""
    if step.kind is not StepKind.INSPECTION or not step.job_id:
        return step
    if not any(job.job_id == step.job_id for job in case.jobs):
        return step
    fact = case.active_fact(step.job_id, "address")
    if fact is not None and fact.value.strip():
        return step
    sentence = step.sentence.rstrip()
    if VISIT_ADDRESS not in sentence:
        sentence = f"{sentence} {VISIT_ADDRESS}"
    return step.model_copy(update={"kind": StepKind.ASK, "sentence": sentence, "fact_key": "address"})


def wants_revision(text: str) -> bool:
    """The customer asked to change the quoted options. Anything else leaves the quote."""
    return _REVISE.search(text or "") is not None


def reopen_after_quote(case: CaseFile, playbook: BusinessPlaybook, text: str) -> CaseFile:
    """After a quote, a change withdraws it and sends that checklist item back to inferred."""
    if not (text or "").strip() or not case.jobs:
        return case
    updated = case
    touched = False
    event_id = uuid4()
    for job in case.jobs:
        if (job.job_type or "") != "carport" or not _revision_open(updated, job.job_id):
            continue
        play = _play_for(playbook, job)
        if play is None:
            continue
        items = _revision_items(play, text, updated, job.job_id)
        if items is None:
            continue
        touched = True
        if not items:
            updated = _ask_which(updated, job.job_id, event_id)
        else:
            updated = _apply_revision(updated, play, job.job_id, items, text, event_id)
    return updated if touched else case


def quote_needs_reconfirm(case: CaseFile, playbook: BusinessPlaybook) -> bool:
    """A stored quote waits while a checklist item is back open."""
    for job in case.jobs:
        if _awaiting_change(case, job.job_id):
            return True
        items = carport_checklist(case, job, _play_for(playbook, job))
        if items is not None and not checklist_confirmed(items):
            return True
    return False


def _revision_open(case: CaseFile, job_id: str) -> bool:
    return quote_issued(case, job_id) or spec_choice(case, job_id) is True


def _awaiting_change(case: CaseFile, job_id: str) -> bool:
    fact = case.active_fact(job_id, "awaiting_change")
    return fact is not None and fact.value.strip().casefold() in ("true", "yes")


def _revision_items(play, text: str, case: CaseFile, job_id: str) -> tuple[str, ...] | None:
    mentions = _mentioned_items(text)
    changed = _changed_values(play, text, case, job_id)
    asked = _CHANGE.search(text or "") is not None
    if changed:
        chosen = set(changed)
        if asked:
            chosen |= mentions
        return _ordered(chosen)
    if asked and mentions:
        return _ordered(mentions)
    if asked:
        return ()
    return None


def _picked_items(play, text: str, case: CaseFile, job_id: str) -> tuple[str, ...]:
    return _ordered(_mentioned_items(text) | _changed_values(play, text, case, job_id))


def _ordered(items: set[str]) -> tuple[str, ...]:
    return tuple(item for item in ("size", "sheet", "installation") if item in items)


def _mentioned_items(text: str) -> set[str]:
    found: set[str] = set()
    if _SIZE_WORD.search(text or ""):
        found.add("size")
    if _SHEET_WORD.search(text or ""):
        found.add("sheet")
    if _INSTALL_WORD.search(text or ""):
        found.add("installation")
    return found


def _changed_values(play, text: str, case: CaseFile, job_id: str) -> set[str]:
    found: set[str] = set()
    said = _sheet_from_text(play, text)
    current_sheet = case.active_fact(job_id, "sheet")
    if said is not None and (current_sheet is None or current_sheet.value != said[0]):
        found.add("sheet")
    pair = _stated_pair(text)
    if pair is not None and pair != _current_pair(case, job_id):
        found.add("size")
    elif pair is None:
        width = _WIDTH_ONLY.search(text or "")
        length = _LENGTH_ONLY.search(text or "")
        current = _current_pair(case, job_id)
        if width is not None and (current is None or _clean_num(width.group(1)) != current[0]):
            found.add("size")
        if length is not None and (current is None or _clean_num(length.group(1)) != current[1]):
            found.add("size")
    frame = _stated_frame(text)
    if frame is not None and frame != _current_frame(case, job_id):
        found.add("installation")
    return found


def _stated_pair(text: str) -> tuple[str, str] | None:
    match = _PAIR.search(text or "")
    if match is not None:
        return (_clean_num(match.group(1)), _clean_num(match.group(2)))
    bays = _bay_count(text or "")
    if bays is not None:
        return _BAY_SIZE[bays]
    return None


def _current_pair(case: CaseFile, job_id: str) -> tuple[str, str] | None:
    width = case.active_fact(job_id, "width_m")
    length = case.active_fact(job_id, "length_m")
    if width is None or length is None or not width.value.strip() or not length.value.strip():
        return None
    return (_clean_num(width.value), _clean_num(length.value))


def _stated_frame(text: str) -> str | None:
    if re.search(r"\bexisting frame\b|\bonto the existing\b|\breplacement\b", text or "", re.IGNORECASE):
        return "true"
    if re.search(r"\bfreestanding\b|\bnew carport\b|\bnew installation\b|\bnew altogether\b", text or "", re.IGNORECASE):
        return "false"
    return None


def _current_frame(case: CaseFile, job_id: str) -> str | None:
    fact = case.active_fact(job_id, "existing_frame")
    if fact is not None and fact.value.strip():
        folded = fact.value.strip().casefold()
        if folded in ("true", "yes"):
            return "true"
        if folded in ("false", "no"):
            return "false"
    opening = case.active_fact(job_id, "opening")
    if opening is None:
        return None
    if opening.value.strip().casefold() == "existing":
        return "true"
    if opening.value.strip().casefold() == "new":
        return "false"
    return None


def _clean_num(value: str) -> str:
    number = Decimal(value)
    if number == number.to_integral():
        return str(int(number))
    return format(number.normalize(), "f")


def _ask_which(case: CaseFile, job_id: str, event_id: UUID) -> CaseFile:
    updated = _withdraw_quote(case, job_id, event_id)
    if _awaiting_change(updated, job_id):
        return updated
    return updated.record_fact(
        job_id,
        uuid4(),
        "awaiting_change",
        "true",
        "customer_text",
        event_id,
        status="confirmed",
    )


def _apply_revision(case: CaseFile, play, job_id: str, items: tuple[str, ...], text: str, event_id: UUID) -> CaseFile:
    updated = _withdraw_quote(case, job_id, event_id)
    updated = updated.retire_fact(job_id, "awaiting_change", event_id)
    changed = _changed_values(play, text, case, job_id)
    for item in items:
        if item not in changed and _asks_for_options(text):
            updated = _clear_item(updated, job_id, item, event_id)
        else:
            updated = _demote_item(updated, play, job_id, item, text, event_id)
    return updated


_OPTIONS = re.compile(r"\b(?:options|option|choices|choice|different|another|other)\b", re.IGNORECASE)


def _asks_for_options(text: str) -> bool:
    return _OPTIONS.search(text or "") is not None


def _rejects_inference(text: str) -> bool:
    from quotedesk.domain.case.contradictions import spec_answer

    return spec_answer(text) == "yes" and (_CHANGE.search(text or "") is not None or _asks_for_options(text))


def _reject_the_item(case: CaseFile, reply: str, event_id: UUID) -> CaseFile:
    folded = reply.casefold()
    if "the size is " in folded or "the size looks like " in folded or "could be " in folded:
        item = "size"
    elif "sheeting" in folded or "the roof" in folded:
        item = "sheet"
    elif "the installation is " in folded:
        item = "installation"
    else:
        return case
    updated = case
    for job in case.jobs:
        updated = _clear_item(updated, job.job_id, item, event_id)
    return updated


def _clear_item(case: CaseFile, job_id: str, item: str, event_id: UUID) -> CaseFile:
    keys = {
        "size": ("width_m", "length_m"),
        "sheet": ("sheet",),
        "installation": ("existing_frame", "opening"),
    }[item]
    updated = case
    for key in keys:
        updated = updated.reject_assumption(job_id, key, uuid4(), event_id)
        updated = updated.retire_fact(job_id, key, event_id)
        updated = updated.retire_fact(job_id, f"alt:{key}", event_id)
    return updated.retire_fact(job_id, f"unknown:{item}", event_id)


def _withdraw_quote(case: CaseFile, job_id: str, event_id: UUID) -> CaseFile:
    updated = case.retire_fact(job_id, "spec_confirmed", event_id)
    if not quote_issued(updated, job_id):
        return updated
    return updated.record_fact(
        job_id,
        uuid4(),
        "quote_issued",
        "false",
        "customer_text",
        event_id,
        status="confirmed",
    )


def _demote_item(case: CaseFile, play, job_id: str, item: str, text: str, event_id: UUID) -> CaseFile:
    if item == "size":
        return _demote_size(case, job_id, text, event_id)
    if item == "sheet":
        return _demote_sheet(case, play, job_id, text, event_id)
    return _demote_installation(case, job_id, text, event_id)


def _demote_size(case: CaseFile, job_id: str, text: str, event_id: UUID) -> CaseFile:
    pair = _stated_pair(text)
    width = pair[0] if pair is not None else None
    length = pair[1] if pair is not None else None
    if pair is None:
        width_match = _WIDTH_ONLY.search(text or "")
        length_match = _LENGTH_ONLY.search(text or "")
        if width_match is not None:
            width = _clean_num(width_match.group(1))
        if length_match is not None:
            length = _clean_num(length_match.group(1))
    updated = case.reopen_fact(job_id, "width_m", event_id, value=width)
    updated = updated.reopen_fact(job_id, "length_m", event_id, value=length)
    return updated.retire_fact(job_id, "unknown:size", event_id)


def _demote_sheet(case: CaseFile, play, job_id: str, text: str, event_id: UUID) -> CaseFile:
    said = _sheet_from_text(play, text)
    value = None if said is None else said[0]
    updated = case.reopen_fact(job_id, "sheet", event_id, value=value)
    if value is not None:
        updated = updated.reopen_fact(job_id, "item_codes", event_id, value=value)
    return updated.retire_fact(job_id, "unknown:sheet", event_id)


def _demote_installation(case: CaseFile, job_id: str, text: str, event_id: UUID) -> CaseFile:
    updated = case.reopen_fact(job_id, "existing_frame", event_id, value=_stated_frame(text))
    opening = updated.active_fact(job_id, "opening")
    if opening is not None and opening.value.strip().casefold() in ("new", "existing"):
        updated = updated.reopen_fact(job_id, "opening", event_id)
    updated = updated.reopen_fact(job_id, "installation", event_id)
    return updated.retire_fact(job_id, "unknown:installation", event_id)


def _job_step(
    job: Job,
    case: CaseFile,
    playbook: BusinessPlaybook,
    policy: Policy,
    asked: dict[str, int],
    customer_text: str = "",
) -> NextStep:
    if _awaiting_change(case, job.job_id):
        return NextStep(kind=StepKind.ASK, sentence=WHICH_CHANGE, job_id=job.job_id, fact_key="revision")
    if quote_issued(case, job.job_id) and not wants_revision(customer_text):
        return NextStep(kind=StepKind.ASK, sentence=STANDS, job_id=job.job_id)
    current = _current(case, job.job_id)
    play = _play_for(playbook, job)
    seen = _has_photo(case)
    decision = _decision(job, current, case, policy, () if play is None else _sheet_options(play))
    if decision is not None and not _fallback(decision.rule_id.value):
        step = _from_decision(decision, job.job_id)
        if step.kind in (StepKind.ESCALATE, StepKind.INSPECTION):
            return step
    waiting = unresolved_clashes(case, job.job_id)
    if waiting:
        return _clash_step(job.job_id, _job_label(play) if play is not None else "", waiting[0], play)
    if decision is not None and decision.outcome is Outcome.FIXED_OFFER and spec_choice(case, job.job_id) is False:
        return _declined(job, current, case, policy, () if play is None else _sheet_options(play), decision)
    if play is not None and (job.job_type or "") == "carport":
        gate = _carport_gate(job, case, play, seen)
        if gate is not None:
            return gate
        if spec_choice(case, job.job_id) is not True:
            return _replay(job.job_id, _job_label(play), case, play)
    elif play is not None and spec_choice(case, job.job_id) is not True:
        one = _one_fact(job, case, play, seen, asked, playbook)
        if one is not None:
            return one
        if _checklist_done(case, job, play, current):
            return _replay(job.job_id, _job_label(play), case, play)
    if play is not None and not _ready(case, job, play, current):
        return NextStep(kind=StepKind.ASK, sentence=_ASK, job_id=job.job_id)
    if decision is None:
        return NextStep(kind=StepKind.QUOTE, sentence=_QUOTE, job_id=job.job_id)
    if decision.outcome is Outcome.FIXED_OFFER and spec_choice(case, job.job_id) is not True:
        if spec_choice(case, job.job_id) is False:
            return _declined(job, current, case, policy, () if play is None else _sheet_options(play), decision)
        return _replay(job.job_id, _job_label(play) if play is not None else "", case, play)
    return _from_decision(decision, job.job_id)


def _carport_gate(job: Job, case: CaseFile, play, seen: bool) -> NextStep | None:
    """The first carport checklist item that is not confirmed. None when all three are."""
    items = carport_checklist(case, job, play)
    if items is None or checklist_confirmed(items):
        return None
    item = _next_checklist_item(items)
    label = _job_label(play)
    if item is None:
        missing = [_item_name(held.key) for held in items if held.status == "unknown"]
        return NextStep(
            kind=StepKind.ASK,
            sentence=f"We can't price this until you know the {_join(missing)}.",
            job_id=job.job_id,
            job_label=label,
            fact_key=missing[0] if missing else "size",
        )
    if item.status == "inferred" and len(item.values) == 2:
        return _which(job.job_id, label, item)
    if item.status == "inferred" and len(item.values) == 1:
        return _confirm_checklist(job.job_id, label, play, item)
    return _ask_checklist(job.job_id, label, play, case, item, seen)


def _next_checklist_item(items: tuple[ChecklistItem, ...]) -> ChecklistItem | None:
    """A confident inference jumps ahead of a blank item. A stated value stays in order."""
    pending = [item for item in items if item.status not in ("confirmed", "unknown")]
    if not pending:
        return None
    if pending[0].values:
        return pending[0]
    for later in pending[1:]:
        if later.values and any(value.confidence is not None and value.confidence >= _SURE for value in later.values):
            return later
    return pending[0]


def _confirm_checklist(job_id: str, job_label: str, play, item: ChecklistItem) -> NextStep:
    value = item.values[0]
    if item.key == "sheet":
        fact = _defined(play, "sheet")
        photo = value.source in ("photo_extraction", "video_extraction")
        return _assume(job_id, job_label, fact, value.raw, photo, value.evidence, fact.type)
    if item.key == "installation":
        if value.evidence.strip():
            sentence = f"{value.evidence.strip().rstrip('.')}. The installation is {value.label}. Is that right? {YES_NO}"
        else:
            sentence = f"The installation is {value.label}. Is that right? {YES_NO}"
        return NextStep(
            kind=StepKind.CONFIRM,
            sentence=sentence,
            job_id=job_id,
            job_label=job_label,
            fact_key="installation",
            assumptions=(Assumption(fact_key="installation", fact_label="Installation", value_label=value.label, evidence=value.evidence),),
        )
    if value.evidence.strip():
        lead = f"{value.evidence.strip().rstrip('.')}. The size looks like {value.label}"
    elif value.source in ("photo_extraction", "video_extraction"):
        lead = f"From the photo, the size looks like {value.label}"
    else:
        lead = f"You said the size is {value.label}"
    return NextStep(
        kind=StepKind.CONFIRM,
        sentence=f"{lead}. Is that right? {YES_NO}",
        job_id=job_id,
        job_label=job_label,
        fact_key="size",
        assumptions=(Assumption(fact_key="size", fact_label="Size", value_label=value.label, evidence=value.evidence),),
    )


def _which(job_id: str, job_label: str, item: ChecklistItem) -> NextStep:
    left, right = item.values
    if right.source == "customer_text" and left.source != "customer_text":
        left, right = right, left
    if left.source == "customer_text" and right.source in ("photo_extraction", "video_extraction"):
        sentence = f"You said {left.label}. The photo looks like {right.label}. Which should I price?"
    elif left.source == "customer_text":
        sentence = f"You said {left.label}. You also said {right.label}. Which should I price?"
    else:
        sentence = f"The photo could be {left.label} or {right.label}. Which should I price?"
    return NextStep(
        kind=StepKind.CONFIRM,
        sentence=sentence,
        job_id=job_id,
        job_label=job_label,
        fact_key=item.key,
        assumptions=tuple(
            Assumption(fact_key=item.key, fact_label=_item_name(item.key), value_label=value.label, evidence=value.evidence)
            for value in (left, right)
        ),
    )


def _ask_checklist(job_id: str, job_label: str, play, case: CaseFile, item: ChecklistItem, seen: bool) -> NextStep:
    if item.key == "size":
        return _ask_size(job_id, job_label, play, case, seen)
    if item.key == "sheet":
        return _ask(job_id, job_label, _defined(play, "sheet"), seen)
    return _ask(job_id, job_label, _defined(play, "existing_frame"), seen)


def _ask_size(job_id: str, job_label: str, play, case: CaseFile, seen: bool) -> NextStep:
    width = case.active_fact(job_id, "width_m")
    length = case.active_fact(job_id, "length_m")
    width_known = width is not None and width.value.strip() and case.active_fact(job_id, "rejected:width_m") is None
    length_known = length is not None and length.value.strip() and case.active_fact(job_id, "rejected:length_m") is None
    if width_known and not length_known and width is not None:
        return NextStep(
            kind=StepKind.ASK,
            sentence=f"You said the width is {width.value} m. What is the length in metres?",
            job_id=job_id,
            job_label=job_label,
            fact_key="length_m",
        )
    if length_known and not width_known and length is not None:
        return NextStep(
            kind=StepKind.ASK,
            sentence=f"You said the length is {length.value} m. What is the width in metres?",
            job_id=job_id,
            job_label=job_label,
            fact_key="width_m",
        )
    return _ask(job_id, job_label, _defined(play, "width_m"), seen)


def _defined(play, key: str) -> FactDefinition:
    found = next((fact for fact in play.facts if fact.key == key), None)
    if found is not None:
        return found
    return FactDefinition(key=key, question=_ASK)


def _item_name(key: str) -> str:
    return {"size": "size", "sheet": "roof sheeting", "installation": "installation"}.get(key, key)


def _join(names: list[str]) -> str:
    if not names:
        return "sheet, the size, and the installation"
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " and the " + names[-1]


def _one_fact(job: Job, case: CaseFile, play, seen: bool, asked: dict[str, int], playbook: BusinessPlaybook) -> NextStep | None:
    """The first required fact that still needs its own question.

    A value already taken from the photo or the customer's words is confirmed
    before a blank question is asked.
    """
    current = _current(case, job.job_id)
    label = _job_label(play)
    pending: list[FactDefinition] = []
    for fact in play.facts:
        if not fact.required or not fact.question.strip() or not _relevant(fact, job.job_type or "", current):
            continue
        if _settled(case, job.job_id, fact, current):
            continue
        pending.append(fact)
    for index, fact in enumerate(pending):
        active, value = _answer(case, job.job_id, fact, current)
        if active is not None and value.strip() and status_of(active) != "unknown":
            return _question_for(job, case, playbook, label, fact, seen, asked)
        inferred = _pending_inference(case, job.job_id, pending[index + 1 :], current)
        if inferred is not None:
            return _question_for(job, case, playbook, label, inferred, seen, asked)
        return _question_for(job, case, playbook, label, fact, seen, asked)
    return None


def _pending_inference(case: CaseFile, job_id: str, later: list[FactDefinition], current: dict[str, str]) -> FactDefinition | None:
    """A photo or message inference waiting behind a blank question."""
    found: list[tuple[int, FactDefinition]] = []
    for index, fact in enumerate(later):
        active, value = _answer(case, job_id, fact, current)
        if active is None or not value.strip() or status_of(active) != "inferred" or not _confident(active, fact):
            continue
        found.append((index, fact))
    if not found:
        return None
    return sorted(found, key=lambda item: (_EASE[item[1].ease], item[0]))[0][1]


def _question_for(
    job: Job,
    case: CaseFile,
    playbook: BusinessPlaybook,
    label: str,
    fact: FactDefinition,
    seen: bool,
    asked: dict[str, int],
) -> NextStep:
    current = _current(case, job.job_id)
    active, value = _answer(case, job.job_id, fact, current)
    rejected = case.active_fact(job.job_id, f"rejected:{fact.key}") is not None
    if active is not None and status_of(active) == "unknown":
        return _unsure(playbook, job.job_id, fact, False, seen, asked)
    if rejected or active is None or not value.strip():
        if asked.get(fact.key, 0) >= 2:
            return _unsure(playbook, job.job_id, fact, True, seen, asked)
        return _ask(job.job_id, label, fact, seen)
    if status_of(active) == "inferred" and not _confident(active, fact):
        if asked.get(fact.key, 0) >= 2:
            return _unsure(playbook, job.job_id, fact, True, seen, asked)
        return _ask(job.job_id, label, fact, seen)
    if asked.get(fact.key, 0) >= 2:
        return _unsure(playbook, job.job_id, fact, True, seen, asked)
    photo = active.source in ("photo_extraction", "video_extraction")
    return _assume(job.job_id, label, fact, value, photo, active.evidence, fact.type)


def _settled(case: CaseFile, job_id: str, fact: FactDefinition, current: dict[str, str]) -> bool:
    if _acked(case, job_id, fact.key):
        return True
    active, value = _answer(case, job_id, fact, current)
    return active is not None and bool(value.strip()) and status_of(active) == "confirmed"


def _checklist_done(case: CaseFile, job: Job, play, current: dict[str, str]) -> bool:
    required = [fact for fact in play.facts if fact.required and fact.question.strip() and _relevant(fact, job.job_type or "", current)]
    return bool(required) and all(_settled(case, job.job_id, fact, current) for fact in required)


def _fact_name(fact: FactDefinition) -> str:
    if fact.label.strip():
        return fact.label.strip().casefold()
    key = fact.key[:-2] if fact.key.endswith("_m") else fact.key
    return key.replace("_", " ")


def _acked(case: CaseFile, job_id: str, key: str) -> bool:
    fact = case.active_fact(job_id, f"ack:{key}")
    return fact is not None and fact.value.strip().casefold() in _TRUE


def _answer(case: CaseFile, job_id: str, fact: FactDefinition, current: dict[str, str]) -> tuple[CaseFact | None, str]:
    active = case.active_fact(job_id, fact.key)
    if fact.key == "sheet" and _sheet_known(current, fact):
        choice = chosen_sheet(current, fact.options)
        holder = active if active is not None and active.value.strip() else case.active_fact(job_id, "item_codes")
        if choice is not None and holder is not None:
            return holder, choice.value
    if active is None:
        return None, ""
    return active, active.value


def _assume(
    job_id: str,
    job_label: str,
    fact: FactDefinition,
    value: str,
    photo: bool,
    evidence: str,
    fact_type: str = "",
) -> NextStep:
    shown = _shown(fact, value)
    name = _fact_name(fact)
    if fact_type == "yes_no" and evidence.strip():
        lead = evidence.strip().rstrip(".")
    elif photo:
        why = f" ({evidence})" if evidence else ""
        lead = f"From the photo, the {name} looks like {shown}{why}"
    elif evidence.strip():
        lead = f"{evidence.strip().rstrip('.')}. The {name} looks like {shown}"
    else:
        lead = f"You said the {name} is {shown}"
    return NextStep(
        kind=StepKind.CONFIRM,
        sentence=f"{lead}. Is that right? {YES_NO}",
        job_id=job_id,
        job_label=job_label,
        fact_key=fact.key,
        assumptions=(
            Assumption(
                fact_key=fact.key,
                fact_label=fact.label or fact.question or fact.key,
                value_label=shown,
                evidence=evidence,
            ),
        ),
    )


def _shown(fact: FactDefinition, value: str) -> str:
    plain = _plain(fact, value)
    if fact.type == "number" and fact.unit and not plain.endswith(fact.unit):
        return f"{plain} {fact.unit}"
    return plain


def question_brief(case: CaseFile, playbook: BusinessPlaybook, customer_name: str = "", name_settled: bool = True) -> str:
    """What this turn's prompt tells the model is already answered, and what is still waiting."""
    done: list[str] = []
    waiting: list[str] = []
    if name_settled and customer_name.strip():
        done.append(f"name: {customer_name.strip()}")
    elif not name_settled:
        waiting.append("name")
    for job in case.jobs:
        play = _play_for(playbook, job)
        if play is None:
            continue
        items = carport_checklist(case, job, play)
        if items is not None:
            for item in items:
                label = _item_name(item.key)
                if item.status == "confirmed" and item.values:
                    done.append(f"{label}: {item.values[0].label}")
                elif item.status == "unknown":
                    done.append(f"{label}: the customer does not know")
                else:
                    waiting.append(label)
            continue
        current = _current(case, job.job_id)
        for fact in play.facts:
            if not fact.required or not fact.question.strip() or not _relevant(fact, job.job_type or "", current):
                continue
            label = fact.label.strip() or _fact_name(fact)
            if _settled(case, job.job_id, fact, current):
                _active, value = _answer(case, job.job_id, fact, current)
                done.append(f"{label}: {_shown(fact, value)}" if value else label)
            else:
                waiting.append(label)
    if not done:
        done.append("none")
    if not waiting:
        waiting.append("the spec replay")
    return (
        "Already acknowledged:\n"
        + "\n".join(f"- {item}" for item in done)
        + "\nNot yet acknowledged. Ask only the one question in the next step:\n"
        + "\n".join(f"- {item}" for item in waiting)
        + "\nDo not ask an acknowledged fact again. Do not ask finish, gutters, or bays unless the customer mentions them. "
        "The name is only for how you address them and for the quote. It is not a price fact. "
        "Do not add a second question."
    )


def take_customer_answer(case: CaseFile, playbook: BusinessPlaybook, last_reply: str, text: str, event_id: UUID):
    """A reply to the one question just asked acknowledges that fact and no other."""
    from quotedesk.domain.case.contradictions import spec_answer

    reply = last_reply or ""
    if not reply.strip() or not text.strip() or not case.jobs:
        return case
    if "Is that right?" in reply and _rejects_inference(text):
        return _reject_the_item(case, reply, event_id)
    if VISIT_ADDRESS in reply:
        place = text.strip()
        if not place:
            return case
        updated = case
        for job in case.jobs:
            updated = updated.record_fact(job.job_id, uuid4(), "address", place, "customer_text", event_id)
        return updated
    if WHICH_CHANGE in reply:
        updated = case
        for job in case.jobs:
            play = _play_for(playbook, job)
            if play is None:
                continue
            picked = _picked_items(play, text, updated, job.job_id)
            if not picked:
                return case
            updated = _apply_revision(updated, play, job.job_id, picked, text, event_id)
        return updated
    if "Is that the spec to price?" in reply:
        return case
    chosen = accept_checklist(case, playbook, reply, text, event_id)
    if chosen is not case:
        return chosen
    if "Which should I price?" in reply:
        return case
    if "Is that right?" not in reply:
        return _take_fresh(case, playbook, reply, text, event_id)
    answer = spec_answer(text)
    if answer is None:
        return case
    for job in case.jobs:
        play = _play_for(playbook, job)
        if play is None:
            continue
        current = _current(case, job.job_id)
        for fact in play.facts:
            if not fact.required or not _relevant(fact, job.job_type or "", current):
                continue
            name = _fact_name(fact)
            folded = reply.casefold()
            if f"the {name} is " not in folded and f"the {name} looks like " not in folded:
                continue
            if answer == "yes":
                return case.acknowledge(job.job_id, fact.key, uuid4(), event_id)
            return case.reject_assumption(job.job_id, fact.key, uuid4(), event_id)
    return case


def _take_fresh(case: CaseFile, playbook: BusinessPlaybook, reply: str, text: str, event_id: UUID):
    if "Is that right?" in reply:
        return case
    for job in case.jobs:
        play = _play_for(playbook, job)
        if play is None:
            continue
        current = _current(case, job.job_id)
        for fact in play.facts:
            if not fact.required or not fact.question.strip() or fact.question not in reply:
                continue
            if not _relevant(fact, job.job_type or "", current) or _settled(case, job.job_id, fact, current):
                continue
            value = _parse_answer(fact, text)
            if value is None:
                return case
            updated = case.record_fact(job.job_id, uuid4(), fact.key, value, "customer_text", event_id)
            option = next((item for item in fact.options if item.value == value), None)
            if option is not None and option.item_codes:
                updated = updated.record_fact(
                    job.job_id,
                    uuid4(),
                    "item_codes",
                    option.item_codes[0],
                    "customer_text",
                    event_id,
                )
            return updated.acknowledge(job.job_id, fact.key, uuid4(), event_id)
    return case


def _parse_answer(fact: FactDefinition, text: str) -> str | None:
    from quotedesk.domain.case.contradictions import spec_answer

    if fact.type == "yes_no":
        answer = spec_answer(text)
        if answer == "yes":
            return "true"
        if answer == "no":
            return "false"
        return None
    options = fact.options or tuple(FactOption(value=item, label=item) for item in fact.allowed)
    if fact.type == "choice" or options:
        lead = re.match(r"\s*(\d+)\b", text.strip())
        if lead:
            index = int(lead.group(1)) - 1
            if 0 <= index < len(options):
                return options[index].value
        lowered = text.casefold()
        for option in options:
            if option.label.casefold() in lowered or option.value.casefold() in lowered:
                return option.value
        return None
    if fact.type == "number":
        match = re.search(r"\d+(?:\.\d+)?", text)
        return match.group(0) if match else None
    stripped = text.strip()
    return stripped or None


def _bookkeeping(key: str) -> bool:
    return key.startswith(("ack:", "rejected:", "clash:", "alt:", "unknown:", "dismissed:")) or key in {
        "spec_confirmed",
        "name_acknowledged",
        "quote_issued",
        "awaiting_change",
    }


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
    shown = options
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
            if active is None or not active.value.strip():
                continue
            settled = status_of(active) in ("stated", "confirmed") or (
                status_of(active) == "inferred" and _acked(case, job_id, fact.key)
            )
            if not settled:
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
        sentence=f"I'll price this as: {body}.{noted} Is that the spec to price? {YES_NO}",
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
        if fact.superseded_by is not None or fact.contested or fact.key in values or _bookkeeping(fact.key):
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
        # A photo is not proof the sheet is off the rate card. That false flag
        # drops the band to low and the fallback becomes a site measure.
        met = not photo
        return ConfidenceChecks(
            required_fields=met,
            agreement=met,
            measurement=met,
            media_usable=met,
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
