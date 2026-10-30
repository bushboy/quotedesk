from datetime import datetime, timedelta, timezone
from uuid import UUID

from quotedesk.application.dto.agent import ModelReply, ToolCall
from quotedesk.application.dto.inbound import InboundMessage
from quotedesk.application.dto.tenant import TenantContext
from quotedesk.application.errors import ModelTimeout, TenantRequired
from quotedesk.application.use_cases.conversation.run_agent_turn import (
    HandoverToHuman,
    RunAgentTurn,
    close_batch,
)
from quotedesk.domain.case.case_file import CaseFile
from quotedesk.domain.conversation.events import Conversation, ConversationEvent
from quotedesk.domain.shared.errors import PolicyViolation, ValidationError
from quotedesk.domain.shared.money import Money

TENANT = UUID("11111111-1111-4111-8111-111111111111")
CONVERSATION = UUID("33333333-3333-4333-8333-333333333333")
EVENT = UUID("44444444-4444-4444-8444-444444444444")
BASE = datetime(2026, 10, 24, 0, 0, tzinfo=timezone.utc)
WINDOW = timedelta(seconds=5)
WA = "15550002222"
REFUSAL = "I can only repeat what the quote says."
VIDEO = "Got your video, having a look."
HANDOVER = "I'll ask someone from the business to pick this up. You can keep sending details here."


def at(seconds: float) -> datetime:
    return BASE + timedelta(seconds=seconds)


def event(name: str, seconds: float, body: str | None = None) -> ConversationEvent:
    return ConversationEvent(provider_message_id=name, at=at(seconds), body=name if body is None else body)


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
    def __init__(self, case: CaseFile | None = None) -> None:
        self.case = case

    def get(self, tenant_id: UUID, conversation_id: UUID) -> CaseFile | None:
        return self.case

    def save(self, tenant_id: UUID, case: CaseFile) -> None:
        self.case = case


class Sender:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send(self, wa_id: str, body: str) -> None:
        self.sent.append((wa_id, body))


class Lock:
    def __init__(self) -> None:
        self.held = False
        self.acquires = 0
        self.releases = 0

    def acquire(self, conversation_id: UUID) -> bool:
        self.acquires += 1
        if self.held:
            return False
        self.held = True
        return True

    def release(self, conversation_id: UUID) -> None:
        self.releases += 1
        self.held = False


class Clock:
    def __init__(self, instant: datetime) -> None:
        self.instant = instant

    def now(self) -> datetime:
        return self.instant


class Script:
    def __init__(self, replies: tuple[ModelReply, ...]) -> None:
        self._replies = list(replies)
        self.prompts = []

    def complete(self, prompt) -> ModelReply:
        self.prompts.append(prompt)
        if not self._replies:
            return ModelReply(text="", tool_calls=())
        return self._replies.pop(0)


class Update:
    def __init__(self) -> None:
        self.calls = 0

    def execute(self, context, data) -> None:
        self.calls += 1


class Quote:
    def __init__(self) -> None:
        self.calls = 0

    def execute(self, context, data):
        self.calls += 1
        return type("Result", (), {"total": Money("4250.00"), "price_type": "fixed", "clauses": ()})()


def tools():
    return (
        ToolCall(
            name="update_case",
            arguments={
                "conversation_id": str(CONVERSATION),
                "job_id": "tank",
                "job_type": "replacement",
                "facts": [
                    {
                        "key": "colour",
                        "value": "blue",
                        "source": "customer_text",
                        "event_id": str(EVENT),
                    }
                ],
            },
        ),
        ToolCall(name="get_quote", arguments={"conversation_id": str(CONVERSATION)}),
    )


def turn(model, conversations, sender, clock, cases=None, update=None, availability=None):
    lock = Lock()
    update = update or Update()
    quote = Quote()
    handover = HandoverToHuman(cases or Cases(CaseFile.open(CONVERSATION, TENANT)))
    use_case = RunAgentTurn(
        conversations,
        sender,
        model,
        lock,
        update,
        quote,
        handover,
        clock,
        check_availability=availability,
    )
    return use_case, lock, update, quote, handover


