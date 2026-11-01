# Swap and new installation

Written 31 October 2026. A swap and a new installation share the material price. The stand, the frame, and the labour are separate rate-card rows, added when that infrastructure is not already there. The quote engine and the owner console land in one sequence. Each increment leaves quoting working.

The production plan records the five gates in [PLAN.md](PLAN.md). This file is the working checklist. Tick a box only when that item is actually done. A design box is ticked when the design file exists. A test box is ticked when the test fails for the reason the design names, or passes once the slice is implemented. A gate box is ticked when that behavior has been seen, not when the code looks finished. The next increment waits until the current gate is green.

`pytest` and `lint-imports` are green at every gate. Do not weaken `tests/unit/domain/test_price.py`, `tests/use_cases/test_get_quote.py`, `tests/use_cases/test_publish_policy.py`, `tests/eval/test_gate.py`, or `tests/adapters/test_console.py` to absorb a slice.

## Confirm decisions, before increment 1

Overturn one by editing it here, in writing, before any test for the increment it governs. After the box is ticked, it is the rule.

- [x] The tank and the sheet stay one row each. `applies_to` is `both`, `swap`, or `new`. A code such as `TANK-5000-SWAP` is not how the two prices are split.
- [x] Every row that exists today is `both`. The built-in AquaSure and FrameWorks cards gain no stand, frame, or labour price in this build. The owner types those amounts in the console and publishes them.
- [x] A swap quotes the material. It also quotes a labour row whose `applies_to` is `swap`, when that row is on the published card. A new installation quotes the material plus the `frame` and `installation` rows whose `applies_to` is `new`.
- [x] A range spans the product choices. Shared infrastructure is added to both ends. The range is not the cheapest line against the dearest line once a frame or a labour row is in the quote.
- [x] `replacement` and an existing opening are a swap. `new_system` and a new opening on the ground, one opening, are a new installation. Ask whether the stand or the frame is already there only when the case has not already said which.
- [x] A widened opening, work above the ground floor, more than one opening, a damaged stand, a borehole, a slope, and an unknown pipe run stay a site measure. `FAB-S01` matches a widened opening. It no longer matches a plain new opening.
- [x] A new installation whose card has no matching infrastructure row quotes the material only. The customer sentence lists the lines on the quote. It does not mention a stand or a frame that was not priced.
- [x] At most one non-product row for each role and each `applies_to`. Two installation rows both marked `new` do not publish.
- [x] Quotes already sent keep the lines they were issued with. Oakmere Doors stays unserved: no prices, no tenant, no number.
- [x] The document pass is the last increment. It describes the code and the green tests. It does not describe a step that was cut.

## Increment 1 — the price engine

The domain can price the split. No playbook question changes, and no demo price changes. A card that only has tanks or sheets still quotes those amounts.

### Design

Write this before the tests.

- [x] [design/applies-to-price.md](design/applies-to-price.md) states the purpose: one material price, infrastructure rows selected by `applies_to`, a range that adds shared lines to both ends.
- [x] Module paths recorded. `quotedesk/domain/services/price.py` gains `applies_to` on `RateCardItem`, default `both`, and `work` on `PriceFacts` (`swap` or `new`). `quotedesk/domain/policy/draft.py` gains the same field on `DraftRateRow`, default `both`. `quotedesk/application/use_cases/editor/publish_policy.py` copies it onto the published item. `quotedesk/application/use_cases/tools/get_quote.py` does not yet choose `work`. That is increment 3.
- [x] `_composed` adds a role row when `applies_to` is `both` or equals `work`. Product rows stay the chosen item codes. A missing infrastructure row adds nothing.
- [x] An indicative range prices each product choice, then adds the extended price of the shared role rows to both ends. A fixed offer still sums every composed line. The deposit on a fixed quote is the percent of that sum. The deposit on a range stays the percent of the low end.
- [x] A second non-product row with the same role and the same `applies_to` is a policy error, sentence included, raised from `validate_policy` when the draft is checked. `price()` is not the place that sentence is shown to the owner.
- [x] The 29 October price fixture is unchanged: `TANK-5000` at `4250.00`, and a range over two coverings still uses those unit prices when no role row is requested.

