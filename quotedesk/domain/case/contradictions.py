from uuid import UUID

from pydantic import BaseModel, ConfigDict

from quotedesk.domain.case.case_file import CaseFact, status_of


class Contradiction(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    job_id: str
    key: str
    fact_id: UUID
    other_fact_id: UUID


def detect_contradiction(existing: CaseFact, new: CaseFact) -> Contradiction | None:
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
