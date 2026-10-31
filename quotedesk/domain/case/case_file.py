from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

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
    model_config = ConfigDict(frozen=True, extra="forbid")

    job_id: str
    job_type: str | None
    status: JobStatus
    facts: tuple[CaseFact, ...] = ()


class CaseFile(BaseModel):
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
            return self
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
        return self._write(job_id, replaced + (new,))

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


def derived_status(source: FactSource, state: FactState) -> FactStatus:
    if state == "unknown":
        return "unknown"
    if source in _INFERRED_SOURCES:
        return "inferred"
    return "stated"


def status_of(fact: CaseFact) -> FactStatus:
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