### Tests

Written failing, against the design.

#### `tests/unit/domain/test_price.py`

- [x] `test_a_swap_prices_the_material_and_leaves_out_new_lines` — card has `TANK-5000` (`both`, product), `STAND` (`new`, frame), and `FIT-NEW` (`new`, installation). `work` is `swap`. The fixed lines are `TANK-5000` only.
- [x] `test_a_new_installation_adds_the_frame_and_the_new_labour` — the same card, `work` `new`. The lines are the tank, the stand, and the new labour, and the total is their sum.
- [x] `test_a_swap_adds_swap_labour_when_that_row_exists` — the card also has `FIT-SWAP` (`swap`, installation). A swap has the tank and `FIT-SWAP`. It does not have `STAND` or `FIT-NEW`.
- [x] `test_a_range_adds_the_shared_lines_to_both_ends` — two sheets, `per m²`, width 5, length 7, plus one `new` frame row priced per m². `work` is `new`. `range_min` is the cheaper sheet area plus the frame area. `range_max` is the dearer sheet area plus the same frame area. `lines` stays empty.
- [x] `test_a_card_with_only_products_prices_as_before` — no role rows, `work` `new`. The tank total is the tank price.

#### `tests/use_cases/test_publish_policy.py`

- [x] `test_publish_keeps_applies_to` — a draft row with `applies_to` `new` and role `frame` publishes as that role and that `applies_to`. A row that omits the field publishes as `both`.

### Functionality

- [x] `RateCardItem.applies_to` and `DraftRateRow.applies_to` exist, default `both`. Existing constructors and the demo cards in `quotedesk/infrastructure/demo.py` still build.
- [x] `price()` implements the filter and the range rule above. `get_quote` still passes today's roles. AquaSure has none, and FrameWorks lists `product`, so a customer quote does not change in this increment.
- [x] `validate_policy` rejects two non-product rows that share a role and an `applies_to`, with a sentence the console can list. It accepts one `swap` installation row and one `new` installation row.

Increment 1 gate:

- [x] The five price tests and the publish test pass.
- [x] The existing price tests and `tests/use_cases/test_get_quote.py` pass without edited expectations.
- [x] `pytest tests/unit/domain/test_price.py tests/use_cases/test_publish_policy.py tests/use_cases/test_get_quote.py -q` and `lint-imports` are green. Seen: 48 passed. `lint-imports` kept 4 contracts.

## Increment 2 — the console and the stored card

The owner can see and edit the unit, the role, and when the row applies. Publishing writes `applies_to`. A customer quote still does not change, because the built-in cards have no infrastructure rows and the playbook does not ask yet.

### Tests

#### `tests/adapters/test_console.py`

The TestClient drives the page. No socket.

- [x] `test_the_draft_shows_unit_role_and_applies_to` — `GET /console` shows the unit, the role, and when the row applies, for each live row and each draft row. They are not only hidden inputs.
- [x] `test_publishing_a_stand_shows_it_on_the_live_card` — post a new row, code `STAND`, a rand amount, unit `each`, role `frame`, applies to `new`, with a reason. The live list shows that code, the role, and that it applies to a new installation. A quote issued before the post still has its old lines.
- [x] `test_two_new_installation_rows_of_one_role_are_not_published` — two `installation` rows both marked `new`. The page lists the validation sentence. `published()` is unchanged.

#### `tests/adapters/test_rate_card_tables.py`

- [x] `test_applies_to_round_trips` — save a card with one `new` frame row and one `both` product row, read it back, and get those values. A row saved before the column existed reads as `both`.

#### `tests/use_cases/test_import_rate_card.py`

- [x] `test_a_sheet_without_applies_to_stores_both` — an Excel row that has a code, a price, and a unit, and no applies-to column, becomes a draft row with `applies_to` `both`.

### Functionality

