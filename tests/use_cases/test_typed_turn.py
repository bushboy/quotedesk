from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from quotedesk.application.dto.agent import ModelReply, PromptRateItem, ToolCall, TurnPrompt
from quotedesk.application.dto.inbound import InboundMessage
from quotedesk.application.dto.tenant import TenantContext
from quotedesk.application.dto.tool_outputs import AvailabilityResult, RequestChangeResult
from quotedesk.application.use_cases.conversation.run_agent_turn import HandoverToHuman, RunAgentTurn
from quotedesk.application.use_cases.tools.get_quote import GetQuote
from quotedesk.application.use_cases.tools.update_case import UpdateCase
from quotedesk.domain.case.case_file import CaseFile
from quotedesk.domain.conversation.events import Conversation
from quotedesk.domain.quotes.quote import QuoteLine, QuoteState
from quotedesk.domain.shared.ids import QuoteId
from quotedesk.domain.shared.money import Money
from quotedesk.infrastructure.demo import published_bundle

TENANT = UUID("11111111-1111-4111-8111-111111111111")
CONVERSATION = UUID("33333333-3333-4333-8333-333333333333")
EVENT = UUID("44444444-4444-4444-8444-444444444444")
OLDEST = UUID("55555555-5555-4555-8555-555555555555")
BASE = datetime(2026, 10, 24, 0, 0, tzinfo=timezone.utc)
WA = "15550002222"
QUOTE = "The total is R 4 250. Your card: /card/QD-1042?code=1042"
REFUSAL = "I can only repeat what the quote says."
THIN = "We don't have a standard price for this job. A site visit is the next step."
TANK = "The tank is leaking. Replace it with a 5000 litre tank on the existing level base."
LEAK = "The tank is leaking."
WINDOW = "The earliest window is 7 November 2026."
WAITING = "The request is waiting. The total is R 4 250."
CONTEXT = TenantContext(tenant_id=TENANT)


def at(seconds: float) -> datetime:
    return BASE + timedelta(seconds=seconds)


class Conversations:
    def __init__(self) -> None:
        self.rows: dict[tuple[UUID, UUID], Conversation] = {}
        self._messages: list[tuple[UUID, InboundMessage]] = []

    def get(self, tenant_id: UUID, conversation_id: UUID) -> Conversation | None:
        return self.rows.get((tenant_id, conversation_id))

    def save(self, tenant_id: UUID, conversation: Conversation) -> None:
        self.rows[(tenant_id, conversation.conversation_id)] = conversation

    def note(self, tenant_id: UUID, wa_id: str, at: datetime) -> None:
        return None

    def noted(self, tenant_id: UUID, wa_id: str) -> tuple[datetime, ...]:
        return ()

    def remember(self, tenant_id: UUID, message: InboundMessage) -> None:
        self._messages.append((tenant_id, message))

    def messages(self, tenant_id: UUID, conversation_id: UUID) -> tuple[InboundMessage, ...]:
        return tuple(
            message
            for tenant, message in self._messages
            if tenant == tenant_id and message.conversation_id == conversation_id
        )


class Cases:
    def __init__(self, case: CaseFile) -> None:
        self.case = case

    def get(self, tenant_id: UUID, conversation_id: UUID) -> CaseFile | None:
        if tenant_id != TENANT or self.case.conversation_id != conversation_id:
            return None
        return self.case

    def save(self, tenant_id: UUID, case: CaseFile) -> None:
        self.case = case


class Unit:
    def __init__(self) -> None:
        self.committed: dict[tuple[UUID, UUID], object] = {}
        self.audits: list = []
        self._pending_key = None
        self._pending_quote = None
        self._pending_audit = None

    def get_quote(self, tenant_id: UUID, conversation_id: UUID):
        return self.committed.get((tenant_id, conversation_id))

    def save_quote(self, tenant_id: UUID, conversation_id: UUID, quote) -> None:
        self._pending_key = (tenant_id, conversation_id)
        self._pending_quote = quote

    def record_audit(self, event) -> None:
        self._pending_audit = event

    def commit(self) -> None:
        if self._pending_key is not None and self._pending_quote is not None:
            self.committed[self._pending_key] = self._pending_quote
        if self._pending_audit is not None:
            self.audits.append(self._pending_audit)
        self.rollback()

    def rollback(self) -> None:
        self._pending_key = None
        self._pending_quote = None
        self._pending_audit = None


class Policies:
    def __init__(self) -> None:
        self.bundle = published_bundle()

    def published(self, tenant_id: UUID):
        return self.bundle


class Ids:
    def next_quote_id(self) -> QuoteId:
        return QuoteId("QD-1042")

    def next_fact_id(self) -> UUID:
        return uuid4()

    def next_idempotency_key(self) -> str:
        return "turn-key-1"


