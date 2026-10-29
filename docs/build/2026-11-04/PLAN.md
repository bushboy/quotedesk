# Image context

The recorded photo slice is green. On the running app every photo is still described as the tank fixture, and the webhook throws away the media id, so the bytes in `/sim/media` are never read. This slice reads each uploaded image, keeps that description on the conversation, and uses it for the reply and for agreement. The model still does not set the price. Voice stays after this gate.

The week plan is [QuoteDesk_Build_Plan.md](../QuoteDesk_Build_Plan.md). The recorded-photo list is [2026-11-03/PLAN.md](../2026-11-03/PLAN.md). The design for this slice goes in [design/](design/) before any test. Tick a box only when that item is actually done.

**You:** block A. The prompt shows one extraction per image, including an image from an earlier turn, and the confidence write uses those stored objects, masks, and usability flags. You own `quotedesk/application/dto/` and `quotedesk/application/ports/` for this slice. You do not reopen `decide`, `price`, `select_clauses`, `derive_confidence`, `cross_model_agreement`, `measurement_acceptable`, `media_is_usable`, `GetQuote`, `RequestChange`, `CheckAvailability`, `UpdateCase`, or `check_reply`. The SAM parser is not edited.

**Agents:** after the block A gate is green, the channel keeps the media id, the enricher reads those bytes, and `MODEL=spark` installs that enricher. They may edit the chat page only to send every selected file. They do not edit `quotedesk/domain/`, `seeds/`, `tests/unit/`, or the block A tests.

**Done when:** a caption, a separate text, one photo, and several photos each produce one extraction row per image and the plain text stays on the message. A stated 5000 L replacement on a level base, with a photo Spark calls a tank and SAM masks as a tank, still issues `R 4 250.00` under WATER-F01. A photo-inferred size, a blur, a SAM failure, or an object SAM does not mask does not. The prompt contains the summaries and does not contain the bytes, a unit price, or a mask score. `pytest` and `lint-imports` are green. The typed-turn tests and the recorded-photo tests are not weakened.

**Out of scope:** Voice Transcribe, video frame extraction, a live WhatsApp media download, `assess_media` as a model tool, the operator console, the policy editor, Excel column labelling, a FrameWorks thread, live PayFast, Wonder, Afrikaans switched on, and any change to `price`. The visit fee is still not a deposit. The console and the editor stay handed off.

## Confirm decisions, before the design

Overturn one in this file, in writing, before the design. After that they are the rules.

- [x] The running model is `spark`. This slice does not install `QuoteScript` or `RecordedEnricher`. A turn test uses a fake enricher and does not open a socket. An adapter test injects the transport and does not call `api.meta.ai`. A key in the diff still fails the evening gate.
- [x] D4 stays. A litre read from a photo is not `customer_stated`. `photo_inferred` alone still fails `measurement_acceptable`. A fixed quote still needs the customer to state the size, in the caption or in a text message.
- [x] Agreement uses every image in the last 20 messages, not only the quiet-window batch. A photo, then "how much?" after the window, still uses that photo's objects and masks. No image in those 20 still passes, which is why a typed turn with no enricher stays green. The threshold stays `Decimal("0.80")`.
- [x] The enricher is not a tool the model can call. The turn calls it before the model speaks. `update_case`, `get_quote`, `request_change`, and `check_availability` stay the only dispatched names.
- [x] One Spark read per image, then SAM on the same bytes. The Spark result is the summary, the object names, and the usability flags. SAM supplies the masks. The existing parser turns SAM's text into masks. A SAM failure keeps the summary in the prompt, sets agreement false, and adds no new customer sentence.
- [x] The same photo is read once. A later turn uses the stored result. The bytes are not put in the prompt, the case, or the outbox. The summary is not sent as its own outbox row. The model writes the customer reply, and `check_reply` still blocks a price, a date, an inclusion, or a guarantee that no tool returned.
- [x] A caption is the image message body. A separate text is its own message. Several images are several messages, one extraction each. The file picker may send them in one action. The caption is attached to the first image. The quiet window is unchanged, so a burst is one turn.
- [x] The live size gate allows `image/jpeg` and `image/png` up to 5 MiB, which is the size the channel will now measure. An empty file is refused. `image/webp` is refused with the existing file sentence. The 100-byte cap is not the live image limit.
- [x] A claimed approval in a caption is still the inbound gate. A claimed approval inside a Spark summary is data in the prompt. It does not grant a discount and it does not change the quote.