- [x] Alembic adds `rate_card_item.applies_to`, `text`, not null, default `both`. The revision follows the current head. `quotedesk/adapters/outbound/persistence/rate_cards.py` reads and writes the column.
- [x] `quotedesk/adapters/inbound/http/templates/console.html` shows Unit, Role, and Applies to on the draft table and on the live rate card. The blank row defaults to unit `each`, role `product`, applies to `both`.
- [x] `quotedesk/adapters/inbound/http/editor.py` accepts `applies-to-<n>` beside `unit` and `role`. An unknown value is the same class of draft error as a bad price: the draft is left alone and the sentence is listed.
- [x] The live list names the row in the owner's words: product, frame, or installation, and both, a swap, or a new installation. The price stays the rand format already on the page.
- [x] Import copies an applies-to cell when the sheet has one, and stores `both` when it does not.

Increment 2 gate:

- [x] The console tests, the table test, and the import test pass.
- [x] In the browser, on `/console#policy`: the draft shows the three fields; adding a stand, checking the draft, and publishing shows that row on Live now; a second new-installation labour row stays unpublished and the sentence is on the page. Quotes already on the page are unchanged.
- [x] `pytest tests/adapters/test_console.py tests/adapters/test_rate_card_tables.py tests/use_cases/test_import_rate_card.py tests/use_cases/test_publish_policy.py -q` and `lint-imports` are green. The table test may skip when Postgres is down. Say so on the gate line if it skipped. Seen: 61 passed, including the editor tests. The table test ran. `lint-imports` kept 4 contracts.

## Increment 3 — ask, and price the work the customer named

The case decides `swap` or `new`. The rules that treat every new opening as a visit, and every sized tank as the same range, change here. The release set changes with them.

### Tests

#### `tests/unit/domain/test_plan_next_step.py`

- [x] `test_a_named_swap_does_not_ask_about_the_stand` — job `replacement`. The next ask is the tank size, not the stand.
- [x] `test_an_unnamed_tank_job_asks_whether_the_stand_is_there` — no replacement and no `new_system`. The question is whether the stand is already there.
- [x] `test_a_new_carport_asks_the_sheet_before_the_size` — opening `new`, sheet missing. The ask is the sheet. It is not a site measure.
- [x] `test_a_widened_opening_is_still_a_site_measure` — opening `widened`. The step is the inspection, and the sentence has no total.

#### `tests/unit/domain/test_frameworks_decide.py` and the AquaSure decide tests

- [x] `test_a_new_opening_with_a_sheet_and_a_size_is_a_fixed_quote` — opening `new`, width, length, and a chosen sheet. The outcome is `fixed_offer`. The rule is the new fixed rule, not `FAB-S01`.
- [x] `test_a_widened_opening_is_a_site_measure` — `FAB-S01` still matches `widened`.
- [x] `test_a_new_tank_of_a_known_size_is_a_fixed_quote` — `new_system`, size one of 2500, 5000, 10000. The outcome is `fixed_offer`. `WATER-F01` still wins for a replacement of the same size.
- [x] `test_an_unchosen_sheet_on_a_new_carport_stays_a_range` — opening `new`, width and length known, sheet unknown. The outcome is the indicative range.

#### `tests/use_cases/test_get_quote.py`

Use a card that includes the infrastructure rows. Do not put those amounts on the demo cards.

- [x] `test_a_replacement_prices_the_tank_only` — `replacement`, 5000 L. Lines are `TANK-5000`. The stand row is on the card and is not on the quote.
- [x] `test_a_new_system_prices_the_tank_and_the_stand` — `new_system`, 5000 L, stand and new-labour rows on the card. The lines are those three. The total is their sum. The deposit is the published percent of that sum.
- [x] `test_an_existing_opening_prices_the_sheet_only` — opening `existing`, sheet `SHEET-ECO`, width and length set. The frame row is on the card and is not on the quote.
- [x] `test_a_new_carport_prices_the_sheet_and_the_frame` — opening `new`, same size and sheet. The lines include the sheet and the frame.
- [x] `test_a_new_system_without_a_stand_row_prices_the_tank` — `new_system`, 5000 L, card has only tanks. The line is the tank. The result does not invent a stand amount.

#### `tests/eval/test_gate.py`

- [x] The release set still has outcome accuracy 1, rule accuracy 1, and unfounded 0 after the conversations below are updated. A new opening that is a freestanding carport with a known sheet and size expects the new fixed rule. A widened opening still expects `FAB-S01`. A sized replacement still expects `WATER-F01`.