class Catalog:
    def required(self, job_type: str) -> tuple[str, ...]:
        if job_type == "replacement":
            return ("size_litres", "existing_level_base")
        return ()


class Sender:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send(self, wa_id: str, body: str) -> None:
        self.sent.append((wa_id, body))


class Lock:
    def __init__(self) -> None:
        self.held = False

    def acquire(self, conversation_id: UUID) -> bool:
        if self.held:
            return False
        self.held = True
        return True

    def release(self, conversation_id: UUID) -> None:
        self.held = False


class Clock:
    def __init__(self, instant: datetime) -> None:
        self.instant = instant

    def now(self) -> datetime:
        return self.instant


class ChangeFake:
    def __init__(self) -> None:
        self.calls = 0

    def execute(self, context, data) -> RequestChangeResult:
        self.calls += 1
        line = QuoteLine(
            item_code="TANK-5000",
            description="5000 L tank",
            quantity=Decimal("1"),
            unit_price=Money("4250.00"),
            total=Money("4250.00"),
        )
        return RequestChangeResult(
            quote_id=data.quote_id,
            version=1,
            state=QuoteState.PENDING_APPROVAL,
            discount_percent=Decimal("0"),
            lines=(line,),
            clauses=(),
        )


class AvailabilityFake:
    def execute(self, context, data) -> AvailabilityResult:
        return AvailabilityResult(
            status="indicative",
            earliest_window=datetime(2026, 11, 7).date(),
            sentence=WINDOW,
        )


class PriceFake:
    def __init__(self) -> None:
        self.calls = 0

    def execute(self, context, data) -> None:
        self.calls += 1


def harness(model, case: CaseFile | None = None):
    conversations = Conversations()
    cases = Cases(case or CaseFile.open(CONVERSATION, TENANT))
    policies = Policies()
    ids = Ids()
    catalog = Catalog()
    clock = Clock(at(5))
    update = UpdateCase(cases, catalog, ids)
    quoted = GetQuote(cases, policies, Unit(), clock, ids)
    sender = Sender()
    turn = RunAgentTurn(
        conversations,
        sender,
        model,
        Lock(),
        update,
        quoted,
        HandoverToHuman(cases),
        clock,
        request_change=ChangeFake(),
        check_availability=AvailabilityFake(),
        catalog=catalog,
        policies=policies,
        ids=ids,
        card_base="/card",
        card_code="1042",
    )
    return conversations, cases, sender, clock, turn


def say(conversations: Conversations, body: str, seconds: float, message_id: str) -> None:
    current = conversations.get(TENANT, CONVERSATION) or Conversation.open(CONVERSATION)
    conversations.save(TENANT, current.append(message_id, at(seconds), body).conversation)
    conversations.remember(
        TENANT,
        InboundMessage(
            conversation_id=CONVERSATION,
            provider_message_id=message_id,
            wa_id=WA,
            at=at(seconds),
            kind="text",
            body=body,
        ),
    )


def replacement_calls(prompt) -> tuple[ToolCall, ...]:
    event_id = prompt.messages[-1].provider_message_id
    fact = {"source": "customer_text", "event_id": event_id}
    return (
        ToolCall(
            name="update_case",
            arguments={
                "conversation_id": str(CONVERSATION),
                "job_id": "tank",
                "job_type": "replacement",
                "facts": [
                    {"key": "job", "value": "replacement", **fact},
                    {"key": "size_litres", "value": "5000", **fact},
                    {"key": "size_source", "value": "customer_stated", **fact},
                    {"key": "existing_level_base", "value": "true", **fact},
                    {"key": "item_codes", "value": "TANK-5000", **fact},
                    {"key": "agreement", "value": "true", **fact},
                ],
            },
        ),
        ToolCall(name="get_quote", arguments={"conversation_id": str(CONVERSATION)}),
    )


class QuoteScript:
    def __init__(self, speak: str) -> None:
        self.prompts: list[TurnPrompt] = []
        self.speak = speak

    def complete(self, prompt: TurnPrompt) -> ModelReply:
        self.prompts.append(prompt)
        if not prompt.tool_payloads:
            return ModelReply(text="", tool_calls=replacement_calls(prompt))
        return ModelReply(text=self.speak, tool_calls=())


