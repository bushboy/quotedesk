"""Increment 4: an inspection is recorded, the brief is enough to call from, and the owner is told once."""

from datetime import date, datetime, timezone
from uuid import uuid4

from quotedesk.application.dto.agent import HandoverNote
from quotedesk.application.dto.inbound import InboundMessage
from quotedesk.application.dto.tenant import TenantContext
from quotedesk.application.dto.tool_inputs import BookInspectionInput, EscalateToOwnerInput
from quotedesk.application.use_cases.tools.book_inspection import BookInspection
from quotedesk.application.use_cases.tools.escalate_to_owner import EscalateToOwner
from quotedesk.application.use_cases.tools.notify_owner import NotifyOwner
from quotedesk.domain.case.case_file import CaseFile
from quotedesk.domain.policy.rules import Outcome
from quotedesk.domain.quotes.quote import Quote, QuoteState
from quotedesk.domain.quotes.schedule import Capacity, CapacitySlot
from quotedesk.domain.shared.ids import QuoteId
from quotedesk.adapters.outbound.persistence.commercial import MemoryInspections, MemoryMail, MemoryNotices
from quotedesk.infrastructure.demo import _schedule_settings
from tests.unit.domain.test_plan_next_step import AQUA, EVENT
from tests.unit.domain.water_policy import aquasure_policy
from tests.use_cases.test_run_agent_turn import CONVERSATION, Cases, Clock, Conversations, HANDOVER, Sender, TENANT, at, turn
from tests.use_cases.test_turn_guard import CONTEXT, Counting, _open

WHEN = datetime(2026, 10, 30, 8, 0, tzinfo=timezone.utc)


class Published:
    def __init__(self, playbook) -> None:
        self.playbook = playbook
        self.policy = aquasure_policy()

    def published(self, tenant_id):
        return self


class Quotes:
    def __init__(self, quote: Quote) -> None:
        self.quote = quote

    def get_quote(self, tenant_id, conversation_id):
        return self.quote

    def save_quote(self, tenant_id, conversation_id, quote):
        self.quote = quote


class Notes:
    def __init__(self) -> None:
        self.rows: list[HandoverNote] = []

    def append(self, tenant_id, note: HandoverNote) -> None:
        self.rows.append(note)


class Talk:
    def __init__(self, body: str) -> None:
        self.body = body

    def messages(self, tenant_id, conversation_id):
        return (
            InboundMessage(
                conversation_id=conversation_id,
                provider_message_id="wamid.A",
                wa_id="15550002222",
                at=WHEN,
                kind="text",
                body=self.body,
            ),
            InboundMessage(
                conversation_id=conversation_id,
                provider_message_id="wamid.B",
                wa_id="15550002222",
                at=WHEN,
                kind="image",
                body=None,
                image_text="tank on a cracked base",
            ),
        )

    def name(self, tenant_id, wa_id):
        return "Thabo"

    def replies(self, tenant_id, conversation_id):
        return ()


def _capacity():
    store = type("Capacity", (), {})()
    held = Capacity(slots=(CapacitySlot(day=date(2026, 11, 6), places=2),))

    def get(tenant_id):
        return held

    store.get = get
    return store


def _damaged() -> CaseFile:
    case = CaseFile.open(CONVERSATION, TENANT).add_job("tank", "replacement")
    case = case.record_fact("tank", uuid4(), "installation_damaged", "true", "customer_text", EVENT)
    return case.record_fact("tank", uuid4(), "simple_swap", "false", "customer_text", EVENT)


class Heard:
    def __init__(self, replies) -> None:
        self._replies = replies

    def replies(self, tenant_id, conversation_id):
        return self._replies

    def get(self, tenant_id, conversation_id):
        return None


def test_two_unanswered_asks_are_told_plainly_when_the_inspection_is_recorded():
    question = "Which tank size do you want?"
    case = CaseFile.open(CONVERSATION, TENANT).add_job("tank", "replacement")
    case = case.record_fact("tank", uuid4(), "existing_level_base", "true", "customer_text", EVENT)
    inspections = MemoryInspections()
    tool = BookInspection(
        Cases(case),
        Published(AQUA),
        _capacity(),
        _schedule_settings(),
        Clock(WHEN),
        inspections,
        conversations=Heard(((WHEN, question), (WHEN, question))),
    )
    offered = tool.execute(CONTEXT, BookInspectionInput(conversation_id=CONVERSATION, job_id="tank"))
    assert "I've asked twice, so I won't ask again." in offered.sentence
    stored = inspections.for_conversation(TENANT, CONVERSATION)[0]
    assert stored.rule_id == ""
    assert stored.status.value == "offered"


def test_an_out_of_scope_request_uses_the_playbook_reply_and_notes_the_owner():
    playbook = AQUA.model_copy(
        update={"does_not": "We don't take plumbing call-outs.", "owner_whatsapp": "15550009999"}
    )
    notes = Notes()
    tool = EscalateToOwner(
        Cases(CaseFile.open(CONVERSATION, TENANT)),
        Talk("I need plumbing for a leak."),
        Published(playbook),
        notes,
        None,
        NotifyOwner(MemoryNotices(), Sender()),
        Clock(WHEN),
    )
    result = tool.execute(CONTEXT, EscalateToOwnerInput(conversation_id=CONVERSATION, summary="A plumbing call-out."))
    assert result.sentence == "We don't take plumbing call-outs."
    assert "Reason: This is outside what the business does." in result.brief
    assert notes.rows[0].reason == "This is outside what the business does."


