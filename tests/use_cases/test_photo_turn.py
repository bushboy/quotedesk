from decimal import Decimal

from quotedesk.application.dto.agent import ExtractionResult, ModelReply, ToolCall
from quotedesk.application.dto.inbound import InboundMessage
from quotedesk.application.use_cases.conversation.run_agent_turn import HandoverToHuman, RunAgentTurn
from quotedesk.application.use_cases.tools.get_quote import GetQuote
from quotedesk.application.use_cases.tools.update_case import UpdateCase
from quotedesk.domain.case.case_file import CaseFile
from quotedesk.domain.conversation.events import Conversation
from quotedesk.domain.services.confidence import RecordedMask
from tests.use_cases.test_typed_turn import (
    CONVERSATION,
    CONTEXT,
    EVENT,
    QUOTE,
    TANK,
    TENANT,
    THIN,
    WA,
    AvailabilityFake,
    Cases,
    Catalog,
    ChangeFake,
    Clock,
    Conversations,
    Ids,
    Lock,
    Policies,
    Sender,
    Unit,
    at,
    replacement_calls,
)

IMAGE = "66666666-6666-4666-8666-666666666666"
CAPTION = "By the gate"
MARKER = "not-a-real-photo-byte-marker"
SUMMARY = "A tank on a level base."


def tank_mask(**flags: bool) -> ExtractionResult:
    return ExtractionResult(
        summary=SUMMARY,
        objects=("tank",),
        masks=(RecordedMask(label="tank", score=Decimal("0.91")),),
        **flags,
    )


class Enricher:
    def __init__(self, result: ExtractionResult | None) -> None:
        self.result = result
        self.photo_bytes = MARKER.encode()

    def for_image(self, provider_message_id: str) -> ExtractionResult | None:
        return self.result


class Speaking:
    def __init__(self, calls) -> None:
        self.calls = calls
        self.prompts = []

    def complete(self, prompt) -> ModelReply:
        self.prompts.append(prompt)
        if not prompt.tool_payloads:
            return ModelReply(text="", tool_calls=self.calls(prompt))
        template = next(item.body["customer_template"] for item in prompt.tool_payloads if item.name == "get_quote")
        return ModelReply(text=template, tool_calls=())


def harness(model, enricher: Enricher):
    conversations = Conversations()
    cases = Cases(CaseFile.open(CONVERSATION, TENANT))
    policies = Policies()
    ids = Ids()
    catalog = Catalog()
    clock = Clock(at(5))
    sender = Sender()
    turn = RunAgentTurn(
        conversations,
        sender,
        model,
        Lock(),
        UpdateCase(cases, catalog, ids),
        GetQuote(cases, policies, Unit(), clock, ids),
        HandoverToHuman(cases),
        clock,
        request_change=ChangeFake(),
        check_availability=AvailabilityFake(),
        catalog=catalog,
        policies=policies,
        ids=ids,
        card_base="/card",
        card_code="1042",
        enricher=enricher,
    )
    return conversations, cases, sender, turn


def picture(conversations: Conversations, caption: str, seconds: float, message_id: str) -> None:
    current = conversations.get(TENANT, CONVERSATION) or Conversation.open(CONVERSATION)
    conversations.save(TENANT, current.append(message_id, at(seconds), caption).conversation)
    conversations.remember(
        TENANT,
        InboundMessage(
            conversation_id=CONVERSATION,
            provider_message_id=message_id,
            wa_id=WA,
            at=at(seconds),
            kind="image",
            body=caption,
        ),
    )


def text(conversations: Conversations, body: str, seconds: float, message_id: str) -> None:
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


def stated_size(prompt):
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
                    {"key": "size_source", "value": "photo_inferred", **fact},
                    {"key": "existing_level_base", "value": "true", **fact},
                    {"key": "item_codes", "value": "TANK-5000", **fact},
                ],
            },
        ),
        ToolCall(name="get_quote", arguments={"conversation_id": str(CONVERSATION)}),
    )


