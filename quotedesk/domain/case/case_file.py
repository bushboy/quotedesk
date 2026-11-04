"""The case file. The planner and the quote use case read the facts the conversation has recorded."""

from decimal import Decimal
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict

from quotedesk.domain.shared.errors import PolicyViolation, ValidationError

FactSource = Literal[
    "customer_text",
    "voice_transcript",
    "photo_extraction",
    "video_extraction",
    "owner",
]
FactState = Literal["known", "unknown"]
FactStatus = Literal["stated", "inferred", "confirmed", "contested", "unknown"]
_INFERRED_SOURCES = frozenset({"photo_extraction", "video_extraction"})
_READY = frozenset({"stated", "confirmed"})
JobStatus = Literal["gathering", "quoted", "held", "closed"]

_EVENT = "A fact names the event it came from."
_ONE = "A fact key has one current value."
_CONTRADICTED = "That fact is contradicted."
_MISSING = "That fact is not on the case."
_JOB = "That job is not on the case."


class CaseFact(BaseModel):
    """The CaseFact."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    fact_id: UUID
    job_id: str
    key: str
    value: str
    source: FactSource
    event_id: UUID
    state: FactState = "known"
    status: FactStatus = "stated"
    evidence: str = ""
    confidence: Decimal | None = None
    superseded_by: UUID | None = None
    contested: bool = False


class Job(BaseModel):
    """The Job."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    job_id: str
    job_type: str | None
    status: JobStatus
    facts: tuple[CaseFact, ...] = ()


