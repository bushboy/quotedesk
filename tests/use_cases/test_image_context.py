from quotedesk.application.dto.agent import ExtractionResult, ModelReply
from quotedesk.application.use_cases.conversation.run_agent_turn import AGENT_TASK
from tests.use_cases.test_photo_turn import (
    CAPTION,
    IMAGE,
    MARKER,
    SUMMARY,
    Enricher,
    Speaking,
    harness,
    picture,
    stated_size,
    tank_mask,
    text,
)
from tests.use_cases.test_typed_turn import CONTEXT, CONVERSATION, QUOTE, TENANT, THIN, WA, replacement_calls

IMAGE_B = "66666666-6666-4666-8666-666666666667"
LATER = "77777777-7777-4777-8777-777777777777"
STATED = "Replace it with a 5000 litre tank on the existing level base."
CAPTION_SIZE = "5000 litre, the base is level"


class Counting:
    def __init__(self, by_id: dict[str, ExtractionResult]) -> None:
        self.by_id = by_id
        self.calls: list[str] = []

    def for_image(self, provider_message_id: str) -> ExtractionResult | None:
        self.calls.append(provider_message_id)
        return self.by_id.get(provider_message_id)


def test_caption_stays_on_the_message_and_the_summary_is_separate():
    enricher = Enricher(tank_mask())
    model = Speaking(replacement_calls)
    conversations, _, _, turn = harness(model, enricher)
    picture(conversations, CAPTION, 0, IMAGE)
    turn.execute(CONTEXT, CONVERSATION)
    prompt = model.prompts[0]
    image = next(message for message in prompt.messages if message.kind == "image")
    assert image.body == CAPTION
    assert prompt.extractions[0].summary == SUMMARY
    assert prompt.extractions[0].objects == ("tank",)
    dumped = str(prompt.model_dump(mode="json"))
    assert MARKER not in dumped
    assert "0.91" not in dumped
    assert "4250" not in dumped
    assert "Use each extraction with the message it names." in AGENT_TASK
    assert "When the photo and the customer disagree, ask one question." in AGENT_TASK
    assert "A size that appears only in an extraction is not customer_stated." in AGENT_TASK
    assert "offer the descriptions on the rate card" in AGENT_TASK


def test_two_images_are_two_rows():
    enricher = Counting(
        {
            IMAGE: tank_mask(),
            IMAGE_B: ExtractionResult(summary="A pump beside the tank.", objects=("pump",)),
        }
    )
    model = Speaking(replacement_calls)
    conversations, _, sender, turn = harness(model, enricher)
    picture(conversations, CAPTION, 0, IMAGE)
    picture(conversations, "", 1, IMAGE_B)
    turn.execute(CONTEXT, CONVERSATION)
    rows = model.prompts[0].extractions
    assert [row.provider_message_id for row in rows] == [IMAGE, IMAGE_B]
    assert rows[0].objects == ("tank",)
    assert rows[1].objects == ("pump",)
    assert sender.sent == [(WA, THIN)]
    assert "R" not in sender.sent[0][1]


def test_a_later_text_still_sees_the_photo():
    enricher = Counting({IMAGE: tank_mask()})

    class Later:
        def __init__(self) -> None:
            self.prompts = []

        def complete(self, prompt) -> ModelReply:
            self.prompts.append(prompt)
            stated = any("5000" in (message.body or "") for message in prompt.messages)
            if not stated:
                return ModelReply(text="I can see the tank.", tool_calls=())
            if not prompt.tool_payloads:
                return ModelReply(text="", tool_calls=replacement_calls(prompt))
            return ModelReply(text=QUOTE, tool_calls=())

    model = Later()
    conversations, _, sender, turn = harness(model, enricher)
    picture(conversations, CAPTION, 0, IMAGE)
    turn.execute(CONTEXT, CONVERSATION)
    text(conversations, STATED, 0, LATER)
    turn.execute(CONTEXT, CONVERSATION)
    stored = conversations.get(TENANT, CONVERSATION)
    image = next(event for event in stored.events if event.provider_message_id == IMAGE)
    assert image.extraction_id == IMAGE
    assert image.body == CAPTION
    assert model.prompts[1].extractions[0].summary == SUMMARY
    assert enricher.calls == [IMAGE]
    assert sender.sent[-1][1] == QUOTE


def test_caption_size_can_be_customer_stated():
    class Script:
        def __init__(self) -> None:
            self.prompts = []

        def complete(self, prompt) -> ModelReply:
            self.prompts.append(prompt)
            if not prompt.tool_payloads:
                return ModelReply(text="", tool_calls=replacement_calls(prompt))
            return ModelReply(text=QUOTE, tool_calls=())

    model = Script()
    conversations, _, sender, turn = harness(model, Enricher(tank_mask()))
    picture(conversations, CAPTION_SIZE, 0, IMAGE)
    turn.execute(CONTEXT, CONVERSATION)
    quote = next(item for item in model.prompts[1].tool_payloads if item.name == "get_quote")
    assert quote.body["total"]["amount"] == "4250.00"
    assert sender.sent == [(WA, QUOTE)]


def test_a_size_only_in_the_summary_does_not_issue():
    inferred = tank_mask()
    inferred = inferred.model_copy(update={"summary": "A 5000 L tank on a level base."})
    model = Speaking(stated_size)
    conversations, _, sender, turn = harness(model, Enricher(inferred))
    picture(conversations, CAPTION, 0, IMAGE)
    turn.execute(CONTEXT, CONVERSATION)
    assert model.prompts[0].extractions[0].summary == "A 5000 L tank on a level base."
    assert sender.sent == [(WA, THIN)]
    assert "R" not in sender.sent[0][1]


def test_blur_or_sam_error_does_not_issue():
    blur = tank_mask(blur=True)
    failed = ExtractionResult(
        summary=SUMMARY,
        objects=("tank",),
        sam_error=True,
        sam_sentence="The segmenter did not return a result.",
    )
    for result in (blur, failed):
        model = Speaking(replacement_calls)
        conversations, _, sender, turn = harness(model, Enricher(result))
        picture(conversations, CAPTION_SIZE, 0, IMAGE)
        turn.execute(CONTEXT, CONVERSATION)
        assert model.prompts[0].extractions[0].summary == SUMMARY
        assert sender.sent == [(WA, THIN)]
        assert "R" not in sender.sent[0][1]
