from quotedesk.application.dto.agent import ExtractionResult, ModelReply, ToolCall, TurnOutcome, TurnPrompt
from quotedesk.application.dto.tenant import TenantContext
from quotedesk.application.errors import ModelTimeout, ToolArgumentsInvalid
from quotedesk.domain.conversation.events import Conversation, ConversationEvent
from quotedesk.domain.shared.errors import InvalidTransition
from quotedesk.infrastructure.demo import Conversations as Memory
from tests.use_cases.test_run_agent_turn import (
    CONVERSATION,
    Cases,
    Clock,
    Conversations,
    HANDOVER,
    Sender,
    TENANT,
    at,
    turn,
)

ACK = "Thanks, I've added that for the team."
CONTEXT = TenantContext(tenant_id=TENANT)


class Counting:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0

    def complete(self, prompt):
        self.calls += 1
        if not self.replies:
            return ModelReply(text="", tool_calls=())
        reply = self.replies.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        return reply


class Ledger(Conversations):
    def __init__(self) -> None:
        super().__init__()
        self.held: set[tuple] = set()

    def hold_escalation(self, tenant_id, conversation_id) -> None:
        self.held.add((tenant_id, conversation_id))

    def release_escalation(self, tenant_id, conversation_id) -> None:
        self.held.discard((tenant_id, conversation_id))

    def escalation_held(self, tenant_id, conversation_id) -> bool:
        return (tenant_id, conversation_id) in self.held


def _open(store, body: str, message_id: str = "wamid.A", seconds: float = 0) -> None:
    store.save(TENANT, Conversation.open(CONVERSATION).append(message_id, at(seconds), body).conversation)


def test_an_empty_greeting_is_retried_and_not_escalated():
    store = Conversations()
    sender = Sender()
    _open(store, "hello")
    model = Counting(
        (
            ModelReply(text="", tool_calls=()),
            ModelReply(text="Hello, I can help with that.", tool_calls=()),
        )
    )
    use_case, _, _, quote, handover = turn(model, store, sender, Clock(at(5)))
    outcome = use_case.execute(CONTEXT, CONVERSATION)
    assert model.calls == 2
    assert outcome == TurnOutcome.ANSWERED
    assert sender.sent == [("", "Hello, I can help with that.")]
    assert handover.records == []
    assert quote.calls == 0
    stored = store.get(TENANT, CONVERSATION)
    assert stored.events[0].status == "answered"
    assert stored.events[0].outcome == "answered"


def test_two_empty_replies_escalate_once():
    store = Conversations()
    sender = Sender()
    _open(store, "hello")
    model = Counting((ModelReply(text="", tool_calls=()), ModelReply(text="  ", tool_calls=())))
    use_case, _, _, _, handover = turn(model, store, sender, Clock(at(5)))
    assert use_case.execute(CONTEXT, CONVERSATION) == TurnOutcome.ASKED
    assert model.calls == 2
    assert sender.sent == [("", "What should I quote for you?")]
    assert "R " not in sender.sent[0][1]
    stored = store.get(TENANT, CONVERSATION)
    assert stored.events[0].status == "answered"
    assert stored.events[0].outcome == "asked"
    use_case.execute(CONTEXT, CONVERSATION)
    assert model.calls == 2


def test_invalid_transition_does_not_call_the_model_again():
    store = Conversations()
    sender = Sender()
    _open(store, "hello")
    model = Counting((InvalidTransition("quote.invalid_transition", "That state change is not allowed."),))
    use_case, _, _, quote, handover = turn(model, store, sender, Clock(at(5)))
    assert use_case.execute(CONTEXT, CONVERSATION) == TurnOutcome.ESCALATED
    assert sender.sent == [("", HANDOVER)]
    assert "InvalidTransition" in handover.records[0].reason
    assert "That state change is not allowed." not in sender.sent[0][1]
    assert quote.calls == 0
    use_case.execute(CONTEXT, CONVERSATION)
    assert model.calls == 1