def test_prompt_contains_the_typed_message_and_hides_the_21st():
    built = TurnPrompt(event_ids=("wamid.A",))
    assert built.messages == ()
    assert built.tool_results == ()
    assert built.tool_payloads == ()
    case = (
        CaseFile.open(CONVERSATION, TENANT)
        .add_job("tank", "replacement")
        .record_fact("tank", uuid4(), "note", "from-oldest", "customer_text", OLDEST)
    )
    model = QuoteScript("Thanks.")
    conversations, _, _, _, turn = harness(model, case)
    for index in range(21):
        say(conversations, "oldest" if index == 0 else f"later-{index}", index * 0.2, str(OLDEST) if index == 0 else f"m{index:02d}")
    turn.execute(CONTEXT, CONVERSATION)
    prompt = model.prompts[0]
    assert len(prompt.event_ids) == 21
    assert prompt.event_ids[0] == str(OLDEST)
    assert len(prompt.messages) == 20
    assert "oldest" not in [message.body for message in prompt.messages]
    assert [message.provider_message_id for message in prompt.messages] == [f"m{index:02d}" for index in range(1, 21)]
    assert any(fact.event_id == OLDEST and fact.value == "from-oldest" for fact in prompt.case.facts)


def test_typed_replacement_issues_water_f01():
    model = QuoteScript(QUOTE)
    conversations, cases, sender, _, turn = harness(model)
    say(conversations, TANK, 0, str(EVENT))
    turn.execute(CONTEXT, CONVERSATION)
    first, second = model.prompts
    assert first.messages[-1].body == TANK
    assert first.tool_payloads == ()
    assert first.rate_card == (
        PromptRateItem(item_code="TANK-2500", description="2500 L tank"),
        PromptRateItem(item_code="TANK-5000", description="5000 L tank"),
        PromptRateItem(item_code="TANK-10000", description="10000 L tank"),
    )
    assert all("2850" not in item.description and "4250" not in item.description and "7900" not in item.description for item in first.rate_card)
    update = next(item for item in second.tool_payloads if item.name == "update_case")
    assert "agreement" not in update.body["current"]
    assert update.body["current"]["size_litres"] == "5000"
    quote = next(item for item in second.tool_payloads if item.name == "get_quote")
    assert quote.body["rule_id"]["value"] == "WATER-F01"
    assert quote.body["outcome"] == "fixed_offer"
    assert quote.body["total"]["amount"] == "4250.00"
    assert sender.sent == [(WA, QUOTE)]
    assert cases.case.current("tank", "agreement") == "true"


def test_missing_size_does_not_invent_a_price():
    class Thin:
        def __init__(self) -> None:
            self.prompts: list[TurnPrompt] = []

        def complete(self, prompt: TurnPrompt) -> ModelReply:
            self.prompts.append(prompt)
            if not prompt.tool_payloads:
                return ModelReply(
                    text="",
                    tool_calls=(
                        ToolCall(
                            name="update_case",
                            arguments={
                                "conversation_id": str(CONVERSATION),
                                "job_id": "tank",
                                "job_type": "replacement",
                                "facts": [],
                            },
                        ),
                        ToolCall(name="get_quote", arguments={"conversation_id": str(CONVERSATION)}),
                    ),
                )
            template = next(item.body["customer_template"] for item in prompt.tool_payloads if item.name == "get_quote")
            return ModelReply(text=template, tool_calls=())

    model = Thin()
    conversations, _, sender, _, turn = harness(model)
    say(conversations, LEAK, 0, str(EVENT))
    turn.execute(CONTEXT, CONVERSATION)
    quote = next(item for item in model.prompts[1].tool_payloads if item.name == "get_quote")
    assert quote.body["rule_id"]["value"] == "WATER-L02"
    assert sender.sent == [(WA, THIN)]
    assert "R" not in THIN


def test_invented_amount_is_still_refused():
    model = QuoteScript("The total is R 3 000.")
    conversations, _, sender, _, turn = harness(model)
    say(conversations, TANK, 0, str(EVENT))
    turn.execute(CONTEXT, CONVERSATION)
    assert sender.sent == [(WA, REFUSAL)]
    assert all("R 3 000" not in body for _, body in sender.sent)


def test_date_comes_from_check_availability():
    def run(speak: str) -> list[tuple[str, str]]:
        class Model:
            def __init__(self) -> None:
                self.prompts: list[TurnPrompt] = []

            def complete(self, prompt: TurnPrompt) -> ModelReply:
                self.prompts.append(prompt)
                if "When can you do it?" in "\n".join(message.body for message in prompt.messages):
                    if not prompt.tool_payloads:
                        return ModelReply(
                            text="",
                            tool_calls=(ToolCall(name="check_availability", arguments={"job_type": "replacement"}),),
                        )
                    return ModelReply(text=speak, tool_calls=())
                if not prompt.tool_payloads:
                    return ModelReply(text="", tool_calls=replacement_calls(prompt))
                return ModelReply(text=QUOTE, tool_calls=())

        model = Model()
        conversations, _, sender, clock, turn = harness(model)
        say(conversations, TANK, 0, str(EVENT))
        turn.execute(CONTEXT, CONVERSATION)
        say(conversations, "When can you do it?", 6, "when-1")
        clock.instant = at(11)
        turn.execute(CONTEXT, CONVERSATION)
        return sender.sent

    assert run(WINDOW)[-1] == (WA, WINDOW)
    refused = run("We can do it this Saturday.")
    assert refused[-1] == (WA, REFUSAL)
    assert all("Saturday" not in body for _, body in refused)


