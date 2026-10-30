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
    ) -> "CaseFile":
        if event_id is None:
            raise ValidationError(code="fact.event_required", sentence=_EVENT)
        job = self._job(job_id)
        new = CaseFact(
            fact_id=fact_id,
            job_id=job_id,
            key=key,
            value=value,
            source=source,
            event_id=event_id,
            state=state,
        )
        active = next(
            (
                fact
                for fact in job.facts
                if fact.key == key and fact.superseded_by is None and not fact.contested
            ),
            None,
        )
        if active is None:
            return self._write(job_id, job.facts + (new,))
        from quotedesk.domain.case.contradictions import detect_contradiction

        found = detect_contradiction(active, new)
        if found is None:
            replaced = tuple(
                fact.model_copy(update={"superseded_by": fact_id}) if fact.fact_id == active.fact_id else fact
                for fact in job.facts
            )
            return self._write(job_id, replaced + (new,))
        contested = tuple(
            fact.model_copy(update={"contested": True}) if fact.fact_id == active.fact_id else fact
            for fact in job.facts
        )
        stored = new.model_copy(update={"contested": True})
        return self._write(job_id, contested + (stored,), self.contradictions + (found,))

    def start_over(self, job_id: str) -> "CaseFile":
        self._job(job_id)
        jobs = tuple(
            job.model_copy(update={"status": "closed"}) if job.job_id == job_id else job
            for job in self.jobs
        )
        return self.model_copy(update={"jobs": jobs})

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
