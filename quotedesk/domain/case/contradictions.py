from uuid import UUID

from pydantic import BaseModel, ConfigDict

from quotedesk.domain.case.case_file import CaseFact


class Contradiction(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    job_id: str
    key: str
    fact_id: UUID
    other_fact_id: UUID


def detect_contradiction(existing: CaseFact, new: CaseFact) -> Contradiction | None:
    if existing.key != new.key:
        return None
    if existing.source != new.source and existing.value != new.value:
        return Contradiction(
            job_id=existing.job_id,
            key=existing.key,
            fact_id=existing.fact_id,
            other_fact_id=new.fact_id,
        )
    return None
