from decimal import Decimal
from uuid import UUID

from quotedesk.domain.case.case_file import CaseFact, CaseFile, Job
from quotedesk.domain.case.contradictions import detect_contradiction
from quotedesk.domain.shared.errors import PolicyViolation, ValidationError
from tests.unit.domain.assertions import expect_domain

CONVERSATION = UUID("33333333-3333-4333-8333-333333333333")
TENANT = UUID("11111111-1111-4111-8111-111111111111")
EVENT = UUID("44444444-4444-4444-8444-444444444444")
FIRST = UUID("55555555-5555-4555-8555-555555555555")
SECOND = UUID("66666666-6666-4666-8666-666666666666")


def opened() -> CaseFile:
    return CaseFile.open(CONVERSATION, TENANT)


def fact(fact_id: UUID, job_id: str, key: str, value: str, source: str) -> CaseFact:
    return CaseFact(
        fact_id=fact_id,
        job_id=job_id,
        key=key,
        value=value,
        source=source,
        event_id=EVENT,
    )


def test_fact_requires_a_source_event():
    case = opened().add_job("tank", "replacement")
    expect_domain(
        lambda: case.record_fact("tank", FIRST, "size_litres", "5000", "customer_text", None),
        ValidationError,
        "fact.event_required",
        "A fact names the event it came from.",
    )
    stored = case
    for source in (
        "customer_text",
        "voice_transcript",
        "photo_extraction",
        "video_extraction",
        "owner",
    ):
        stored = opened().add_job("tank", None).record_fact("tank", FIRST, "note", "yes", source, EVENT)
        assert stored.facts("tank")[0].source == source


def test_correction_supersedes():
    case = opened().add_job("tank", "replacement")
    case = case.record_fact("tank", FIRST, "size_litres", "2500 L", "customer_text", EVENT)
    assert case.current("tank", "size_litres") == "2500 L"
    case = case.record_fact("tank", SECOND, "size_litres", "5000 L", "customer_text", EVENT)
    assert case.current("tank", "size_litres") == "5000 L"
    older = case.facts("tank")[0]
    assert older.value == "2500 L"
    assert older.superseded_by == SECOND


def test_two_active_facts_for_one_key_rejected():
    job = Job(
        job_id="tank",
        job_type="replacement",
        status="gathering",
        facts=(
            fact(FIRST, "tank", "size_litres", "2500 L", "customer_text"),
            fact(SECOND, "tank", "size_litres", "5000 L", "customer_text"),
        ),
    )
    expect_domain(
        lambda: CaseFile(conversation_id=CONVERSATION, tenant_id=TENANT, jobs=(job,)),
        PolicyViolation,
        "policy.violation",
        "A fact key has one current value.",
    )


def test_a_stated_value_replaces_an_inference():
    case = opened().add_job("tank", "replacement")
    case = case.record_fact("tank", FIRST, "size_litres", "2500", "photo_extraction", EVENT, confidence=Decimal("0.9"))
    assert case.active_fact("tank", "size_litres").status == "inferred"
    case = case.record_fact("tank", SECOND, "size_litres", "5000", "customer_text", EVENT)
    assert case.contradictions == ()
    current = case.active_fact("tank", "size_litres")
    assert current is not None
    assert current.value == "5000"
    assert current.status == "stated"


def test_an_inference_does_not_replace_a_stated_value():
    case = opened().add_job("tank", "replacement")
    case = case.record_fact("tank", FIRST, "position", "roof", "customer_text", EVENT)
    case = case.record_fact("tank", SECOND, "position", "ground level", "photo_extraction", EVENT)
    assert case.contradictions == ()
    assert case.current("tank", "position") == "roof"
    assert len(case.facts("tank")) == 1


def test_two_stated_sources_that_disagree_are_contested():
    case = opened().add_job("tank", "replacement")
    case = case.record_fact("tank", FIRST, "position", "roof", "customer_text", EVENT)
    case = case.record_fact("tank", SECOND, "position", "ground level", "voice_transcript", EVENT)
    assert len(case.contradictions) == 1
    values = {item.value for item in case.facts("tank")}
    assert values == {"roof", "ground level"}


def test_confirming_an_inference_makes_it_price_ready():
    from quotedesk.domain.case.case_file import price_ready

    case = opened().add_job("tank", "replacement")
    case = case.record_fact("tank", FIRST, "size_litres", "5000", "photo_extraction", EVENT, confidence=Decimal("0.82"))
    assert price_ready(case, "tank", ("size_litres",)) is False
    case = case.confirm("tank", "size_litres", SECOND, EVENT)
    assert case.active_fact("tank", "size_litres").status == "confirmed"
    assert price_ready(case, "tank", ("size_litres",)) is True


def test_detect_contradiction_when_values_agree():
    existing = fact(FIRST, "tank", "size_litres", "5000 L", "customer_text")
    incoming = fact(SECOND, "tank", "size_litres", "5000 L", "photo_extraction")
    assert detect_contradiction(existing, incoming) is None
    case = opened().add_job("tank", "replacement")
    case = case.record_fact("tank", FIRST, "size_litres", "5000 L", "customer_text", EVENT)
    case = case.record_fact("tank", SECOND, "size_litres", "5000 L", "photo_extraction", EVENT)
    assert case.contradictions == ()
    assert case.current("tank", "size_litres") == "5000 L"


def test_several_jobs_in_one_case():
    case = opened().add_job("tank", "replacement").add_job("pump", "replacement")
    case = case.record_fact("tank", FIRST, "fault", "leaking", "customer_text", EVENT)
    case = case.record_fact("pump", SECOND, "fault", "dead", "customer_text", EVENT)
    assert case.current("tank", "fault") == "leaking"
    assert case.current("pump", "fault") == "dead"


def test_start_over_closes_the_job_and_keeps_the_facts():
    case = opened().add_job("tank", "replacement")
    case = case.record_fact("tank", FIRST, "size_litres", "5000 L", "customer_text", EVENT)
    closed = case.start_over("tank")
    assert closed.jobs[0].status == "closed"
    assert closed.facts("tank")[0].value == "5000 L"
    assert len(closed.jobs) == 1
