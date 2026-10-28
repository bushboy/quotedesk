# Photo on the typed quote

Written 28 October 2026. Block A tests and `quotedesk/application/dto/agent.py`, `quotedesk/application/ports/media.py`, and `quotedesk/application/use_cases/conversation/run_agent_turn.py` implement the turn half of this note. Block B tests and `quotedesk/adapters/outbound/models/recorded_extraction.py`, with the wiring in `quotedesk/infrastructure/demo.py`, implement the recording.

The decisions in [the slice plan](../PLAN.md) are confirmed. D4 stays. D3 changes only for a batch that contains an image. The model interprets the job. Code commits the price. `decide`, `price`, `select_clauses`, `derive_confidence`, `cross_model_agreement`, `measurement_acceptable`, `media_is_usable`, `GetQuote`, `RequestChange`, `CheckAvailability`, `UpdateCase`, and `check_reply` are not edited. The SAM parser is not edited.

A test of the turn does not open a socket. The adapter test does not call `api.meta.ai` or Baseten.

## Modules

| Name | Module |
| --- | --- |
| `PromptExtraction`, `ExtractionResult` | `quotedesk.application.dto.agent` |
| `MediaEnricher` | `quotedesk.application.ports.media` |
| `RunAgentTurn` | `quotedesk.application.use_cases.conversation.run_agent_turn` |
| `RecordedEnricher`, `load_recording` | `quotedesk.adapters.outbound.models.recorded_extraction` |

`AgentModel` stays `complete(prompt) -> ModelReply`. The turn does not import `sam_parser`. The adapter may. The use case does not import the adapter.

## Prompt

`TurnPrompt` gains one field, with a default, so `TurnPrompt(event_ids=("wamid.A",))` still builds.

```text
PromptExtraction
    provider_message_id: str
    summary: str
    objects: tuple[str, ...]

TurnPrompt
    extractions: tuple[PromptExtraction, ...] = ()
```

Frozen. `extra` is forbid.

One row per enriched image among the last 20 events, in that same order. The row has the provider message id, the summary, and the object names. It has no score and no unit price. A text event adds no row. An image whose enricher returns nothing adds no row.

The image `PromptMessage.body` stays `ConversationEvent.body`, the caption. The bytes of the photo are not copied into the prompt.

## Enricher

```text
ExtractionResult
    summary: str
    objects: tuple[str, ...]
    blur: bool = False
    darkness: bool = False
    wrong_subject: bool = False
    masks: tuple[RecordedMask, ...] = ()
    sam_error: bool = False
    sam_sentence: str = ""

MediaEnricher.for_image(provider_message_id) -> ExtractionResult | None
```

`RecordedMask` is the domain type: `label` and `score`. A score is a `Decimal`.

`None` means the image has no enrichment. The prompt gets no row for it. Agreement then sees no masks.

```text
RunAgentTurn(..., *, enricher=None)
```

`enricher` is keyword-only and defaults to absent. Absent keeps today's confidence inputs: no objects, no masks, `sam_error` false, `has_media` false. `has_image` and `has_video` still come from the closed batch. The typed-turn constructor does not pass `enricher`.

## Recordings

Files live in `tests/fixtures/extraction/`. Each names a SAM file under `tests/fixtures/sam/`. The adapter reads those files. It does not read `seeds/media/tank-on-base.png`. The pixels stay there for the evening gate.

| Name | Summary | Objects | Flags | SAM file |
| --- | --- | --- | --- | --- |
| `tank-on-base` | `A tank on a level base.` | `tank` | all false | `tank_success.json` |
| `tank-blur` | `A tank on a level base.` | `tank` | `blur` true, the other two false | `tank_success.json` |
| `sam-error` | `A tank on a level base.` | `tank` | all false | `error.json` |
| `no-mask` | `A tank on a level base.` | `tank` | all false | `no_mask.json` |

`tank_success.json` is one mask, label `tank`, score `0.91`. `load_recording` maps that to `RecordedMask` with `Decimal("0.91")`. `error.json` sets `sam_error` true, `masks` empty, and `sam_sentence` to `The segmenter did not return a result.` `no_mask.json` sets `sam_error` false and `masks` empty.

`RecordedEnricher.for_image` ignores the id and returns `load_recording("tank-on-base")`. This slice has one photo on the running app. Blur, the SAM error, and the empty masks are selected by the tests through `load_recording` or a fake.

## Confidence, written before get_quote

The five facts, the source `customer_text`, and the last event id stay as the typed turn wrote them. Catalog and policies must both be present, and the case must have a job. Saturday's turn has neither dependency, so it still writes nothing.

When `enricher` is absent, the call is unchanged: `spark_objects` empty, `masks` empty, `sam_error` false, `media_is_usable` with `has_media` false.

When `enricher` is present and the closed batch has no image, `has_media` is false and `extractions` is empty.

When `enricher` is present and the batch has an image, `has_media` is true. The turn calls `for_image` for each image in the batch.

| Enricher result | Agreement inputs | Usability |
| --- | --- | --- |
| One result | Its objects, its masks, its `sam_error` | Its blur, darkness, and wrong-subject flags |
| `None`, or any image in the batch returns `None` | No objects, no masks, `sam_error` false | Flags false |

The threshold stays `Decimal("0.80")`. More than one image unions the object names and the masks, and a true flag on any image stays true. This slice's tests send one image.

A clean tank mask at `0.91` with object `tank` passes agreement. `sam_error`, or no masks, fails it. `blur` true fails `media_is_usable` and does not fail agreement.

## What the quote does

WATER-F01 still needs high confidence, job `replacement`, `size_litres` `5000`, `size_source` `customer_stated`, `existing_level_base` true, and `item_codes` including `TANK-5000`. The clean recording plus those facts issues total `4250.00`. The reply is:

```text
The total is R 4 250. Your card: /card/QD-1042?code=1042
```

`photo_inferred` fails measurement and is not `customer_stated`, so WATER-F01 does not match. Blur fails media and drops the band to medium. A SAM error fails agreement and drops the band to medium. Each of those is WATER-L02. The outbox is:

```text
We don't have a standard price for this job. A site visit is the next step.
```

That sentence has no rand amount. The card link stays unset because the outcome is a site visit.

The model may still send `agreement=true` on `update_case`. That key is dropped before `UpdateCase`. The turn writes `agreement` afterwards. The four tool names stay the only ones dispatched.