`Outcome` stays `fixed_offer`, `indicative_range`, `site_assessment`, `escalation`. `GetQuote` still does not call `schedule`. The video sentence stays `Got your video, having a look.`

## What the combinations must do

| What arrives | What the thread holds | What the model is shown | What a quote may use |
| --- | --- | --- | --- |
| One image, no caption | An image message with an empty body | That image's summary and object names | Masks and flags from that image. No litres unless the customer states them later. |
| One image plus a caption | The caption is the message body | The caption and that image's extraction | The caption is customer text. A size in the caption may be `customer_stated`. A size that appears only in the summary may not. |
| Text, then an image, inside one quiet window | Both messages, in arrival order | Both bodies, and one extraction for the image | Same rule. The text and the photo are one turn. |
| Image, then text, after the window | Two turns. The photo stays on the trail | The later prompt still has the photo's extraction | Agreement on the later turn still uses that photo. |
| Several images, with or without a caption on the first | One message per image | One extraction row per image, tied to its message id | Objects and masks are the union. One blur, one SAM failure, or one unnamed object fails the fixed quote. The reply can still ask which photo they mean. |

The customer-facing reply comes from the model. A photo of a tank and a caption that states 5000 L on a level base can become the WATER-F01 sentence, with the amount only from `get_quote`. A photo the summary cannot read, or a photo that disagrees with the text, becomes a question, not a price.

## Design to create

A test starts only after this file is ticked.

### [design/image-context.md](design/image-context.md)

- [x] Purpose: each image on the channel is described once, that description stays on the conversation, and the reply and the quote use it together with the plain text.
- [x] Module paths recorded. `quotedesk/application/dto/inbound.py` gains `media_id`. `quotedesk/application/ports/media.py` keeps `for_image(provider_message_id)` and gains the host the adapter uses to load bytes. The turn stays free of pixels. The webhook and `quotedesk/adapters/inbound/http/chat.py` keep the media id. The enricher lives in `quotedesk/adapters/outbound/models/`. `install` constructs it for the running app.
- [x] The webhook copies `image.id` onto `media_id` and sets `size_bytes` from the hosted object. The caption stays the body. A missing image id is still stored. The enricher then returns no result, and agreement fails for that image.
- [x] The host is the simulator's media store. `get(media_id)` returns the mime and the bytes, or nothing. A later WhatsApp download fills the same store. This slice does not call the Graph media URL.
- [x] Spark extraction is one Responses call per image. The body is the bytes and the caption. The parsed object is `summary`, `objects`, `blur`, `darkness`, `wrong_subject`. It has no `size_litres`, no `unit_price`, and no `outcome`. The adapter drops those keys if the model sends them.
- [x] SAM is a second Responses call on the same bytes. The prompt is the object names from that image. `parse_sam_response` is unchanged. `SamFailure` becomes `sam_error` with the sentence already in the parser. Masks become `RecordedMask` values. Scores stay `Decimal`.
- [x] The result is cached on the provider message id. `for_image` of an id already read does not post again. The turn attaches that id on the event with `attach(extraction_id=...)` and saves the conversation. The event body stays the caption.
- [x] The prompt's `extractions` are one row per image in the last 20 messages: provider message id, summary, object names. No score, no unit price, no bytes. A text message adds no row. An image with no result adds no row.
- [x] Before `get_quote`, agreement and `media_is_usable` see those same images. Union of objects, union of masks, `sam_error` if any result failed, usability OR of the flags. A text-only last 20 still calls `media_is_usable` with `has_media` false.
- [x] The task gains three sentences, and keeps the rule that a price comes from `tool_payloads`: "Use each extraction with the message it names. When the photo and the customer disagree, ask one question. A size that appears only in an extraction is not `customer_stated`."
- [x] WATER-F01 is unchanged. High confidence, a replacement, `size_litres` 5000, `size_source` `customer_stated`, `existing_level_base` true, and `item_codes` including `TANK-5000`. The photo can make agreement and media true. It cannot supply the litres.
- [x] `photo_inferred`, blur, a SAM error, empty masks, and an object with no matching mask each leave WATER-F01 unmatched. The outbox is the WATER-L02 template when that is the failed check. It contains no rand amount.
- [x] A test of the turn does not open a socket. The adapter test does not call `api.meta.ai` or Baseten. The transport is injected.