class CaseFile(BaseModel):
    """The CaseFile."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    conversation_id: UUID
    tenant_id: UUID
    jobs: tuple[Job, ...] = ()
    contradictions: tuple[Any, ...] = ()

    def __init__(self, **data: Any) -> None:
        _require_one_current(data.get("jobs") or ())
        super().__init__(**data)

    @classmethod
    def open(cls, conversation_id: UUID, tenant_id: UUID) -> "CaseFile":
        return cls(conversation_id=conversation_id, tenant_id=tenant_id)

    def add_job(self, job_id: str, job_type: str | None) -> "CaseFile":
        job = Job(job_id=job_id, job_type=job_type, status="gathering")
        return self.model_copy(update={"jobs": self.jobs + (job,)})

    def record_fact(
        self,
        job_id: str,
        fact_id: UUID,
        key: str,
        value: str,
        source: FactSource,
        event_id: UUID | None,
        *,
        state: FactState = "known",
        status: FactStatus | None = None,
        evidence: str = "",
        confidence: Decimal | None = None,
    ) -> "CaseFile":
        if event_id is None:
            raise ValidationError(code="fact.event_required", sentence=_EVENT)
        job = self._job(job_id)
        chosen = status or derived_status(source, state)
        if state == "unknown":
            chosen = "unknown"
        new = CaseFact(
            fact_id=fact_id,
            job_id=job_id,
            key=key,
            value=value,
            source=source,
            event_id=event_id,
            state=state,
            status=chosen,
            evidence=evidence,
            confidence=confidence,
        )
        active = self.active_fact(job_id, key)
        if active is None:
            return self._write(job_id, job.facts + (new,))
        active_status = status_of(active)
        new_status = status_of(new)
        if active_status in _READY and new_status == "inferred":
            if active.value == new.value:
                return self
            return self._keep_evidence(job_id, job.facts, active, new)
        if active_status == "inferred" and new_status in _READY:
            return self._replace(job_id, job.facts, active, new)
        from quotedesk.domain.case.contradictions import detect_contradiction

        found = detect_contradiction(active, new)
        if found is None:
            return self._replace(job_id, job.facts, active, new)
        contested = tuple(
            fact.model_copy(update={"contested": True, "status": "contested"})
            if fact.fact_id == active.fact_id
            else fact
            for fact in job.facts
        )
        stored = new.model_copy(update={"contested": True, "status": "contested"})
        return self._write(job_id, contested + (stored,), self.contradictions + (found,))

    def acknowledge(self, job_id: str, key: str, fact_id: UUID, event_id: UUID) -> "CaseFile":
        """The customer accepted this one fact. The whole spec is still unconfirmed."""
        if self.active_fact(job_id, f"ack:{key}") is not None:
            return self._without_mark(job_id, f"rejected:{key}")
        updated = self.record_fact(
            job_id,
            fact_id,
            f"ack:{key}",
            "true",
            "customer_text",
            event_id,
            status="confirmed",
        )
        return updated._without_mark(job_id, f"rejected:{key}")

    def retire_fact(self, job_id: str, key: str, by: UUID) -> "CaseFile":
        """Drop the current value for a key. The row stays, marked as replaced."""
        active = self.active_fact(job_id, key)
        if active is None:
            return self
        facts = tuple(
            fact.model_copy(update={"superseded_by": by}) if fact.fact_id == active.fact_id else fact
            for fact in self.facts(job_id)
        )
        return self._write(job_id, facts)

    def reopen_fact(
        self,
        job_id: str,
        key: str,
        event_id: UUID,
        *,
        value: str | None = None,
        evidence: str = "",
    ) -> "CaseFile":
        """A confirmed fact the customer wants to change becomes inferred again."""
        updated = self._without_mark(job_id, f"ack:{key}")._without_mark(job_id, f"rejected:{key}")
        updated = updated.retire_fact(job_id, f"alt:{key}", event_id)
        active = updated.active_fact(job_id, key)
        if active is None:
            if value is None or not str(value).strip():
                return updated
            return updated.record_fact(
                job_id,
                uuid4(),
                key,
                value,
                "customer_text",
                event_id,
                status="inferred",
                evidence=evidence,
                confidence=Decimal("0.8"),
            )
        if value is None or value == active.value:
            facts = tuple(
                fact.model_copy(update={"status": "inferred", "state": "known", "contested": False})
                if fact.fact_id == active.fact_id
                else fact
                for fact in updated.facts(job_id)
            )
            return updated._write(job_id, facts)
        updated = updated.retire_fact(job_id, key, event_id)
        return updated.record_fact(
            job_id,
            uuid4(),
            key,
            value,
            "customer_text",
            event_id,
            status="inferred",
            evidence=evidence,
            confidence=Decimal("0.8"),
        )

    def reject_assumption(self, job_id: str, key: str, fact_id: UUID, event_id: UUID) -> "CaseFile":
        """A no on one fact. Ask it fresh, and do not treat the old value as accepted."""
        updated = self._without_mark(job_id, f"ack:{key}")
        if updated.active_fact(job_id, f"rejected:{key}") is not None:
            return updated
        return updated.record_fact(
            job_id,
            fact_id,
            f"rejected:{key}",
            "true",
            "customer_text",
            event_id,
            status="confirmed",
        )

    def start_over(self, job_id: str) -> "CaseFile":
        self._job(job_id)
        jobs = tuple(
            job.model_copy(update={"status": "closed"}) if job.job_id == job_id else job
            for job in self.jobs
        )
        return self.model_copy(update={"jobs": jobs})

    def confirm(self, job_id: str, key: str, fact_id: UUID, event_id: UUID) -> "CaseFile":
        """A yes on a confirm step. The inferred value becomes confirmed."""
        active = self.active_fact(job_id, key)
        if active is None or status_of(active) != "inferred":
            return self
        confirmed = active.model_copy(
            update={
                "fact_id": fact_id,
                "event_id": event_id,
                "status": "confirmed",
                "state": "known",
                "superseded_by": None,
                "contested": False,
            }
        )
        return self._replace(job_id, self._job(job_id).facts, active, confirmed)

    def confirm_spec(self, job_id: str, fact_id: UUID, event_id: UUID) -> "CaseFile":
        """A yes on the replay. Inferred price facts become confirmed."""
        updated = self
        for fact in self.facts(job_id):
            if fact.superseded_by is None and not fact.contested and status_of(fact) == "inferred":
                updated = updated.confirm(job_id, fact.key, uuid4(), event_id)
        return updated.record_fact(
            job_id,
            fact_id,
            "spec_confirmed",
            "true",
            "customer_text",
            event_id,
            status="confirmed",
        )

    def decline_spec(self, job_id: str, fact_id: UUID, event_id: UUID) -> "CaseFile":
        """A no on the replay. A fixed quote stays withheld."""
        return self.record_fact(
            job_id,
            fact_id,
            "spec_confirmed",
            "false",
            "customer_text",
            event_id,
            status="confirmed",
        )

    def resolve_clash(self, job_id: str, key: str, side: str, fact_id: UUID, event_id: UUID) -> "CaseFile":
        """Remember which side the customer chose. The chosen value becomes the current fact."""
        from quotedesk.domain.case.contradictions import unresolved_clashes

        clash = next((item for item in unresolved_clashes(self, job_id) if item.key == key), None)
        if clash is None or side not in ("customer", "evidence"):
            return self
        chosen = clash.customer_value if side == "customer" else clash.evidence_value
        updated = self
        active = updated.active_fact(job_id, key)
        if active is None or active.value != chosen:
            updated = updated.record_fact(
                job_id,
                uuid4(),
                key,
                chosen,
                "customer_text",
                event_id,
                status="confirmed",
            )
        else:
            confirmed = active.model_copy(update={"status": "confirmed", "contested": False, "state": "known"})
            facts = tuple(
                confirmed if fact.fact_id == active.fact_id else fact for fact in updated.facts(job_id)
            )
            updated = updated._write(job_id, facts)
        return updated.record_fact(
            job_id,
            fact_id,
            f"clash:{key}",
            side,
            "customer_text",
            event_id,
            status="confirmed",
        )

    def active_fact(self, job_id: str, key: str) -> CaseFact | None:
        for fact in self.facts(job_id):
            if fact.key == key and fact.superseded_by is None and not fact.contested:
                return fact
        return None

    def current(self, job_id: str, key: str) -> str:
        matched = [fact for fact in self.facts(job_id) if fact.key == key]
        active = [fact for fact in matched if fact.superseded_by is None and not fact.contested]
        if len(active) == 1:
            return active[0].value
        if any(fact.contested for fact in matched):
            raise PolicyViolation(code="policy.violation", sentence=_CONTRADICTED)
        raise PolicyViolation(code="policy.violation", sentence=_MISSING)

    def facts(self, job_id: str) -> tuple[CaseFact, ...]:
        return self._job(job_id).facts

    def _job(self, job_id: str) -> Job:
        for job in self.jobs:
            if job.job_id == job_id:
                return job
        raise PolicyViolation(code="policy.violation", sentence=_JOB)

    def _replace(self, job_id: str, facts: tuple[CaseFact, ...], active: CaseFact, new: CaseFact) -> "CaseFile":
        replaced = tuple(
            fact.model_copy(update={"superseded_by": new.fact_id}) if fact.fact_id == active.fact_id else fact
            for fact in facts
        )
        written = self._write(job_id, replaced + (new,))
        if active.value != new.value and _customer_key(new.key):
            return written._without_mark(job_id, f"ack:{new.key}")
        return written

    def _without_mark(self, job_id: str, key: str) -> "CaseFile":
        active = self.active_fact(job_id, key)
        if active is None:
            return self
        facts = tuple(
            fact.model_copy(update={"superseded_by": active.fact_id}) if fact.fact_id == active.fact_id else fact
            for fact in self.facts(job_id)
        )
        return self._write(job_id, facts)

    def _write(
        self,
        job_id: str,
        facts: tuple[CaseFact, ...],
        contradictions: tuple[Any, ...] | None = None,
    ) -> "CaseFile":
        jobs = tuple(
            job.model_copy(update={"facts": facts}) if job.job_id == job_id else job
            for job in self.jobs
        )
        update: dict[str, Any] = {"jobs": jobs}
        if contradictions is not None:
            update["contradictions"] = contradictions
        return self.model_copy(update=update)

    def _keep_evidence(self, job_id: str, facts: tuple[CaseFact, ...], active: CaseFact, new: CaseFact) -> "CaseFile":
        """Keep a disagreeing photo reading without letting it replace the customer's value."""
        stored = new.model_copy(update={"superseded_by": active.fact_id})
        updated = self._clear_resolution(job_id, facts, active.key, stored.fact_id, new.value)
        kept = updated.facts(job_id) + (stored,)
        if quote_issued(updated, job_id):
            return updated._write(job_id, kept)
        opened = updated._clear_spec(job_id, kept)
        return opened._write(job_id, opened.facts(job_id))

    def _clear_resolution(
        self,
        job_id: str,
        facts: tuple[CaseFact, ...],
        key: str,
        evidence_id: UUID,
        evidence_value: str,
    ) -> "CaseFile":
        prior = [
            fact
            for fact in facts
            if fact.key == key and fact.source in _INFERRED_SOURCES and fact.value != evidence_value
        ]
        if not prior:
            return self
        resolution = self.active_fact(job_id, f"clash:{key}")
        if resolution is None:
            return self
        replaced = tuple(
            fact.model_copy(update={"superseded_by": evidence_id}) if fact.fact_id == resolution.fact_id else fact
            for fact in facts
        )
        return self._write(job_id, replaced)

    def _clear_spec(self, job_id: str, facts: tuple[CaseFact, ...]) -> "CaseFile":
        spec = self.active_fact(job_id, "spec_confirmed")
        if spec is None:
            return self._write(job_id, facts) if facts is not self.facts(job_id) else self
        replaced = tuple(
            fact.model_copy(update={"superseded_by": spec.fact_id}) if fact.fact_id == spec.fact_id else fact
            for fact in facts
        )
        return self._write(job_id, replaced)