def test_clean_photo_keeps_water_f01():
    class Script:
        def __init__(self) -> None:
            self.prompts = []

        def complete(self, prompt) -> ModelReply:
            self.prompts.append(prompt)
            if not prompt.tool_payloads:
                return ModelReply(text="", tool_calls=replacement_calls(prompt))
            return ModelReply(text=QUOTE, tool_calls=())

    model = Script()
    conversations, cases, sender, turn = harness(model, Enricher(tank_mask()))
    text(conversations, TANK, 0, str(EVENT))
    picture(conversations, CAPTION, 1, IMAGE)
    turn.execute(CONTEXT, CONVERSATION)
    first, second = model.prompts
    image = next(message for message in first.messages if message.kind == "image")
    assert image.body == CAPTION
    assert first.extractions[0].summary == SUMMARY
    assert first.extractions[0].objects == ("tank",)
    dumped = str(first.extractions[0].model_dump(mode="json"))
    assert "4250" not in dumped
    assert "0.91" not in dumped
    update = next(item for item in second.tool_payloads if item.name == "update_case")
    assert "agreement" not in update.body["current"]
    quote = next(item for item in second.tool_payloads if item.name == "get_quote")
    assert quote.body["rule_id"]["value"] == "WATER-F01"
    assert quote.body["outcome"] == "fixed_offer"
    assert quote.body["total"]["amount"] == "4250.00"
    assert sender.sent == [(WA, QUOTE)]
    assert cases.case.current("tank", "agreement") == "true"


def test_photo_inferred_size_does_not_issue_a_fixed_price():
    model = Speaking(stated_size)
    conversations, _, sender, turn = harness(model, Enricher(tank_mask()))
    text(conversations, TANK, 0, str(EVENT))
    picture(conversations, CAPTION, 1, IMAGE)
    turn.execute(CONTEXT, CONVERSATION)
    assert sender.sent == [(WA, THIN)]
    assert "R" not in THIN


def test_blur_does_not_issue_a_fixed_price():
    model = Speaking(replacement_calls)
    conversations, cases, sender, turn = harness(model, Enricher(tank_mask(blur=True)))
    text(conversations, TANK, 0, str(EVENT))
    picture(conversations, CAPTION, 1, IMAGE)
    turn.execute(CONTEXT, CONVERSATION)
    assert cases.case.current("tank", "media_usable") == "false"
    assert sender.sent == [(WA, THIN)]
    assert "R" not in sender.sent[0][1]


def test_sam_error_does_not_issue_a_fixed_price():
    failed = ExtractionResult(
        summary=SUMMARY,
        objects=("tank",),
        sam_error=True,
        sam_sentence="The segmenter did not return a result.",
    )
    model = Speaking(replacement_calls)
    conversations, cases, sender, turn = harness(model, Enricher(failed))
    text(conversations, TANK, 0, str(EVENT))
    picture(conversations, CAPTION, 1, IMAGE)
    turn.execute(CONTEXT, CONVERSATION)
    assert cases.case.current("tank", "agreement") == "false"
    assert sender.sent == [(WA, THIN)]
    assert "R" not in sender.sent[0][1]


def test_image_bytes_are_not_in_the_prompt():
    class Peek:
        def __init__(self) -> None:
            self.prompts = []

        def complete(self, prompt) -> ModelReply:
            self.prompts.append(prompt)
            return ModelReply(text="Thanks.", tool_calls=())

    model = Peek()
    enricher = Enricher(tank_mask())
    conversations, _, _, turn = harness(model, enricher)
    picture(conversations, CAPTION, 0, IMAGE)
    turn.execute(CONTEXT, CONVERSATION)
    prompt = model.prompts[0]
    image = next(message for message in prompt.messages if message.kind == "image")
    assert image.body == CAPTION
    assert prompt.extractions[0].summary == SUMMARY
    assert MARKER not in str(prompt.model_dump(mode="json"))
    assert enricher.photo_bytes.decode() == MARKER