def test_quiet_window_batches_a_burst():
    window = WINDOW
    burst = close_batch((event("a", 0), event("b", 1), event("c", 4)), window=window, now=at(5))
    assert burst is not None
    assert [item.provider_message_id for item in burst] == ["a", "b", "c"]
    edge = close_batch(
        (event("a", 0), event("b", 1), event("c", 4), event("d", 5)),
        window=window,
        now=at(5),
    )
    assert edge is not None
    assert [item.provider_message_id for item in edge] == ["a", "b", "c", "d"]
    split = close_batch(
        (event("a", 0), event("b", 1), event("c", 4), event("e", 5.1)),
        window=window,
        now=at(5.1),
    )
    assert split is not None
    assert [item.provider_message_id for item in split] == ["a", "b", "c"]
    assert close_batch((event("e", 5.1),), window=window, now=at(5.1)) is None


def test_one_turn_at_a_time():
    conversations = Conversations()
    sender = Sender()
    clock = Clock(at(5))
    conversations.save(TENANT, Conversation.open(CONVERSATION).append("wamid.A", at(0), "first").conversation)
    holder: dict[str, RunAgentTurn] = {}

    class Model:
        def __init__(self) -> None:
            self.prompts = []
            self.calls = 0

        def complete(self, prompt):
            self.calls += 1
            self.prompts.append(prompt)
            if self.calls == 1:
                holder["turn"].execute(TenantContext(tenant_id=TENANT), CONVERSATION)
                assert self.calls == 1
                current = conversations.get(TENANT, CONVERSATION)
                assert current is not None
                current = current.append("wamid.C", at(8), "late").conversation
                current = current.append("wamid.B", at(6), "early").conversation
                conversations.save(TENANT, current)
            return ModelReply(text="Thanks.", tool_calls=())

    model = Model()
    use_case, lock, _, _, _ = turn(model, conversations, sender, clock)
    holder["turn"] = use_case
    use_case.execute(TenantContext(tenant_id=TENANT), CONVERSATION)
    assert model.prompts[0].event_ids == ("wamid.A",)
    assert "wamid.B" not in model.prompts[0].event_ids
    assert "wamid.C" not in model.prompts[0].event_ids
    assert lock.held is False
    clock.instant = at(13)
    use_case.execute(TenantContext(tenant_id=TENANT), CONVERSATION)
    assert model.prompts[1].event_ids == ("wamid.A", "wamid.B", "wamid.C")


def test_run_agent_turn_calls_tools_then_checks_the_reply():
    context = TenantContext(tenant_id=TENANT)

    def run(replies: tuple[ModelReply, ...]):
        conversations = Conversations()
        sender = Sender()
        conversations.save(TENANT, Conversation.open(CONVERSATION).append("wamid.A", at(0), "The tank is leaking.").conversation)
        use_case, _, update, quote, _ = turn(Script(replies), conversations, sender, Clock(at(5)))
        use_case.execute(context, CONVERSATION)
        return sender, update, quote

    good, update, quote = run((ModelReply(text="The total is R 4 250.", tool_calls=tools()),))
    assert update.calls == 1
    assert quote.calls == 1
    assert good.sent == [("", "The total is R 4 250.")]
    bad, _, _ = run((ModelReply(text="The total is R 3 000.", tool_calls=tools()),))
    assert bad.sent == [("", HANDOVER)]
    assert all("R 3 000" not in body for _, body in bad.sent)
    safe, _, _ = run(
        (
            ModelReply(text="The total is R 3 000.", tool_calls=tools()),
            ModelReply(text="The total is R 4 250.", tool_calls=()),
        )
    )
    assert safe.sent == [("", "The total is R 4 250.")]
    assert all("R 3 000" not in body for _, body in safe.sent)


def test_slow_media_acknowledgement():
    conversations = Conversations()
    sender = Sender()
    conversations.save(TENANT, Conversation.open(CONVERSATION).append("wamid.V", at(0), "").conversation)
    conversations.remember(
        TENANT,
        InboundMessage(
            conversation_id=CONVERSATION,
            provider_message_id="wamid.V",
            wa_id=WA,
            at=at(0),
            kind="video",
        ),
    )

    class Model:
        def __init__(self) -> None:
            self.calls = 0

        def complete(self, prompt):
            self.calls += 1
            return ModelReply(text="The total is R 4 250.", tool_calls=())

    model = Model()
    use_case, _, _, quote, _ = turn(model, conversations, sender, Clock(at(5)))
    use_case.execute(TenantContext(tenant_id=TENANT), CONVERSATION)
    assert sender.sent == [(WA, VIDEO)]
    assert model.calls == 0
    assert quote.calls == 0