## Tests to create

Tests are written failing, against the design. They do not contain the implementation. They do not weaken `tests/use_cases/test_typed_turn.py`, `tests/use_cases/test_photo_turn.py`, or `tests/use_cases/test_run_agent_turn.py`.

### Block A

#### `tests/use_cases/test_image_context.py`

The photo-turn harness. `GetQuote` is the real use case. The enricher is a fake. No socket. No pixels.

- [x] `test_caption_stays_on_the_message_and_the_summary_is_separate` — one image, body `By the gate`, summary `A tank on a level base.`, object `tank`. The prompt message body is the caption. `extractions` has the summary and `tank`. The prompt dump contains neither the byte marker nor `0.91` nor `4250`.
- [x] `test_two_images_are_two_rows` — two images in one batch. The fake returns `tank` for the first and `pump` for the second. The prompt has two rows, in message order. Agreement sees both names. A mask only for `tank` leaves agreement false and the outbox is the site-visit template.
- [x] `test_a_later_text_still_sees_the_photo` — an image turn is closed, then a text turn asks for a price and states 5000 L on a level base. The second prompt still has the image summary. The fake is not called again for that id. Agreement uses the stored tank mask. The outbox is the WATER-F01 card sentence.
- [x] `test_caption_size_can_be_customer_stated` — the image body is `5000 litre, the base is level`, and the script records `size_source` `customer_stated`. With a clean tank extraction this issues `4250.00`.
- [x] `test_a_size_only_in_the_summary_does_not_issue` — the summary mentions 5000 L, the customer did not, and the script writes `size_source` `photo_inferred`. The outbox is the site-visit template. No rand amount.
- [x] `test_blur_or_sam_error_does_not_issue` — the stated-size facts, once with `blur` true and once with `sam_error`. Each outbox is the site-visit template. The summary is still on `extractions`.

#### Block A gate

- [x] A stated size plus a masked tank still issues `4250.00`.
- [x] A second unmatched object, a blur, a SAM error, and a photo-inferred size each produce a site visit and no amount.
- [x] A later text turn still shows the earlier summary and does not call the enricher again.
- [x] `pytest tests/use_cases/test_image_context.py tests/use_cases/test_photo_turn.py tests/use_cases/test_typed_turn.py -q` passes.
- [x] `lint-imports` passes.
- [x] Block B does not start while this gate is red.

### Block B

#### `tests/adapters/test_image_enricher.py`

The transport is `post(url, body) -> dict`. It records the call. It does not open a socket.

