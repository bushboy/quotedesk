from uuid import UUID

import pytest
from pydantic import ValidationError as ModelError

from quotedesk.application.dto.tenant import TenantContext
from quotedesk.application.dto.tool_inputs import FactInput, UpdateCaseInput
from quotedesk.application.errors import CaseNotFound, TenantRequired
from quotedesk.application.use_cases.tools.update_case import UpdateCase
from quotedesk.domain.case.case_file import CaseFile
from quotedesk.domain.shared.errors import ValidationError

TENANT = UUID("11111111-1111-4111-8111-111111111111")
CONVERSATION = UUID("33333333-3333-4333-8333-333333333333")
EVENT = UUID("44444444-4444-4444-8444-444444444444")
FIRST = UUID("55555555-5555-4555-8555-555555555555")
SECOND = UUID("66666666-6666-4666-8666-666666666666")
THIRD = UUID("77777777-7777-4777-8777-777777777777")


class Cases:
    def __init__(self, case: CaseFile | None) -> None:
        self.case = case
        self.saves = 0

    def get(self, tenant_id: UUID, conversation_id: UUID) -> CaseFile | None:
        if tenant_id != TENANT:
            return None
        return self.case

    def save(self, tenant_id: UUID, case: CaseFile) -> None:
        self.saves += 1
        self.case = case


class Catalog:
    def required(self, job_type: str) -> tuple[str, ...]:
        if job_type == "replacement":
            return ("size_litres", "existing_level_base")
        return ()


class Ids:
    def __init__(self, values: tuple[UUID, ...]) -> None:
        self._values = list(values)

    def next_quote_id(self):
        raise AssertionError("UpdateCase does not mint a quote id.")

    def next_fact_id(self) -> UUID:
        return self._values.pop(0)


def fact(key: str, value: str, source: str = "customer_text") -> FactInput:
    return FactInput(key=key, value=value, source=source, event_id=EVENT)


def use(case: CaseFile | None, ids: tuple[UUID, ...] = (FIRST,)):
    cases = Cases(case)
    tool = UpdateCase(cases, Catalog(), Ids(ids))
    return tool, cases


def test_update_case_records_a_fact_on_a_job():
    tool, cases = use(None, (FIRST, SECOND))
    with pytest.raises(TenantRequired):
        tool.execute(None, UpdateCaseInput(conversation_id=CONVERSATION, job_id="tank", job_type="replacement", facts=(fact("colour", "blue"),)))
    assert cases.saves == 0
    with pytest.raises(CaseNotFound):
        tool.execute(
            TenantContext(tenant_id=TENANT),
            UpdateCaseInput(conversation_id=CONVERSATION, job_id="tank", job_type="replacement", facts=(fact("colour", "blue"),)),
        )
    assert cases.saves == 0
    cases.case = CaseFile.open(CONVERSATION, TENANT)
    context = TenantContext(tenant_id=TENANT)
    created = tool.execute(
        context,
        UpdateCaseInput(
            conversation_id=CONVERSATION,
            job_id="tank",
            job_type="replacement",
            facts=(fact("colour", "blue"),),
        ),
    )
    assert created.created is True
    assert created.current == {"colour": "blue"}
    assert created.missing_required == ("size_litres", "existing_level_base")
    assert "colour" not in created.missing_required
    assert len(cases.case.jobs) == 1
    added = tool.execute(
        context,
        UpdateCaseInput(
            conversation_id=CONVERSATION,
            job_id="tank",
            facts=(fact("size_litres", "5000 L"),),
        ),
    )
    assert added.created is False
    assert len(cases.case.jobs) == 1
    assert added.current["size_litres"] == "5000 L"
    assert added.current["colour"] == "blue"
    assert added.missing_required == ("existing_level_base",)
    for key in ("unit_price", "outcome", "clause_text"):
        with pytest.raises(ModelError):
            FactInput(key=key, value="1", source="customer_text", event_id=EVENT)
        with pytest.raises(ModelError):
            UpdateCaseInput(
                conversation_id=CONVERSATION,
                job_id="tank",
                facts=(fact("colour", "blue"),),
                **{key: "1"},
            )
    before = cases.saves
    with pytest.raises(ValidationError) as caught:
        tool.execute(
            context,
            UpdateCaseInput(conversation_id=CONVERSATION, job_id="pump", facts=(fact("colour", "blue"),)),
        )
    assert caught.value.code == "job.type_required"
    assert str(caught.value) == "A new job names its type."
    assert cases.saves == before
    assert len(cases.case.jobs) == 1