def test_a_held_conversation_acknowledges_and_does_not_quote():
    store = Ledger()
    sender = Sender()
    _open(store, "hello")
    model = Counting(
        (
            ModelTimeout(),
            ModelTimeout(),
            ModelReply(
                text="",
                tool_calls=(ToolCall(name="get_quote", arguments={"conversation_id": str(CONVERSATION)}),),
            ),
        )
    )
    use_case, _, update, quote, handover = turn(model, store, sender, Clock(at(5)))
    assert use_case.execute(CONTEXT, CONVERSATION) == TurnOutcome.ESCALATED
    current = store.get(TENANT, CONVERSATION)
    current = current.append("wamid.B", at(20), "the base is cracked").conversation
    store.save(TENANT, current)
    use_case._clock.instant = at(26)
    assert use_case.execute(CONTEXT, CONVERSATION) == TurnOutcome.ANSWERED
    assert quote.calls == 0
    assert update.calls == 0
    assert sender.sent[-1] == ("", ACK)
    assert "the base is cracked" in handover.records[-1].reason
    assert (TENANT, CONVERSATION) in store.held
    store.release_escalation(TENANT, CONVERSATION)
    assert not store.escalation_held(TENANT, CONVERSATION)


def test_an_unsent_reply_is_sent_once_without_the_model():
    store = Memory()
    sender = Sender()
    _open(store, "hello")
    current = store.get(TENANT, CONVERSATION)
    log = tuple(
        event.model_copy(update={"status": "answered", "outcome": "answered"}) for event in current.log
    )
    store.save(TENANT, current.model_copy(update={"log": log}))
    store.reserve_outbound(TENANT, "wamid.A", CONVERSATION, at(0), "The price is ready.")
    model = Counting(())
    use_case, _, _, _, _ = turn(model, store, sender, Clock(at(5)), cases=Cases())
    use_case.execute(CONTEXT, CONVERSATION)
    assert model.calls == 0
    assert sender.sent == [("", "The price is ready.")]
    use_case.execute(CONTEXT, CONVERSATION)
    assert model.calls == 0
    assert sender.sent == [("", "The price is ready.")]


def test_a_second_claim_does_not_answer_the_batch():
    store = Memory()
    sender = Sender()
    _open(store, "hello")
    assert store.claim_pending(TENANT, CONVERSATION, ("wamid.A",)) == ("wamid.A",)
    model = Counting((ModelReply(text="Hello.", tool_calls=()),))
    use_case, _, _, _, _ = turn(model, store, sender, Clock(at(5)))
    assert use_case.execute(CONTEXT, CONVERSATION) is None
    assert model.calls == 0
    assert sender.sent == []


def test_a_new_turn_reuses_the_stored_extraction():
    store = Memory()
    result = ExtractionResult(summary="a green tank", objects=("tank",))
    store.save_enrichment(TENANT, "img-1", result)

    class Enricher:
        def __init__(self) -> None:
            self.calls = 0

        def for_image(self, provider_message_id: str):
            self.calls += 1
            return result

    enricher = Enricher()
    event = ConversationEvent(provider_message_id="img-1", at=at(0), body="photo")
    for _ in range(2):
        use_case, _, _, _, _ = turn(Counting(()), store, Sender(), Clock(at(5)))
        use_case.enricher = enricher
        use_case._active_tenant = TENANT
        found = use_case._read_image(CONTEXT, CONVERSATION, event)
        assert found is not None
        assert found.summary == "a green tank"
    assert enricher.calls == 0


def test_a_turn_calls_the_model_at_most_four_times():
    store = Ledger()
    model = Counting(tuple(ModelReply(text="Hello, I can help with that.", tool_calls=()) for _ in range(5)))
    use_case, _, _, _, _ = turn(model, store, Sender(), Clock(at(5)))
    prompt = TurnPrompt(event_ids=())
    for _ in range(4):
        assert use_case._complete(prompt) is not None
    assert use_case._complete(prompt) is None
    assert model.calls == 4


def test_invalid_tool_arguments_are_retried_once_then_escalated():
    store = Ledger()
    sender = Sender()
    _open(store, "hello")

    class Bad:
        def __init__(self) -> None:
            self.calls = 0
            self.prompts: list[TurnPrompt] = []

        def complete(self, prompt: TurnPrompt) -> ModelReply:
            self.calls += 1
            self.prompts.append(prompt)
            raise ToolArgumentsInvalid()

    model = Bad()
    use_case, _, _, _, _ = turn(model, store, sender, Clock(at(5)))
    assert use_case.execute(CONTEXT, CONVERSATION) == TurnOutcome.ESCALATED
    assert model.calls == 2
    assert sender.sent == [("", HANDOVER)]
    assert model.prompts[1].exchanges[-1]["type"] == "function_call_output"
    assert "could not be read" in model.prompts[1].exchanges[-1]["output"]