- [x] `test_webhook_keeps_the_media_id_and_the_size` — a Cloud API image message with `image.id`, a jpeg mime, and a caption. The stored inbound has that `media_id`, the caption as the body, and `size_bytes` from the hosted object. A following text message has no `media_id`.
- [x] `test_a_real_jpeg_is_accepted_and_webp_is_refused` — a jpeg under 5 MiB is stored. An empty body is refused. `image/webp` is refused with the existing file sentence.
- [x] `test_spark_extraction_reads_the_bytes_once` — the host returns a tiny jpeg for that media id. The first `for_image` posts one extraction request whose body contains the caption and does not contain a unit price. The parsed result is the summary and the objects from the recorded JSON. The second `for_image` for the same id does not post.
- [x] `test_sam_failure_keeps_the_summary` — the SAM post raises the recorded failure. `sam_error` is true, the masks are empty, and the summary is the Spark summary.
- [x] `test_install_uses_spark_for_images` — `MODEL=spark` installs `SparkTurn` and the image enricher. This test does not call `api.meta.ai`.

#### `tests/adapters/test_chat_images.py`

The page posts one webhook message per selected file.

- [x] `test_several_files_are_several_messages` — two files and a caption. The first webhook message is an image with that caption and its media id. The second is an image with an empty caption and its own media id. Both ids can be read back from `/sim/media`.

#### Block B gate

- [x] `pytest tests/adapters/test_image_enricher.py tests/adapters/test_chat_images.py tests/use_cases/test_image_context.py -q` passes.
- [x] `lint-imports` passes.
- [x] The domain tests are unchanged.

## Build

### You, block A — the trail

Implement only what the block A tests describe.

- [x] `media_id` on the inbound message, with a default of absent so today's constructors still build.
- [x] Last-20 extractions, the attach-and-save of `extraction_id`, and agreement from those stored results.
- [x] The three task sentences.
- [x] The block A gate is green.

### Agents, after the block A gate — the bytes

```text
Slice: image context from the channel
Design: docs/build/2026-11-04/design/image-context.md
Tests: tests/adapters/test_image_enricher.py, tests/adapters/test_chat_images.py. Do not edit them. Do not weaken an assertion.
You may edit: quotedesk/adapters/inbound/http/whatsapp.py, quotedesk/adapters/inbound/http/chat.py, quotedesk/adapters/inbound/http/templates/chat.html, quotedesk/adapters/outbound/models/, quotedesk/infrastructure/demo.py, quotedesk/infrastructure/container.py
You must not edit: quotedesk/domain, quotedesk/application/ports, quotedesk/application/dto, seeds, tests/unit, tests/use_cases
Done when: the running app describes each hosted image once, and two selected files become two messages.
Out of scope: voice, video frames, a Graph media download, the console, the editor.
```

- [ ] Handoff sent.
- [x] The media id is kept, the size gate matches the decision, and the enricher posts once per image.
- [x] The running app installs that enricher with `SparkTurn`.
- [x] The block B gate is green.

## Evening gate

Repair only inside this list. No new artifact. Run this after block B is green. The process is `MODEL=spark`.

- [x] `pytest -q` passes, apart from the two PostgreSQL tests when that database is down.
- [x] `lint-imports` passes.
- [ ] Open `/chat`. Send `seeds/media/tank-on-base.png` with the caption that it is a 5000 L tank on the existing level base. One reply. The only amount is `R 4 250.00`. The card opens, headline "Fixed quote", rule WATER-F01. The log has one extraction for that message, and the caption is the message body.
- [ ] Reset. Send the same photo with no size in the caption and no following text. The reply contains no rand amount. It asks about the size or says the photo was not enough to price.
- [ ] Reset. Send two photos in one action, then the 5000 L words as a text. The log has two extractions. The reply's only amount, if it quotes, is `R 4 250.00`.
- [x] `.env` is untracked. The key is not in the diff.
- [x] Slip list below is filled if anything is still red.

## Slip list

Write one line per red item: id, failing check, and where it moves. A red image quote stays here. Voice does not start while this gate is red.

- [x] Slip list reviewed. Empty is fine.

| Item | Failing check | Moves to |
| --- | --- | --- |
| Live caption quote | A 5000 L level-base caption on the tank photo got a reply and `update_case`, and no `get_quote`. The page showed no amount. | Stays on this evening gate. Voice does not start. |
