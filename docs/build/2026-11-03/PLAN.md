# Photo on the typed quote

The typed turn is built. A photo that arrives today is stored as an image, and the turn then calls `cross_model_agreement` with empty masks, so agreement fails and WATER-F01 cannot match. This slice gives that photo a recorded extraction and the recorded SAM result. The model still does not set the price.

The week plan is [QuoteDesk_Build_Plan.md](../QuoteDesk_Build_Plan.md). The typed-turn list is [2026-11-02/PLAN.md](../2026-11-02/PLAN.md). The design for this slice goes in [design/](design/) before any test. Tick a box only when that item is actually done.

**You:** block A. The prompt shows the extraction summary, and the confidence write uses the recorded objects, masks, and usability flags. You own `quotedesk/application/dto/` and `quotedesk/application/ports/` for this slice. You do not reopen `decide`, `price`, `select_clauses`, `derive_confidence`, `cross_model_agreement`, `measurement_acceptable`, `media_is_usable`, `GetQuote`, `RequestChange`, `CheckAvailability`, `UpdateCase`, or `check_reply`.

**Agents:** after the block A gate is green, the recorded enricher and the wiring in `install`. They do not edit `quotedesk/domain/`, `quotedesk/application/ports/`, `quotedesk/application/dto/`, `seeds/`, `tests/unit/`, `tests/use_cases/`, `quotedesk/adapters/inbound/http/templates/chat.html`, or `quotedesk/adapters/inbound/http/chat.py`.

**Done when:** the typed 5000 L replacement, sent with `seeds/media/tank-on-base.png`, still issues one quote at `R 4 250.00` under WATER-F01. A photo-inferred size, a blur flag, or the SAM error fixture does not. The prompt contains the summary and does not contain the bytes, a unit price, or a mask score. `pytest` and `lint-imports` are green. The typed-turn tests are not weakened.

**Out of scope:** Voice Transcribe, live Spark extraction, live SAM, video enrichment beyond the sentence already sent, `assess_media` as a model tool, the operator console, the policy editor, Excel column labelling, a FrameWorks thread, live WhatsApp delivery, live PayFast, Wonder, Afrikaans switched on, and any change to `price`. The visit fee is still not a deposit. The console and the editor are handed off in [../2026-11-01/design/console-editor-handoff.md](../2026-11-01/design/console-editor-handoff.md).

## Confirm decisions, before the design

Overturn one in this file, in writing, before the design. After that they are the rules.

- [ ] This slice does not start while the typed-turn evening gate is red. A failing scripted reply, a failing live Spark reply, or a key in the diff stays on [2026-11-02/PLAN.md](../2026-11-02/PLAN.md).
- [ ] D3 changes only when the closed batch contains an image. Agreement then uses the recorded Spark object names and the recorded SAM masks, threshold `Decimal("0.80")`. No image and no video still passes, which is why the typed-turn tests stay green. Saturday's turn still has no catalog, so it still does not write the five facts.
- [ ] D4 stays. `photo_inferred` alone fails `measurement_acceptable`. The litres on a fixed quote are still `customer_stated`. This slice has no reference object.
- [ ] The enricher is not a tool the model can call. `update_case`, `get_quote`, `request_change`, and `check_availability` stay the only dispatched names. The model may still write `job`, `size_litres`, `size_source`, `existing_level_base`, and `item_codes`. It may not write `required_fields`, `agreement`, `measurement`, `media_usable`, `rate_card`, `unit_price`, `outcome`, or `clause_text`.
- [ ] A missing enrichment is the SAM-outage path already in `cross_model_agreement`: `has_image` true, no masks, agreement false. The turn still runs. There is no new customer sentence. One failed check is medium confidence, WATER-F01 does not match, and the matched rule is WATER-L02.
- [ ] Usability flags come from the recorded extraction. `media_is_usable` is called with `has_media` true when the batch contains an image. Blur, darkness, or wrong subject fails that check. A clean photo passes. A text-only batch still calls it with `has_media` false. The flags are not put in the prompt.
- [ ] The prompt gains `extractions`, defaulting to empty, so a Saturday or typed-turn constructor still builds. One row per enriched image in the last 20 messages: provider message id, summary, object names. No score, no unit price. The image message body stays the stored caption. Bytes are not copied in.