### Functionality

- [x] AquaSure asks "Is the stand already there?" only when the job is neither `replacement` nor `new_system`. FrameWorks asks "Is this sheeting onto the existing frame?" only when `opening` is unset. Both facts decide the price, and both are easy.
- [x] The job roles for a tank job and for `carport` include `frame` and `installation`. `get_quote` sets `work` from the case and passes those roles into `price()`.
- [x] `FAB-S01` matches `widened` only. A new opening on the ground, one opening, with the sheet and the size known, is a fixed offer. Above the ground floor and more than one opening stay `FAB-S02`. Note: that fixed offer is the existing rule `FAB-F02`. This build did not add a new FrameWorks rule id. The new AquaSure rule is `WATER-F02`.
- [x] A known tank size on `new_system` is a fixed offer. `WATER-R02` remains the range when the size is known and the sheet-or-tank choice is not, including a new installation whose size is not one of the three tanks.
- [x] The seeds say this in `guidance`. They do not add prices. `eval/conversations/gate/frameworks.yaml` conversation `frame-new-opening` is retargeted in the same change as `FAB-S01`. Read it before changing the expected outcome.
- [x] The customer sentence for a fixed quote lists each line's description and amount after the total, using the lines `get_quote` returned. A quote with one line reads as it does today, plus that line.

Increment 3 gate:

- [x] A replacement of a 5000 L tank on the demo card is still R 4 250.00 for the tank.
- [x] A new installation on a card that has a stand quotes the tank plus the stand. The same job on the demo card quotes the tank only, and the sentence does not mention a stand.
- [x] A widened opening offers the visit and states no total.
- [x] `python -m eval.run_gate` reports unfounded 0 and accuracy 1 for both businesses.
- [x] `pytest tests/unit/domain tests/use_cases/test_get_quote.py tests/eval/test_gate.py -q` and `lint-imports` are green.

## Increment 4 — the quote shows its lines

The customer card and the owner brief show the same lines the price was built from.

### Tests

#### `tests/adapters/test_quote_card.py` or the existing card test module

Use the module that already renders a card. Add the cases there rather than a second renderer test.

- [x] `test_a_fixed_quote_lists_each_line` — two lines, a tank and a stand. The card shows each description, each line total, and the quote total. Money uses the rand format already on the card.
- [x] `test_a_range_names_the_material_span_and_the_shared_lines` — low and high differ, and a frame amount is included in both. The card shows the two ends and names the frame. It does not present the frame as a third end.

#### The brief

- [x] `test_the_brief_marks_a_swap_and_lists_its_lines` — a replacement quote's brief says it is a swap and lists the tank line.
- [x] `test_the_brief_marks_a_new_installation_and_lists_its_lines` — a new-installation quote's brief says it is a new installation and lists the tank and the stand.

### Functionality

- [x] `quotedesk/adapters/inbound/http/templates/quote_card.html` lists the lines on a fixed quote, then the total. A range names the low and the high, and names any infrastructure included in both ends.
- [x] The owner brief, built in `quotedesk/adapters/inbound/http/console.py` and rendered by `brief.html`, includes those lines and whether the quote is a swap or a new installation.
- [x] The open-case list stays outcome, title, and time. The split is on the brief, not on that list.

Increment 4 gate:

- [x] The card tests and the brief tests pass.
- [x] In the browser: publish a stand on the AquaSure draft; as a customer, complete a swap and see the tank line and the tank total; complete a new installation and see the tank, the stand, and the summed total on the card; open both briefs and see the same lines, one marked swap and one marked new installation. A widened carport still offers the visit and shows no material total.
- [x] `pytest tests/adapters tests/use_cases/test_get_quote.py tests/eval/test_gate.py -q --ignore=tests/adapters/test_quote_tables.py --ignore=tests/adapters/test_rls.py` and `lint-imports` are green.

## Increment 5 — production, architecture, design, and the README

Write this after the four gates above are green. Describe the code that landed. Where a step was cut or a sentence differs from this plan, the document follows the code and the test name, and this plan gets a one-line note of the difference.