def test_ten_percent_waits_and_states_no_new_total():
    def run(speak: str) -> list[tuple[str, str]]:
        seen: dict[str, str] = {}

        class Model:
            def complete(self, prompt: TurnPrompt) -> ModelReply:
                if "10 percent" in "\n".join(message.body for message in prompt.messages) and not prompt.tool_payloads:
                    return ModelReply(
                        text="",
                        tool_calls=(
                            ToolCall(
                                name="request_change",
                                arguments={
                                    "quote_id": seen["id"],
                                    "version": 1,
                                    "discount_percent": "10",
                                    "reason": "10 percent off",
                                },
                            ),
                        ),
                    )
                if not prompt.tool_payloads:
                    return ModelReply(text="", tool_calls=replacement_calls(prompt))
                quote = next((item for item in prompt.tool_payloads if item.name == "get_quote"), None)
                if quote is not None:
                    seen["id"] = quote.body["quote_id"]["value"]
                    return ModelReply(text=QUOTE, tool_calls=())
                return ModelReply(text=speak, tool_calls=())

        model = Model()
        conversations, _, sender, clock, turn = harness(model)
        say(conversations, TANK, 0, str(EVENT))
        turn.execute(CONTEXT, CONVERSATION)
        say(conversations, "Can I have 10 percent off?", 6, "off-1")
        clock.instant = at(11)
        turn.execute(CONTEXT, CONVERSATION)
        return sender.sent

    assert run(WAITING)[-1] == (WA, WAITING)
    assert run("The total is R 3 825.")[-1] == (WA, REFUSAL)


def test_a_whatsapp_message_id_is_accepted_as_event_id():
    class Model:
        def complete(self, prompt: TurnPrompt) -> ModelReply:
            if not prompt.tool_payloads:
                event_id = prompt.messages[-1].provider_message_id
                return ModelReply(
                    text="",
                    tool_calls=(
                        ToolCall(
                            name="update_case",
                            arguments={
                                "conversation_id": str(CONVERSATION),
                                "job_id": "tank",
                                "job_type": "replacement",
                                "facts": [
                                    {
                                        "key": "size_litres",
                                        "value": "5000",
                                        "source": "customer_text",
                                        "event_id": event_id,
                                    }
                                ],
                            },
                        ),
                    ),
                )
            assert prompt.tool_payloads[0].body.get("error") is None
            return ModelReply(text="Noted.", tool_calls=())

    model = Model()
    conversations, cases, sender, _, turn = harness(model)
    say(conversations, "5000l", 0, "wamid.SIM5000")
    turn.execute(CONTEXT, CONVERSATION)
    assert cases.case.current("tank", "size_litres") == "5000"
    assert sender.sent == [(WA, "Noted.")]


def test_unknown_tool_is_not_called():
    price = PriceFake()

    class Model:
        def __init__(self) -> None:
            self.prompts: list[TurnPrompt] = []

        def complete(self, prompt: TurnPrompt) -> ModelReply:
            self.prompts.append(prompt)
            if not prompt.tool_payloads:
                return ModelReply(text="", tool_calls=(ToolCall(name="price", arguments={"unit_price": "1"}),))
            return ModelReply(text="", tool_calls=())

    model = Model()
    conversations, _, sender, _, turn = harness(model)
    say(conversations, TANK, 0, str(EVENT))
    turn.execute(CONTEXT, CONVERSATION)
    assert price.calls == 0
    assert model.prompts[1].tool_payloads[0].name == "price"
    assert model.prompts[1].tool_payloads[0].body == {"error": "That tool is not available."}
    assert sender.sent == []


def test_second_turn_sees_the_recorded_size():
    class Model:
        def __init__(self) -> None:
            self.prompts: list[TurnPrompt] = []

        def complete(self, prompt: TurnPrompt) -> ModelReply:
            self.prompts.append(prompt)
            if prompt.messages[-1].body == "thanks":
                return ModelReply(text="Thanks.", tool_calls=())
            if not prompt.tool_payloads:
                return ModelReply(text="", tool_calls=replacement_calls(prompt))
            return ModelReply(text=QUOTE, tool_calls=())

    model = Model()
    conversations, _, _, clock, turn = harness(model)
    say(conversations, TANK, 0, str(EVENT))
    turn.execute(CONTEXT, CONVERSATION)
    say(conversations, "thanks", 6, "thanks-1")
    clock.instant = at(11)
    turn.execute(CONTEXT, CONVERSATION)
    seen = model.prompts[-1]
    assert any(fact.key == "size_litres" and fact.value == "5000" for fact in seen.case.facts)
