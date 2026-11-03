"""The clash record. The planner replays a photo that disagrees with what the customer said."""

import re
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict

from quotedesk.domain.case.case_file import CaseFact, status_of


class Contradiction(BaseModel):
    """The Contradiction."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    job_id: str
    key: str
    fact_id: UUID
    other_fact_id: UUID


class Clash(BaseModel):
    """One price fact where the customer and other evidence disagree."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    job_id: str
    key: str
    customer_value: str
    evidence_value: str
    evidence: str = ""
    chosen_value: str = ""
    chosen_side: str = ""


def clashes_of(case, job_id: str) -> tuple[Clash, ...]:
    """Both sides of each clash, and the side the customer already chose."""
    facts = case.facts(job_id)
    keys: list[str] = []
    for fact in facts:
        if (
            fact.key.startswith(("clash:", "ack:", "rejected:"))
            or fact.key in {"spec_confirmed", "name_acknowledged"}
            or fact.key in keys
        ):
            continue
        keys.append(fact.key)
    found: list[Clash] = []
    for key in keys:
        evidence_facts = [fact for fact in facts if fact.key == key and fact.source in ("photo_extraction", "video_extraction")]
        customer_facts = [
            fact
            for fact in facts
            if fact.key == key and fact.source in ("customer_text", "voice_transcript", "owner")
        ]
        if not evidence_facts or not customer_facts:
            continue
        evidence = evidence_facts[-1]
        stated = [fact for fact in customer_facts if fact.value != evidence.value]
        customer = stated[-1] if stated else None
        if customer is None:
            continue
        side, chosen = _chosen(case, job_id, key, customer.value, evidence.value)
        found.append(
            Clash(
                job_id=job_id,
                key=key,
                customer_value=customer.value,
                evidence_value=evidence.value,
                evidence=evidence.evidence,
                chosen_value=chosen,
                chosen_side=side,
            )
        )
    return tuple(found)


def unresolved_clashes(case, job_id: str) -> tuple[Clash, ...]:
    """The clashes the customer has not settled."""
    return tuple(clash for clash in clashes_of(case, job_id) if not clash.chosen_side)


def spec_answer(text: str) -> str | None:
    """A yes or a no at the start of the reply. Later words do not change it."""
    folded = text.strip().casefold()
    if re.match(r"(?:yes|yep|yeah|correct)\b", folded):
        return "yes"
    if re.match(r"(?:no|nope)\b", folded):
        return "no"
    return None


def accept_spec_reply(case, last_reply: str, text: str, event_id: UUID):
    """A yes or no after the replay, or a chosen side after a clash question."""
    folded = text.strip().casefold()
    answer = spec_answer(text)
    updated = case
    for job in case.jobs:
        if "Is that the spec to price?" in last_reply and spec_choice(updated, job.job_id) is None:
            if answer == "yes":
                updated = updated.confirm_spec(job.job_id, uuid4(), event_id)
            elif answer == "no":
                updated = updated.decline_spec(job.job_id, uuid4(), event_id)
        if "Which should I price?" not in last_reply:
            continue
        for clash in unresolved_clashes(updated, job.job_id):
            evidence = clash.evidence_value.casefold()
            customer = clash.customer_value.casefold()
            if evidence and evidence in folded and customer not in folded:
                updated = updated.resolve_clash(job.job_id, clash.key, "evidence", uuid4(), event_id)
            elif customer and customer in folded:
                updated = updated.resolve_clash(job.job_id, clash.key, "customer", uuid4(), event_id)
    return updated


def spec_choice(case, job_id: str) -> bool | None:
    """True when the customer accepted the replay, false when they declined, otherwise unset."""
    fact = case.active_fact(job_id, "spec_confirmed")
    if fact is None or fact.state == "unknown" or not fact.value.strip():
        return None
    return fact.value.strip().casefold() in ("true", "yes")


def _chosen(case, job_id: str, key: str, customer_value: str, evidence_value: str) -> tuple[str, str]:
    fact = case.active_fact(job_id, f"clash:{key}")
    if fact is None or fact.state == "unknown" or fact.value not in ("customer", "evidence"):
        return "", ""
    if fact.value == "customer":
        return "customer", customer_value
    return "evidence", evidence_value


def detect_contradiction(existing: CaseFact, new: CaseFact) -> Contradiction | None:
    """Two stated sources that name different values."""
    if existing.key != new.key or existing.value == new.value:
        return None
    if status_of(existing) != "stated" or status_of(new) != "stated":
        return None
    if existing.source != new.source:
        return Contradiction(
            job_id=existing.job_id,
            key=existing.key,
            fact_id=existing.fact_id,
            other_fact_id=new.fact_id,
        )
    return None