### Production

- [x] [PLAN.md](PLAN.md) ticks the five gates in the "Swap and new installation" section. The Order section says this work follows increment 7.
- [x] [design/planner.md](design/planner.md) records the stand question, the frame question, when each is skipped, and that a plain new opening can be a quote while a widened opening stays a visit.
- [x] [design/prompts.md](design/prompts.md) section 10 records what this build changed in the customer sentences and the rules. Sections 5 and 7 match the ask order and the fixed-quote wording that the tests lock.

### Architecture

- [x] [docs/design/QuoteDesk_Clean_Architecture.md](../../design/QuoteDesk_Clean_Architecture.md) describes `price()` as composing the chosen product with the role rows whose `applies_to` matches the work, and a range as the product span plus those shared rows on both ends. The quote flow that says `price()` builds line items or a range uses the same description. `validate_policy` is described as rejecting two non-product rows that share a role and an `applies_to`.

### Design notes that still describe the old behavior

Leave the date and the fixture at the top of each note. Add what the function does now, so a reader does not implement the old rule.

- [x] [docs/build/2026-10-29/design/price.md](../2026-10-29/design/price.md) — `applies_to`, the composer filter, and the range with shared lines on both ends. The original tank fixture stays the no-infrastructure case.
- [x] [docs/build/2026-10-30/design/get-quote.md](../2026-10-30/design/get-quote.md) — `work`, the roles passed into `price()`, and a new installation whose lines include the published infrastructure rows.
- [x] [docs/build/2026-11-01/design/frameworks-decide.md](../2026-11-01/design/frameworks-decide.md) — `FAB-S01` is a widened opening. A new opening with a known sheet and size is the fixed rule this build added.
- [x] [docs/build/2026-10-28/design/aquasure-decide.md](../2026-10-28/design/aquasure-decide.md) — a known size on `new_system` is a fixed offer. The range remains when the size is not one of the three tanks.
- [x] [docs/build/2026-11-01/design/policy-publish.md](../2026-11-01/design/policy-publish.md) — `DraftRateRow.applies_to`, and the sentence for a duplicated role.
- [x] [docs/build/2026-11-01/design/rate-card-import.md](../2026-11-01/design/rate-card-import.md) — a sheet without the column stores `both`.
- [x] [docs/build/2026-11-01/design/console-editor-handoff.md](../2026-11-01/design/console-editor-handoff.md) — one sentence at the top pointing at [design/applies-to-price.md](design/applies-to-price.md) for the rate-card fields the page has now. The handoff body stays the record of that Sunday.

### README

- [x] The Database section names `rate_card_item.applies_to`, default `both`, and says a publish from `/console` writes it.
- [x] "What this build simulates" says the Policy draft shows the unit, the role, and whether the row applies to a swap, a new installation, or both. A swap quotes the material. A new installation adds the published frame and installation rows. The built-in cards have none of those rows, so a new installation on a fresh database is the material price until the owner publishes them.
- [x] The evaluation paragraph and the results table are replaced from a real `python -m eval.run_gate` run done after increment 3. Record that run's date, the conversation counts, and the accuracy figures the command printed. If the counts are still 24 and 24, say so, and name the conversations whose expected outcome changed.

Increment 5 gate:

- [x] A reader of the architecture note, the planner note, and the README can tell a swap from a new installation without reading this plan.
- [x] No document in the list above still says that every new opening is a site measure, or that a new tank and a swap of the same tank are always the same price.
- [x] The README figures match the gate command's output from this build, and the date on that table is the date of that run.

## Order

1, then 2, then 3, then 4, then 5. Increment 1 makes a published infrastructure row safe to store. Increment 2 lets the owner store one. Increment 3 starts adding those rows to a quote. Increment 4 shows the lines. Increment 5 writes the documents from that behavior.

## Out of scope

These are not boxes. They are not work.

- Invented prices for a stand, a frame, or labour, in a seed, a demo card, or a migration.
- A second product code per tank or per sheet.
- Pricing a widened opening, upstairs work, or more than one opening as a new carport.
- Serving Oakmere Doors.
- A reminder scheduler, a live WhatsApp number, or a change to SAM.
