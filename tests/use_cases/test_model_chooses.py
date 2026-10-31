from quotedesk.application.dto.agent import ModelReply, ToolCall
from quotedesk.application.dto.inbound import InboundMessage
from quotedesk.application.use_cases.conversation.run_agent_turn import AGENT_TASK
from quotedesk.domain.conversation.events import Conversation
from tests.use_cases.test_typed_turn import (
    CONVERSATION,
    CONTEXT,
    EVENT,
    QUOTE,
    HANDOVER,
    TENANT,
    WA,
    at,
    harness,
    replacement_calls,
)

CUSTOMER = "eish the jojo out back finally gave up, swap it for another 5000 litre one, the base is still level"
CHOSEN = "We can swap that tank. The total is R 4 250. Your card: /card/QD-1042?code=1042"


class Choosing:
    def __init__(self, speak: str) -> None:
        self.speak = speak
        self.prompts = []

    def complete(self, prompt) -> ModelReply:
        self.prompts.append(prompt)
        if not prompt.tool_payloads:
            return ModelReply(text="", tool_calls=replacement_calls(prompt))
        return ModelReply(text=self.speak, tool_calls=())


def say(conversations, body: str) -> None:
    current = conversations.get(TENANT, CONVERSATION) or Conversation.open(CONVERSATION)
    conversations.save(TENANT, current.append(str(EVENT), at(0), body).conversation)
    conversations.remember(
        TENANT,
        InboundMessage(
            conversation_id=CONVERSATION,
            provider_message_id=str(EVENT),
            wa_id=WA,
            at=at(0),
            kind="text",
            body=body,
        ),
    )


def test_unstructured_words_are_answered_by_the_model():
    model = Choosing(CHOSEN)
    conversations, _, sender, _, turn = harness(model)
    say(conversations, CUSTOMER)
    turn.execute(CONTEXT, CONVERSATION)
    first = model.prompts[0]
    assert first.task.startswith(AGENT_TASK)
    assert "```business" in first.task
    assert "Do not stay silent." in first.task
    assert first.messages[-1].body == CUSTOMER
    assert CHOSEN not in first.task
    assert QUOTE not in first.task
    assert sender.sent == [(WA, CHOSEN)]


def test_a_wrong_conversation_id_still_uses_the_open_thread():
    class WrongId:
        def complete(self, prompt) -> ModelReply:
            self.prompt = prompt
            if not prompt.tool_payloads:
                calls = []
                for call in replacement_calls(prompt):
                    arguments = dict(call.arguments)
                    arguments["conversation_id"] = "99999999-9999-4999-8999-999999999999"
                    calls.append(ToolCall(name=call.name, arguments=arguments))
                return ModelReply(text="", tool_calls=tuple(calls))
            return ModelReply(text=CHOSEN, tool_calls=())

    conversations, _, sender, _, turn = harness(WrongId())
    say(conversations, CUSTOMER)
    turn.execute(CONTEXT, CONVERSATION)
    assert sender.sent == [(WA, CHOSEN)]


def test_a_greeting_is_sent():
    class Greeting:
        def complete(self, prompt) -> ModelReply:
            return ModelReply(text="Hi, what can I help you with today?", tool_calls=())

    conversations, _, sender, _, turn = harness(Greeting())
    say(conversations, "hello")
    turn.execute(CONTEXT, CONVERSATION)
    assert sender.sent == [(WA, "Hi, what can I help you with today?")]


def test_a_chosen_sentence_with_the_wrong_total_is_refused():
    model = Choosing("The total is R 3 000. Your card: /card/QD-1042?code=1042")
    conversations, _, sender, _, turn = harness(model)
    say(conversations, CUSTOMER)
    turn.execute(CONTEXT, CONVERSATION)
    assert sender.sent == [(WA, "We can send a fixed quote for this replacement. The total is R 4250.00. /card/QD-1042?code=1042")]
    assert all("R 3 000" not in body for _, body in sender.sent)