`Outcome` stays `fixed_offer`, `indicative_range`, `site_assessment`, `escalation`. `Decision` still has no amount. `GetQuote` still does not call `schedule`. The video sentence stays `Got your video, having a look.`

## Design to create

A test starts only after this file is ticked.

### [design/photo-turn.md](design/photo-turn.md)

- [ ] Purpose: a photo in the closed batch is enriched from a recording, the prompt shows the summary, and the five confidence facts are still written by the turn.
- [ ] Module paths recorded: `quotedesk/application/dto/agent.py` for the prompt row, `quotedesk/application/ports/` for the enricher port, `quotedesk/application/use_cases/conversation/run_agent_turn.py` for the confidence write, `quotedesk/adapters/outbound/models/` for the recorded enricher. The adapter is block B. The design records the path so the test file name is stable.
- [ ] The enricher port returns the summary, the object names, the usability flags, and either the parsed SAM masks or the SAM failure. The turn does not import `sam_parser`. The adapter may.
- [ ] The recording for the tank photo is named. The summary is `A tank on a level base.` The object name is `tank`. The masks are `tests/fixtures/sam/tank_success.json`: label `tank`, score `0.91`. Blur, darkness, and wrong subject are false. The pixels stay in `seeds/media/tank-on-base.png`. The test does not need the pixels.
- [ ] `tests/fixtures/sam/error.json` is the failure recording. `tests/fixtures/sam/no_mask.json` is the empty-mask recording. Both are already parsed by `parse_sam_response`. This slice does not change that parser.
- [ ] A blur recording is named. Same summary and same masks, `blur` true. That is enough to fail `media_is_usable` while agreement still passes.
- [ ] `RunAgentTurn` gains a keyword-only `enricher` defaulting to absent. Absent means today's inputs: no objects, no masks, `sam_error` false, `has_media` false. The typed-turn constructor still builds.
- [ ] Immediately before `get_quote`, and only when catalog and policies are present and the case has a job, the turn writes the same five facts. For an image in the batch it passes the enricher's objects, masks, and `sam_error` into `cross_model_agreement`, and the enricher's flags into `media_is_usable`. The stored values are still `true` and `false`. The source is still `customer_text`. The event id is still the last event in the batch.
- [ ] The prompt's `extractions` rows are built from that same result. A text batch has none. An image with no result has none, and agreement fails as in the decision above.
- [ ] WATER-F01 still requires high confidence, a replacement, `size_litres` 5000, `size_source` `customer_stated`, `existing_level_base` true, and `item_codes` including `TANK-5000`. The clean photo plus those facts issues `4250.00`. The reply is the typed-turn sentence, including the card link.
- [ ] `photo_inferred`, blur, a SAM error, and empty masks each leave WATER-F01 unmatched. The outbox is the WATER-L02 template. It contains no rand amount. The card link is not set, because the outcome is a site visit.
- [ ] The model port stays `AgentModel.complete(prompt) -> ModelReply`. A test of the turn does not open a socket. The adapter test does not call `api.meta.ai` or Baseten.

## Tests to create

Tests are written failing, against the design. They do not contain the implementation. They do not weaken `tests/use_cases/test_typed_turn.py` or `tests/use_cases/test_run_agent_turn.py`.

### Block A

#### `tests/use_cases/test_photo_turn.py`

The typed-turn harness. `GetQuote` is the real use case. The enricher is a fake that returns the recording named in each test. No socket. No pixels.

- [ ] `test_clean_photo_keeps_water_f01` — the WATER-F01 message, plus one image in the same batch. The enricher returns summary `A tank on a level base.`, object `tank`, the tank mask at `0.91`, and no usability flag. The script's `update_case` includes `agreement=true`. That key is not stored from the model. The prompt's `extractions` contain the summary and the name `tank`, and do not contain `4250` or `0.91`. The second payload is rule `WATER-F01`, outcome `fixed_offer`, total `4250.00`. The outbox is the typed-turn card sentence. The case's current `agreement` is `true`, written by the turn.
- [ ] `test_photo_inferred_size_does_not_issue_a_fixed_price` — the same photo and the same clean recording. The script writes `size_litres` `5000` and `size_source` `photo_inferred`, with the level base and `TANK-5000`. The outbox is `We don't have a standard price for this job. A site visit is the next step.` No rand amount is in the outbox.
- [ ] `test_blur_does_not_issue_a_fixed_price` — the stated-size facts from the WATER-F01 test, and the same masks, with `blur` true. The case's current `media_usable` is `false`. The outbox is the WATER-L02 template. No rand amount is in the outbox.
- [ ] `test_sam_error_does_not_issue_a_fixed_price` — the stated-size facts, and the error recording. The case's current `agreement` is `false`. The outbox is the WATER-L02 template. No rand amount is in the outbox.
- [ ] `test_image_bytes_are_not_in_the_prompt` — the image event's stored body is a caption. The prompt message body is that caption. The extraction summary is on `extractions`. The prompt does not contain the photo's bytes.