def test_model_timeout_retries_once_then_handover():
    def script(failures: int, text: str):
        conversations = Conversations()
        sender = Sender()
        conversations.save(TENANT, Conversation.open(CONVERSATION).append("wamid.A", at(0), "hello").conversation)

        class Model:
            def __init__(self) -> None:
                self.calls = 0
                self.left = failures

            def complete(self, prompt):
                self.calls += 1
                if self.left:
                    self.left -= 1
                    raise ModelTimeout()
                return ModelReply(text=text, tool_calls=())

        model = Model()
        use_case, _, _, quote, handover = turn(model, conversations, sender, Clock(at(5)))
        use_case.execute(TenantContext(tenant_id=TENANT), CONVERSATION)
        return sender, model, quote, handover

    sender, model, quote, handover = script(1, "The tank is a 5000 L replacement.")
    assert model.calls == 2
    assert sender.sent == [("", "The tank is a 5000 L replacement.")]
    assert quote.calls == 0
    assert handover.records == []
    sender, model, quote, handover = script(2, "unused")
    assert model.calls == 2
    assert sender.sent == [("", HANDOVER)]
    assert quote.calls == 0
    assert handover.records[0].reason == "model timeout"


def test_speak_to_a_person():
    conversations = Conversations()
    sender = Sender()
    case = CaseFile.open(CONVERSATION, TENANT).add_job("tank", "replacement")
    cases = Cases(case)
    conversations.save(
        TENANT,
        Conversation.open(CONVERSATION).append("wamid.H", at(0), "can I speak to a person?").conversation,
    )

    class Model:
        def __init__(self) -> None:
            self.calls = 0

        def complete(self, prompt):
            self.calls += 1
            return ModelReply(text="The total is R 4 250.", tool_calls=tools())

    model = Model()
    use_case, _, _, quote, handover = turn(model, conversations, sender, Clock(at(5)), cases)
    with __import__("pytest").raises(TenantRequired):
        use_case.execute(None, CONVERSATION)
    use_case.execute(TenantContext(tenant_id=TENANT), CONVERSATION)
    assert model.calls == 0
    assert quote.calls == 0
    assert len(handover.records) == 1
    assert handover.records[0].reason == "Can I speak to a person?"
    assert handover.records[0].case.jobs[0].job_id == "tank"
    assert sender.sent == [("", HANDOVER)]


def test_a_new_job_without_a_type_is_sent_back_to_the_model():
    class TypedUpdate(Update):
        def execute(self, context, data):
            self.calls += 1
            if data.job_type is None:
                raise ValidationError(code="job.type_required", sentence="A new job names its type.")

    size = {
        "key": "size_litres",
        "value": "2500",
        "source": "customer_text",
        "event_id": str(EVENT),
    }
    missing = ToolCall(name="update_case", arguments={"job_id": "tank", "facts": [size]})
    named = ToolCall(
        name="update_case",
        arguments={"job_id": "tank", "job_type": "replacement", "facts": [size]},
    )
    conversations = Conversations()
    sender = Sender()
    conversations.save(
        TENANT,
        Conversation.open(CONVERSATION).append("wamid.A", at(0), "The 2500 L tank.").conversation,
    )
    update = TypedUpdate()
    script = Script(
        (
            ModelReply(text="I'll record that 2500L tank choice.", tool_calls=(missing,)),
            ModelReply(text="", tool_calls=(named,)),
            ModelReply(text="Is that tank on the existing level base?", tool_calls=()),
        )
    )
    use_case, _, _, quote, _ = turn(script, conversations, sender, Clock(at(5)), update=update)
    use_case.execute(TenantContext(tenant_id=TENANT), CONVERSATION)
    assert update.calls == 2
    assert quote.calls == 1
    assert sender.sent == [("", "Is that tank on the existing level base?")]
    assert script.prompts[1].tool_payloads[0].body["error"] == "A new job names its type."


def test_a_closed_calendar_still_replies_with_the_turnaround():
    class Closed:
        def execute(self, context, data):
            raise PolicyViolation(code="policy.violation", sentence="That calendar has no open day.")

    conversations = Conversations()
    sender = Sender()
    conversations.save(
        TENANT,
        Conversation.open(CONVERSATION).append("wamid.A", at(0), "How soon can you fit it?").conversation,
    )
    script = Script(
        (
            ModelReply(
                text="I'll check the earliest availability for your replacement.",
                tool_calls=(ToolCall(name="check_availability", arguments={"job_type": "replacement"}),),
            ),
        )
    )
    use_case, _, _, _, _ = turn(script, conversations, sender, Clock(at(5)), availability=Closed())
    use_case.execute(TenantContext(tenant_id=TENANT), CONVERSATION)
    assert sender.sent == [("", "That calendar has no open day.")]