def _customer_key(key: str) -> bool:
    return not key.startswith(("ack:", "rejected:", "clash:")) and key not in {"spec_confirmed", "name_acknowledged", "quote_issued"}


def derived_status(source: FactSource, state: FactState) -> FactStatus:
    """The status a fact has when the caller did not set one."""
    if state == "unknown":
        return "unknown"
    if source in _INFERRED_SOURCES:
        return "inferred"
    return "stated"


def quote_issued(case, job_id: str) -> bool:
    """True after a fixed quote for this job was sent. A later photo does not reopen it."""
    fact = case.active_fact(job_id, "quote_issued")
    if fact is None or fact.state == "unknown" or not fact.value.strip():
        return False
    return fact.value.strip().casefold() in ("true", "yes")


def status_of(fact: CaseFact) -> FactStatus:
    """The status stored on a fact."""
    if fact.contested or fact.status == "contested":
        return "contested"
    if fact.state == "unknown" or fact.status == "unknown":
        return "unknown"
    if fact.status in ("inferred", "confirmed"):
        return fact.status
    if fact.source in _INFERRED_SOURCES:
        return "inferred"
    return "stated"


def price_ready(case: CaseFile, job_id: str, required: tuple[str, ...]) -> bool:
    """A quote needs every required fact stated or confirmed. An inference is not enough."""
    for key in required:
        fact = case.active_fact(job_id, key)
        if fact is None or status_of(fact) not in _READY or not fact.value.strip():
            return False
    return True


def ready_values(facts: tuple[CaseFact, ...]) -> dict[str, str]:
    """Values the customer stated or confirmed. A photo inference stays out of the price."""
    values: dict[str, str] = {}
    for fact in facts:
        if fact.superseded_by is not None or fact.contested or fact.key in values:
            continue
        if fact.key.startswith(("alt:", "unknown:", "dismissed:")):
            continue
        if status_of(fact) not in _READY or not fact.value.strip():
            continue
        values[fact.key] = fact.value
    return values


def _require_one_current(jobs: Any) -> None:
    for job in jobs:
        facts = job.facts if isinstance(job, Job) else job.get("facts", ())
        seen: set[str] = set()
        for fact in facts:
            key = fact.key if isinstance(fact, CaseFact) else fact.get("key")
            superseded = fact.superseded_by if isinstance(fact, CaseFact) else fact.get("superseded_by")
            contested = fact.contested if isinstance(fact, CaseFact) else fact.get("contested", False)
            if superseded is None and not contested:
                if key in seen:
                    raise PolicyViolation(code="policy.violation", sentence=_ONE)
                seen.add(key)