def test_a_damaged_installation_records_an_inspection():
    inspections = MemoryInspections()
    quotes = Quotes(Quote.open(QuoteId("QD-1042"), date(2026, 11, 30)).issue(Outcome.SITE_ASSESSMENT, version=1, at=WHEN))
    cases = Cases(_damaged())
    tool = BookInspection(
        cases,
        Published(AQUA),
        _capacity(),
        _schedule_settings(),
        Clock(WHEN),
        inspections,
        quotes,
    )
    offered = tool.execute(CONTEXT, BookInspectionInput(conversation_id=CONVERSATION, job_id="tank"))
    stored = inspections.for_conversation(TENANT, CONVERSATION)[0]
    assert stored.rule_id == "WATER-E02"
    assert stored.status.value == "offered"
    assert stored.fee == "site visit"
    assert stored.window_start == date(2026, 11, 6)
    assert offered.sentence.startswith(
        "We'll book an inspection. The installation is damaged, and it is not clear this is a simple tank replacement."
    )
    assert "The visit fee is site visit." in offered.sentence
    assert "The earliest window is 2026-11-06." in offered.sentence
    booked = tool.execute(CONTEXT, BookInspectionInput(conversation_id=CONVERSATION, job_id="tank", confirm=True))
    assert booked.status == "booked"
    assert quotes.quote.current.state is QuoteState.INSPECTION_BOOKED


def test_the_owner_can_call_from_the_brief_and_is_told_once():
    playbook = AQUA.model_copy(update={"owner_whatsapp": "15550009999"})
    case = CaseFile.open(CONVERSATION, TENANT).add_job("tank", "replacement")
    case = case.record_fact("tank", uuid4(), "size_litres", "5000", "customer_text", EVENT)
    notes = Notes()
    sender = Sender()
    quotes = Quotes(Quote.open(QuoteId("QD-1042"), date(2026, 11, 30)).issue(Outcome.SITE_ASSESSMENT, version=1, at=WHEN))
    tool = EscalateToOwner(
        Cases(case),
        Talk("The tank is leaking."),
        Published(playbook),
        notes,
        MemoryInspections(),
        NotifyOwner(MemoryNotices(), sender, MemoryMail()),
        Clock(WHEN),
        quotes=quotes,
    )
    first = tool.execute(CONTEXT, EscalateToOwnerInput(conversation_id=CONVERSATION, summary="A leaking tank replacement."))
    second = tool.execute(CONTEXT, EscalateToOwnerInput(conversation_id=CONVERSATION, summary="again"))
    brief = first.brief
    assert "Customer: Thabo 15550002222" in brief
    assert "Wants: A leaking tank replacement." in brief
    assert "size_litres = 5000 (said)" in brief
    assert "Photos and voice notes: photo: tank on a cracked base" in brief
    assert "Missing: existing_level_base" in brief
    assert "Unknown: none" in brief
    assert "Quote: QD-1042 SITE_ASSESSMENT_OFFERED" in brief
    assert "Next:" in brief
    assert "Last: The tank is leaking." in brief
    assert first.notified == "whatsapp"
    assert second.notified == ""
    assert len(sender.sent) == 1
    assert sender.sent[0][0] == "15550009999"
    assert f"/console/brief/{CONVERSATION}" in sender.sent[0][1]
    assert notes.rows[0].brief == brief


def test_a_tool_failure_escalates_with_the_brief():
    store = Conversations()
    _open(store, "The base is cracked")
    customer = Sender()
    model = Counting((RuntimeError("the tool broke"),))
    use_case, _, _, _, handover = turn(model, store, customer, Clock(at(5)))
    notes = Notes()
    owner = Sender()
    use_case._escalate = EscalateToOwner(
        use_case._cases,
        store,
        Published(AQUA.model_copy(update={"owner_whatsapp": "15550009999"})),
        notes,
        None,
        NotifyOwner(MemoryNotices(), owner),
        Clock(at(5)),
    )
    outcome = use_case.execute(CONTEXT, CONVERSATION)
    assert outcome.value == "escalated"
    assert any(HANDOVER in body for _, body in customer.sent)
    assert "Customer:" in notes.rows[0].brief
    assert "the tool broke" in notes.rows[0].brief
    assert len(owner.sent) == 1
    assert handover.records == []


def test_email_is_the_fallback_when_there_is_no_owner_number():
    playbook = AQUA.model_copy(update={"owner_email": "owner@example.com"})
    mail = MemoryMail()
    tool = EscalateToOwner(
        Cases(CaseFile.open(CONVERSATION, TENANT).add_job("tank", "replacement")),
        Talk("hello"),
        Published(playbook),
        Notes(),
        None,
        NotifyOwner(MemoryNotices(), Sender(), mail),
        Clock(WHEN),
    )
    result = tool.execute(CONTEXT, EscalateToOwnerInput(conversation_id=CONVERSATION, summary="A tank."))
    assert result.notified == "email"
    assert mail.sent[0][0] == "owner@example.com"