#### Block A gate

- [ ] The clean photo still issues `4250.00` from the stated size.
- [ ] A photo-inferred size, a blur, and a SAM error each produce a site visit and no amount.
- [ ] `pytest tests/use_cases/test_photo_turn.py tests/use_cases/test_typed_turn.py tests/use_cases/test_run_agent_turn.py -q` passes.
- [ ] `lint-imports` passes.
- [ ] Block B does not start while this gate is red.

### Block B

#### `tests/adapters/test_recorded_extraction.py`

The adapter reads the files named in the design. The transport is not a network client.

- [ ] `test_tank_photo_reads_the_recorded_files` — the tank photo's recording returns the summary, the object `tank`, a mask score of `Decimal("0.91")`, and no usability flag. No socket is opened.
- [ ] `test_sam_error_fixture_is_a_failure` — `tests/fixtures/sam/error.json` is returned as the SAM failure, with the sentence already in that file.
- [ ] `test_install_uses_the_recorded_enricher` — `MODEL=script` still installs `QuoteScript`. The turn used by the app has the recorded enricher. `MODEL=spark` still selects `SparkTurn` and does not call `api.meta.ai` from this test.

#### Block B gate

- [ ] `pytest tests/adapters/test_recorded_extraction.py tests/use_cases/test_photo_turn.py -q` passes.
- [ ] `lint-imports` passes.
- [ ] The chat files are unchanged.

## Build

### You, block A — the turn

Implement only what the block A tests describe.

- [ ] `extractions` on `TurnPrompt`, with a default.
- [ ] The keyword-only enricher, and the five checks written from its result before `get_quote`.
- [ ] The block A gate is green.

### Agents, after the block A gate — the recording

```text
Slice: recorded photo enrichment
Design: docs/build/2026-11-03/design/photo-turn.md
Tests: tests/adapters/test_recorded_extraction.py. Do not edit them. Do not weaken an assertion.
You may edit: quotedesk/adapters/outbound/models/, quotedesk/infrastructure/demo.py, quotedesk/infrastructure/container.py
You must not edit: quotedesk/domain, quotedesk/application/ports, quotedesk/application/dto, seeds, tests/unit, tests/use_cases, quotedesk/adapters/inbound/http/templates/chat.html, quotedesk/adapters/inbound/http/chat.py
Done when: the app's turn uses the recorded enricher, the tank fixture returns the tank mask, and the chat page is unchanged.
Out of scope: live media, voice, video enrichment, the console, the editor, and any change to the chat page.
```

- [ ] Handoff sent.
- [ ] The recorded enricher is what `install` passes.
- [ ] The block B gate is green.

## Evening gate

Repair only inside this list. No new artifact. Run this only after the typed-turn evening gate is green.

- [ ] `pytest -q` passes, apart from the two PostgreSQL tests when that database is down.
- [ ] `lint-imports` passes.
- [ ] `MODEL=script`. Open `/chat`. Send the 5000 L replacement and attach `seeds/media/tank-on-base.png`. The reply's only amount is `R 4 250.00`. The card opens, headline "Fixed quote", rule WATER-F01.
- [ ] Same thread, after a reset. Send the same words with `size` left unstated and only the photo attached. The reply is the site-visit template. It contains no rand amount.
- [ ] `.env` is untracked. The key is not in the diff.
- [ ] Slip list below is filled if anything is still red.

## Slip list

Write one line per red item: id, failing check, and where it moves. A red photo quote stays here. Voice is the following slice. It does not start while this gate is red.

- [ ] Slip list reviewed. Empty is fine.

| Item | Failing check | Moves to |
| --- | --- | --- |
| | | |
