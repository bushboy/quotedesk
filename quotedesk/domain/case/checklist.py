"""The carport quote gate. Three items, each initial, inferred, confirmed, or unknown.

Facts stay the evidence. A checklist item can hold one supporting value, or two when
the photo and the customer's words disagree. A quote waits until sheet, size, and
installation are each confirmed. The customer's name is not one of these items.
"""

import re
from decimal import Decimal
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict

from quotedesk.domain.case.case_file import CaseFact, CaseFile, status_of
from quotedesk.domain.case.contradictions import spec_answer

ChecklistStatus = Literal["initial", "inferred", "confirmed", "unknown"]
_TRUE = frozenset({"true", "yes", "y"})
_SIZE = ("width_m", "length_m")
_SKIP = frozenset({"the", "a", "an", "sheeting", "roof", "sheet", "and", "or", "with"})


class ChecklistValue(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    raw: str
    label: str
    evidence: str = ""
    source: str = ""
    confidence: Decimal | None = None


class ChecklistItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    status: ChecklistStatus
    values: tuple[ChecklistValue, ...] = ()


def carport_checklist(case: CaseFile, job, play) -> tuple[ChecklistItem, ...] | None:
    """Sheet, size, and installation for a carport. Other jobs keep the playbook facts."""
    if (getattr(job, "job_type", None) or "") != "carport" or play is None:
        return None
    if not any(getattr(fact, "key", None) == "sheet" for fact in getattr(play, "facts", ())):
        return None
    job_id = job.job_id
    return (
        _size_item(case, job_id),
        _sheet_item(case, job_id, play),
        _installation_item(case, job_id),
    )


def checklist_confirmed(items: tuple[ChecklistItem, ...] | None) -> bool:
    """True when every gate item has been accepted. Unknown is not accepted."""
    return items is not None and bool(items) and all(item.status == "confirmed" for item in items)


def accept_checklist(case: CaseFile, playbook, reply: str, text: str, event_id: UUID) -> CaseFile:
    """A yes, a no, or a chosen side on the carport checklist. Other replies pass through."""
    if not reply.strip() or not text.strip() or not case.jobs:
        return case
    for job in case.jobs:
        play = _play(playbook, job)
        items = carport_checklist(case, job, play)
        if items is None:
            continue
        if "Which should I price?" in reply:
            chosen = _choose(case, job.job_id, items, text, event_id)
            if chosen is not case:
                return chosen
            continue
        if "Is that right?" not in reply:
            continue
        answer = spec_answer(text)
        if answer is None:
            continue
        folded = reply.casefold()
        if "the size is " in folded or "the size looks like " in folded:
            return _answer_size(case, job.job_id, answer, event_id)
        if "the installation is " in folded:
            return _answer_installation(case, job.job_id, answer, event_id)
    return case


def mark_unknown(case: CaseFile, job_id: str, key: str, event_id: UUID) -> CaseFile:
    """The customer does not know this item. Any inference already stored stays attached."""
    item = {"width_m": "size", "length_m": "size", "sheet": "sheet", "existing_frame": "installation", "opening": "installation"}.get(key)
    if item is None:
        return case
    marker = f"unknown:{item}"
    if case.active_fact(job_id, marker) is not None:
        return case
    return case.record_fact(job_id, uuid4(), marker, "true", "customer_text", event_id, status="confirmed")


def _size_item(case: CaseFile, job_id: str) -> ChecklistItem:
    values = tuple(
        pair
        for pair in (_pair(case, job_id, "width_m", "length_m"), _pair(case, job_id, "alt:width_m", "alt:length_m"))
        if pair is not None
    )
    return ChecklistItem(key="size", status=_status(case, job_id, "size", values, _size_confirmed(case, job_id, values)), values=values)


def _sheet_item(case: CaseFile, job_id: str, play) -> ChecklistItem:
    values: list[ChecklistValue] = []
    for key in ("sheet", "alt:sheet"):
        fact = _live(case, job_id, key)
        if fact is None:
            continue
        values.append(_sheet_value(play, fact))
    if not values:
        coded = _sheet_from_codes(case, job_id, play)
        if coded is not None:
            values.append(coded)
    kept = tuple(values[:2])
    return ChecklistItem(key="sheet", status=_status(case, job_id, "sheet", kept, _sheet_confirmed(case, job_id, kept)), values=kept)


def _installation_item(case: CaseFile, job_id: str) -> ChecklistItem:
    values = _installation_values(case, job_id)
    return ChecklistItem(
        key="installation",
        status=_status(case, job_id, "installation", values, _installation_confirmed(case, job_id, values)),
        values=values,
    )


def _status(case: CaseFile, job_id: str, item: str, values: tuple[ChecklistValue, ...], confirmed: bool) -> ChecklistStatus:
    marker = case.active_fact(job_id, f"unknown:{item}")
    if marker is not None and marker.value.strip().casefold() in _TRUE:
        return "unknown"
    if confirmed and len(values) == 1:
        return "confirmed"
    if values:
        return "inferred"
    return "initial"


def _size_confirmed(case: CaseFile, job_id: str, values: tuple[ChecklistValue, ...]) -> bool:
    if len(values) != 1:
        return False
    return all(_acked(case, job_id, key) or _settled_fact(case, job_id, key) for key in _SIZE)


def _sheet_confirmed(case: CaseFile, job_id: str, values: tuple[ChecklistValue, ...]) -> bool:
    if len(values) != 1:
        return False
    return _acked(case, job_id, "sheet") or _settled_fact(case, job_id, "sheet")


def _installation_confirmed(case: CaseFile, job_id: str, values: tuple[ChecklistValue, ...]) -> bool:
    if len(values) != 1:
        return False
    if _acked(case, job_id, "existing_frame") or _acked(case, job_id, "installation"):
        return True
    if _settled_fact(case, job_id, "existing_frame"):
        return True
    opening = _live(case, job_id, "opening")
    return opening is not None and status_of(opening) in ("stated", "confirmed")


def _settled_fact(case: CaseFile, job_id: str, key: str) -> bool:
    fact = _live(case, job_id, key)
    return fact is not None and status_of(fact) == "confirmed"


def _pair(case: CaseFile, job_id: str, width_key: str, length_key: str) -> ChecklistValue | None:
    width = _live(case, job_id, width_key)
    length = _live(case, job_id, length_key)
    if width is None or length is None or not width.value.strip() or not length.value.strip():
        return None
    evidence = width.evidence.strip() or length.evidence.strip()
    confidence = width.confidence if width.confidence is not None else length.confidence
    return ChecklistValue(
        raw=f"{width.value}x{length.value}",
        label=f"{_number(width.value)} m by {_number(length.value)} m",
        evidence=evidence,
        source=width.source,
        confidence=confidence,
    )


def _installation_values(case: CaseFile, job_id: str) -> tuple[ChecklistValue, ...]:
    found: list[ChecklistValue] = []
    for key in ("existing_frame", "alt:existing_frame", "opening", "alt:opening"):
        fact = _live(case, job_id, key)
        if fact is None:
            continue
        value = _installation_value(fact)
        if value is None or any(item.raw == value.raw for item in found):
            continue
        found.append(value)
        if len(found) == 2:
            break
    return tuple(found)


def _installation_value(fact: CaseFact) -> ChecklistValue | None:
    folded = fact.value.strip().casefold()
    if fact.key.endswith("existing_frame"):
        if folded in _TRUE:
            raw, label = "replacement", "a replacement on the existing frame"
        elif folded in ("false", "no", "n"):
            raw, label = "new", "a new installation"
        else:
            return None
    elif folded == "new":
        raw, label = "new", "a new installation"
    elif folded == "existing":
        raw, label = "replacement", "a replacement on the existing frame"
    else:
        return None
    return ChecklistValue(raw=raw, label=label, evidence=fact.evidence, source=fact.source, confidence=fact.confidence)


def _sheet_value(play, fact: CaseFact) -> ChecklistValue:
    return ChecklistValue(
        raw=fact.value,
        label=_option_label(play, "sheet", fact.value),
        evidence=fact.evidence,
        source=fact.source,
        confidence=fact.confidence,
    )


def _sheet_from_codes(case: CaseFile, job_id: str, play) -> ChecklistValue | None:
    if case.active_fact(job_id, "rejected:sheet") is not None:
        return None
    codes = case.active_fact(job_id, "item_codes")
    if codes is None or not codes.value.strip():
        return None
    for fact in getattr(play, "facts", ()):
        if fact.key != "sheet":
            continue
        for option in fact.options:
            if option.value in codes.value or any(code in codes.value for code in option.item_codes):
                return ChecklistValue(raw=option.value, label=option.label, evidence=codes.evidence, source=codes.source)
    return None


def _live(case: CaseFile, job_id: str, key: str) -> CaseFact | None:
    bare = key.split(":", 1)[-1]
    if case.active_fact(job_id, f"rejected:{bare}") is not None and not key.startswith("alt:"):
        return None
    fact = case.active_fact(job_id, key)
    if fact is None or not fact.value.strip() or status_of(fact) == "unknown":
        return None
    return fact


def _acked(case: CaseFile, job_id: str, key: str) -> bool:
    fact = case.active_fact(job_id, f"ack:{key}")
    return fact is not None and fact.value.strip().casefold() in _TRUE


def _answer_size(case: CaseFile, job_id: str, answer: str, event_id: UUID) -> CaseFile:
    if answer == "yes":
        return _accept_pair(case, job_id, "width_m", "length_m", event_id)
    return _reject_pair(case, job_id, event_id)


def _answer_installation(case: CaseFile, job_id: str, answer: str, event_id: UUID) -> CaseFile:
    if answer == "no":
        updated = case.reject_assumption(job_id, "existing_frame", uuid4(), event_id)
        updated = updated.retire_fact(job_id, "alt:existing_frame", uuid4())
        return updated.retire_fact(job_id, "unknown:installation", uuid4())
    updated = _confirm_key(case, job_id, "existing_frame", event_id)
    if updated.active_fact(job_id, "ack:installation") is None and updated.active_fact(job_id, "existing_frame") is None:
        updated = updated.record_fact(job_id, uuid4(), "ack:installation", "true", "customer_text", event_id, status="confirmed")
    elif updated.active_fact(job_id, "ack:existing_frame") is None and updated.active_fact(job_id, "existing_frame") is not None:
        updated = updated.acknowledge(job_id, "existing_frame", uuid4(), event_id)
    return updated.retire_fact(job_id, "unknown:installation", uuid4())


def _choose(case: CaseFile, job_id: str, items: tuple[ChecklistItem, ...], text: str, event_id: UUID) -> CaseFile:
    for item in items:
        if item.status != "inferred" or len(item.values) != 2:
            continue
        picked = [value for value in item.values if _mentions(text, value.label)]
        if len(picked) != 1:
            continue
        chosen = picked[0]
        if item.key == "sheet":
            return _accept_sheet(case, job_id, chosen, event_id)
        if item.key == "size":
            width, length = chosen.raw.split("x", 1)
            return _write_pair(case, job_id, width, length, chosen.evidence, event_id)
        return _accept_installation_raw(case, job_id, chosen.raw, chosen.evidence, event_id)
    return case


def _accept_pair(case: CaseFile, job_id: str, width_key: str, length_key: str, event_id: UUID) -> CaseFile:
    updated = _confirm_key(case, job_id, width_key, event_id)
    updated = _confirm_key(updated, job_id, length_key, event_id)
    updated = updated.retire_fact(job_id, "alt:width_m", uuid4())
    updated = updated.retire_fact(job_id, "alt:length_m", uuid4())
    return updated.retire_fact(job_id, "unknown:size", uuid4())


def _write_pair(case: CaseFile, job_id: str, width: str, length: str, evidence: str, event_id: UUID) -> CaseFile:
    updated = _write_confirmed(case, job_id, "width_m", width, evidence, event_id)
    updated = _write_confirmed(updated, job_id, "length_m", length, evidence, event_id)
    updated = updated.retire_fact(job_id, "alt:width_m", uuid4())
    updated = updated.retire_fact(job_id, "alt:length_m", uuid4())
    return updated.retire_fact(job_id, "unknown:size", uuid4())


def _accept_sheet(case: CaseFile, job_id: str, chosen: ChecklistValue, event_id: UUID) -> CaseFile:
    updated = _write_confirmed(case, job_id, "sheet", chosen.raw, chosen.evidence, event_id)
    updated = updated.retire_fact(job_id, "alt:sheet", uuid4())
    return updated.retire_fact(job_id, "unknown:sheet", uuid4())


def _accept_installation_raw(case: CaseFile, job_id: str, raw: str, evidence: str, event_id: UUID) -> CaseFile:
    value = "true" if raw == "replacement" else "false"
    updated = _write_confirmed(case, job_id, "existing_frame", value, evidence, event_id)
    updated = updated.retire_fact(job_id, "alt:existing_frame", uuid4())
    return updated.retire_fact(job_id, "unknown:installation", uuid4())


def _confirm_key(case: CaseFile, job_id: str, key: str, event_id: UUID) -> CaseFile:
    active = case.active_fact(job_id, key)
    updated = case
    if active is not None and status_of(active) == "inferred":
        updated = updated.confirm(job_id, key, uuid4(), event_id)
    if updated.active_fact(job_id, f"ack:{key}") is None and updated.active_fact(job_id, key) is not None:
        updated = updated.acknowledge(job_id, key, uuid4(), event_id)
    return updated


def _write_confirmed(case: CaseFile, job_id: str, key: str, value: str, evidence: str, event_id: UUID) -> CaseFile:
    active = case.active_fact(job_id, key)
    if active is None or active.value != value or status_of(active) != "confirmed":
        updated = case.record_fact(
            job_id,
            uuid4(),
            key,
            value,
            "customer_text",
            event_id,
            status="confirmed",
            evidence=evidence,
        )
    else:
        updated = case
    if updated.active_fact(job_id, f"ack:{key}") is None:
        updated = updated.acknowledge(job_id, key, uuid4(), event_id)
    return updated


def _reject_pair(case: CaseFile, job_id: str, event_id: UUID) -> CaseFile:
    updated = case.reject_assumption(job_id, "width_m", uuid4(), event_id)
    updated = updated.reject_assumption(job_id, "length_m", uuid4(), event_id)
    updated = updated.retire_fact(job_id, "alt:width_m", uuid4())
    updated = updated.retire_fact(job_id, "alt:length_m", uuid4())
    return updated.retire_fact(job_id, "unknown:size", uuid4())


def _mentions(text: str, label: str) -> bool:
    words = [
        word
        for word in re.findall(r"[a-z0-9]+", label.casefold())
        if word not in _SKIP and (len(word) > 2 or word.isdigit())
    ]
    folded = text.casefold()
    return bool(words) and all(word in folded for word in words)


def _option_label(play, key: str, value: str) -> str:
    for fact in getattr(play, "facts", ()):
        if fact.key != key:
            continue
        for option in fact.options:
            if option.value == value:
                return option.label
    return value


def _number(value: str) -> str:
    cleaned = value.strip()
    if cleaned.endswith(".0"):
        return cleaned[:-2]
    return cleaned


def _play(playbook, job):
    key = getattr(job, "job_type", None) or ""
    return next((item for item in getattr(playbook, "job_types", ()) if item.key == key), None)
