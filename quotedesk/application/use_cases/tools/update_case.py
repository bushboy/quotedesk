from quotedesk.application.dto.tenant import TenantContext
from quotedesk.application.dto.tool_inputs import UpdateCaseInput
from quotedesk.application.dto.tool_outputs import UpdateCaseResult
from quotedesk.application.errors import CaseNotFound, TenantRequired
from quotedesk.application.ports.repositories import CaseFileRepository, JobCatalog
from quotedesk.application.ports.runtime import IdGenerator
from quotedesk.domain.case.case_file import CaseFile
from quotedesk.domain.shared.errors import PolicyViolation, ValidationError

_TYPE = "A new job names its type."


class UpdateCase:
    def __init__(self, cases: CaseFileRepository, catalog: JobCatalog, ids: IdGenerator) -> None:
        self._cases = cases
        self._catalog = catalog
        self._ids = ids

    def execute(self, context: TenantContext | None, data: UpdateCaseInput) -> UpdateCaseResult:
        if context is None:
            raise TenantRequired()
        case = self._cases.get(context.tenant_id, data.conversation_id)
        if case is None:
            raise CaseNotFound()
        existing = _find(case, data.job_id)
        if existing is None and data.job_type is None:
            raise ValidationError(code="job.type_required", sentence=_TYPE)
        created = existing is None
        if created:
            case = case.add_job(data.job_id, data.job_type)
        for fact in data.facts:
            case = case.record_fact(
                data.job_id,
                self._ids.next_fact_id(),
                fact.key,
                fact.value,
                fact.source,
                fact.event_id,
            )
        self._cases.save(context.tenant_id, case)
        job = _find(case, data.job_id)
        assert job is not None
        current = _current(case, data.job_id)
        required = self._catalog.required(job.job_type or "")
        missing = tuple(name for name in required if name not in current)
        return UpdateCaseResult(
            job_id=data.job_id,
            created=created,
            current=current,
            missing_required=missing,
            contradiction_count=len(case.contradictions),
        )


def _find(case: CaseFile, job_id: str):
    for job in case.jobs:
        if job.job_id == job_id:
            return job
    return None


def _current(case: CaseFile, job_id: str) -> dict[str, str]:
    pairs: dict[str, str] = {}
    for fact in case.facts(job_id):
        if fact.superseded_by is not None or fact.contested or fact.key in pairs:
            continue
        try:
            pairs[fact.key] = case.current(job_id, fact.key)
        except PolicyViolation:
            continue
    return pairs
