from quotedesk.application.dto.tenant import TenantContext
from quotedesk.application.dto.tool_inputs import UpdateCaseInput
from quotedesk.application.dto.tool_outputs import UpdateCaseResult
from quotedesk.application.errors import CaseNotFound, TenantRequired
from quotedesk.application.ports.repositories import CaseFileRepository, JobCatalog
from quotedesk.application.ports.runtime import IdGenerator
from quotedesk.domain.case.case_file import CaseFile
from quotedesk.domain.services.finish import sheet_choice
from quotedesk.domain.shared.errors import PolicyViolation, ValidationError

_TYPE = "A new job names its type."
_ALIAS = "That fact uses a name this business does not."
_UNKNOWN = "That fact is not one this job asks for."
_ALIASES = frozenset({"tank_size", "size", "dimensions", "item", "job"})
_CONFIDENCE = frozenset({"required_fields", "agreement", "measurement", "media_usable", "rate_card"})
_BOOKKEEPING = frozenset({"size_source", "item_codes"})
_DECISION = frozenset(
    {
        "customer_text",
        "installation_damaged",
        "simple_swap",
        "base_unconfirmed",
        "new_tank_and_pump",
        "sloped_ground",
        "pipe_run_unknown",
        "opening",
        "above_ground_floor",
        "multi_unit",
        "standard_band",
        "finish",
        "budget",
        "job_type",
        "stand_condition",
        "elevated",
        "structure_damage",
        "exposed_wiring",
        "active_flooding",
        "lintel_cracked",
        "glass_broken",
        "possible_asbestos",
    }
)
_YES = frozenset({"true", "yes", "y"})
_NO = frozenset({"false", "no", "n"})
_NAME = frozenset({"customer_name", "name"})
_UNSURE = frozenset(
    {
        "unknown",
        "i don't know",
        "i dont know",
        "don't know",
        "dont know",
        "not sure",
        "no idea",
    }
)


class UpdateCase:
    def __init__(self, cases: CaseFileRepository, catalog: JobCatalog, ids: IdGenerator) -> None:
        self._cases = cases
        self._catalog = catalog
        self._ids = ids

    def execute(self, context: TenantContext | None, data: UpdateCaseInput) -> UpdateCaseResult:
        if context is None:
            raise TenantRequired()
        data = _without_name(data)
        case = self._cases.get(context.tenant_id, data.conversation_id)
        if case is None:
            raise CaseNotFound()
        existing = _find(case, data.job_id)
        if existing is None and data.job_type is None:
            raise ValidationError(code="job.type_required", sentence=_TYPE)
        created = existing is None
        if created:
            case = case.add_job(data.job_id, data.job_type)
        job = _find(case, data.job_id)
        assert job is not None
        recorded = {fact.key for fact in data.facts}
        for fact in data.facts:
            if fact.key in _CONFIDENCE and not data.system:
                continue
            if _unsure(fact.value):
                case = case.record_fact(
                    data.job_id,
                    self._ids.next_fact_id(),
                    fact.key,
                    "",
                    fact.source,
                    fact.event_id,
                    state="unknown",
                )
                continue
            value = _normalise(fact.key, fact.value, job.job_type or "", self._catalog, data.system, fact.source)
            case = case.record_fact(
                data.job_id,
                self._ids.next_fact_id(),
                fact.key,
                value,
                fact.source,
                fact.event_id,
            )
            for key, linked in _priced(fact.key, value, _defined(self._catalog, job.job_type or "")):
                if key in recorded:
                    continue
                recorded.add(key)
                case = case.record_fact(
                    data.job_id,
                    self._ids.next_fact_id(),
                    key,
                    linked,
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


def _unsure(value: str) -> bool:
    return " ".join(value.strip().casefold().split()) in _UNSURE


def _without_name(data: UpdateCaseInput) -> UpdateCaseInput:
    """A person's name is not a case fact. A job type stated as a fact still opens the job."""
    facts = tuple(fact for fact in data.facts if fact.key not in _NAME)
    job_type = data.job_type.strip() if data.job_type else ""
    if not job_type:
        stated = next((fact.value.strip() for fact in facts if fact.key == "job_type" and fact.value.strip()), "")
        job_type = stated
    if facts == data.facts and job_type == (data.job_type or ""):
        return data
    return data.model_copy(update={"facts": facts, "job_type": job_type or None})


def _normalise(key: str, value: str, job_type: str, catalog, system: bool, source: str) -> str:
    if key in _ALIASES:
        raise ValidationError(code="fact.alias", sentence=_ALIAS)
    defined = _defined(catalog, job_type)
    media = source in ("photo_extraction", "video_extraction", "voice_transcript")
    allowed = key in defined or key in _BOOKKEEPING or key in _DECISION or (system and key in _CONFIDENCE) or media
    if defined and not allowed:
        raise ValidationError(code="fact.unknown", sentence=_UNKNOWN)
    fact = defined.get(key) if defined else None
    if fact is None or fact.type == "text" or fact.type == "choice":
        return value.strip()
    if fact.type == "yes_no":
        folded = value.strip().casefold()
        if folded in _YES:
            return "true"
        if folded in _NO:
            return "false"
        raise ValidationError(code="fact.yes_no", sentence=_UNKNOWN)
    digits = "".join(character for character in value if character.isdigit() or character == ".")
    if digits == "" or digits == ".":
        raise ValidationError(code="fact.number", sentence=_UNKNOWN)
    return digits


def _priced(key: str, value: str, defined: dict) -> tuple[tuple[str, str], ...]:
    """A named finish is the rate-card item on that choice."""
    sheet = defined.get("sheet")
    if sheet is None or key not in ("sheet", "finish", "item_codes"):
        return ()
    found = sheet_choice(value, sheet.options)
    if found is None:
        return ()
    pairs = []
    if key != "item_codes":
        pairs.append(("item_codes", found.code))
    if key != "finish":
        pairs.append(("finish", found.label))
    if key != "sheet":
        pairs.append(("sheet", found.value))
    return tuple(pairs)


def _defined(catalog, job_type: str) -> dict:
    reader = getattr(catalog, "facts", None)
    if reader is None:
        return {}
    return {fact.key: fact for fact in reader(job_type)}


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