def test_i_dont_know_is_recorded_as_unknown():
    class Tanks:
        def required(self, job_type: str) -> tuple[str, ...]:
            return ("size_litres",)

        def facts(self, job_type: str):
            return (type("Fact", (), {"key": "size_litres", "type": "number"})(),)

    cases = Cases(CaseFile.open(CONVERSATION, TENANT))
    tool = UpdateCase(cases, Tanks(), Ids((FIRST,)))
    tool.execute(
        TenantContext(tenant_id=TENANT),
        UpdateCaseInput(
            conversation_id=CONVERSATION,
            job_id="tank",
            job_type="replacement",
            facts=(fact("size_litres", "I don't know"),),
        ),
    )
    stored = cases.case.facts("tank")
    assert stored[0].state == "unknown"
    assert stored[0].value == ""
    assert stored[0].event_id == EVENT


def test_a_customer_name_is_dropped_and_a_job_type_fact_opens_the_job():
    class Carport:
        def required(self, job_type: str) -> tuple[str, ...]:
            return ("width_m",) if job_type == "carport" else ()

        def facts(self, job_type: str):
            if job_type != "carport":
                return ()
            return (type("Fact", (), {"key": "width_m", "type": "number"})(),)

    cases = Cases(CaseFile.open(CONVERSATION, TENANT))
    tool = UpdateCase(cases, Carport(), Ids((FIRST, SECOND)))
    result = tool.execute(
        TenantContext(tenant_id=TENANT),
        UpdateCaseInput(
            conversation_id=CONVERSATION,
            job_id="carport",
            facts=(
                fact("customer_name", "Polycarbonate"),
                fact("item_codes", "SHEET-POLY"),
                fact("job_type", "carport"),
            ),
        ),
    )
    assert result.created is True
    assert cases.case.jobs[0].job_type == "carport"
    assert result.current["item_codes"] == "SHEET-POLY"
    assert "customer_name" not in result.current


def test_update_case_supersedes():
    tool, cases = use(CaseFile.open(CONVERSATION, TENANT), (FIRST, SECOND))
    context = TenantContext(tenant_id=TENANT)
    tool.execute(
        context,
        UpdateCaseInput(
            conversation_id=CONVERSATION,
            job_id="tank",
            job_type="replacement",
            facts=(fact("size_litres", "2500 L"),),
        ),
    )
    current = tool.execute(
        context,
        UpdateCaseInput(conversation_id=CONVERSATION, job_id="tank", facts=(fact("size_litres", "5000 L"),)),
    )
    facts = cases.case.facts("tank")
    assert current.current["size_litres"] == "5000 L"
    assert current.contradiction_count == 0
    assert facts[0].value == "2500 L"
    assert facts[0].superseded_by == SECOND
    assert facts[1].fact_id == SECOND
    assert facts[1].value == "5000 L"


def test_update_case_flags_contradiction():
    tool, cases = use(CaseFile.open(CONVERSATION, TENANT), (FIRST, SECOND))
    context = TenantContext(tenant_id=TENANT)
    tool.execute(
        context,
        UpdateCaseInput(
            conversation_id=CONVERSATION,
            job_id="tank",
            job_type="replacement",
            facts=(fact("position", "roof"),),
        ),
    )
    current = tool.execute(
        context,
        UpdateCaseInput(
            conversation_id=CONVERSATION,
            job_id="tank",
            facts=(fact("position", "ground level", "photo_extraction"),),
        ),
    )
    facts = cases.case.facts("tank")
    assert current.contradiction_count == 1
    assert "position" not in current.current
    assert facts[0].contested is True
    assert facts[1].contested is True
    assert facts[0].superseded_by is None
    assert facts[1].superseded_by is None
