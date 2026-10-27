# Thursday 29 October 2026

A quote that can be issued. This is the working list for the day. Tick a box only when that item is actually done. The week plan is [QuoteDesk_Build_Plan.md](../QuoteDesk_Build_Plan.md). Designs written this morning go in [design/](design/) before any test for that artifact.

Wednesday's slip list has no red test. Nothing on it moves here. Do not reopen `derive_confidence`, `classify_injection_claims`, or AquaSure `decide`.

**You:** 05:30–06:00 confirm D5, D6, D7, and D9. 06:00–08:00 write the designs, then the failing tests, including the printable 5000 L quote. 18:00–22:00 implement DOM-5, DOM-10, and DOM-9.

**Agents, daytime:** the four quote-card fixtures, once the printable quote is committed. A Cloud API text fixture and an outbox shell. They do not edit `quotedesk/domain/`, `quotedesk/application/ports/`, `quotedesk/application/dto/`, `seeds/`, or `tests/`.

**Done when:** `pytest tests/unit/domain -q` and `lint-imports` are green, the printable quote shows one 5000 L line and no float, and you have opened the fixed-offer card and checked the headline, the rand amount, the clause sentences, and the expiry.

**Out of scope today:** `schedule`, the case file, `GetQuote`, FrameWorks `decide`, `validate_policy`, `seeds/aquasure.yaml`, database tables, deposit links, applying a discount, and live WhatsApp.

## Confirm decisions, 05:30–06:00

Re-read these in the week plan. Overturn one there, in writing, before any test. After 06:00 they are the rules.

- [x] D5. One VAT basis for a whole rate card. `price` does not convert. Mixed inclusive and exclusive rows are Sunday's `validate_policy`, not today's function.
- [x] D6. Issuing version n+1 sets version n to `REVISED`. Both versions remain. The new version is the current one.
- [x] D7. A site assessment and an escalation do not carry a deposit. Creating a deposit link is Saturday. A visit fee is not a deposit.
- [x] D9. An approval applies to one version. An approval after `expires_at` does not apply.

`Outcome` stays as Wednesday recorded it: `fixed_offer`, `indicative_range`, `site_assessment`, `escalation`. Do not introduce `a_fixed_offer` or the other letter codes. The week plan's (a) (b) (c) (d) mean those four values, in that order.

`Decision` still has no amount. `price` returns a separate `PricedQuote`.

Proposed shape, confirm or replace in `design/quote.md` before the tests:

The aggregate is `Quote`. `open` starts at `DRAFT` version 1. The caller passes a `QuoteId`, an expiry as a `datetime.date`, and the later `at` instants. The aggregate does not read the clock, the environment, or the network. `issue` sets the state from the outcome. `transition` moves along the table. `revise` appends version n+1 and marks version n `REVISED`. `apply_approval` checks the version and the instant. Patching an issued version raises `PolicyViolation`. A state move off the table raises `InvalidTransition`. A write that names an old version raises `StaleQuote`.

## Design to create

Written 29 October 2026. A test starts only after its design file is ticked. Domain designs come first. The two adapter designs come after them and before the 08:00 handoff.

### [design/quote.md](design/quote.md)

- [ ] Purpose: one quote, many versions. An issued version is not edited in place.
- [ ] States recorded: `DRAFT`, `PENDING_APPROVAL`, `ISSUED`, `SITE_ASSESSMENT_OFFERED`, `ESCALATED`, `WAITING_FOR_DEPOSIT`, `DEPOSIT_PAID`, `BOOKING_CONFIRMED`, `EXPIRED`, `REJECTED`, `REVISED`.
- [ ] The 22 legal pairs from the week plan are listed. `BOOKING_CONFIRMED`, `REJECTED`, `EXPIRED`, and `REVISED` have no outbound pair.
- [ ] Illegal pairs recorded: `ISSUED` to `DRAFT`, `EXPIRED` to `BOOKING_CONFIRMED`, `REJECTED` to `ISSUED`, `ESCALATED` to `ISSUED`.
- [ ] `fixed_offer` and `indicative_range` issue as `ISSUED`. `site_assessment` issues as `SITE_ASSESSMENT_OFFERED`. `escalation` issues as `ESCALATED`.
- [ ] D6 recorded: version 2 current, version 1 `REVISED`, version 1's line items still readable.
- [ ] A line price, a clause, or the expiry on an issued version raises `PolicyViolation` with code `policy.violation` and a non-empty sentence. The stored values stay as they were.
- [ ] An off-table move raises `InvalidTransition` with code `quote.invalid_transition`.
- [ ] A write of version 1 after version 2 exists raises `StaleQuote` with code `quote.stale`. A write of version 2, while it is current, does not.
- [ ] D9 recorded. An approval names `applies_to_version`. Version 1's approval does not apply to version 2. An instant equal to `expires_at` is kept. An instant after `expires_at` raises `PolicyViolation`.
- [ ] The id is a `QuoteId` argument. `QD-1042` is accepted. `QD-1` raises `ValidationError` with code `quote_id.invalid`. The aggregate does not mint an id.
- [ ] Expiry is a civil date the caller passes. A `datetime` is rejected. The type does not call `datetime.now`.

### [design/price.md](design/price.md)

- [ ] Signature recorded: `price(decision, facts, rate_card) -> PricedQuote`.
- [ ] Amounts are `Money`. The function does not read the clock, the environment, or the network.
- [ ] D5 recorded. The fixture rate card is one VAT basis. The unit price on a line is the card's unit price. There is no 15% gross-up and no stripping of VAT.
- [ ] `price_type` is `fixed`, `range`, or `none`.
- [ ] A fixed offer has line items. Total is quantity times unit price, in cents, for `Decimal("1")` and `Decimal("2.5")`.
- [ ] A range has `min` and `max`, both rate-card amounts, and no line items. `min <= max`. One matching item keeps `price_type` `range` and sets `min == max`.
- [ ] A site assessment has `price_type` `none`, a visit fee equal to the settings fee, empty line items, and an empty range. The fee is not a deposit.
- [ ] An escalation has every money field empty. No fee and no deposit. D7.
- [ ] An unknown item code raises `PolicyViolation` with code `policy.violation`. One unknown code, and one known code beside an unknown code, both raise. The error carries no line list.
- [ ] Quantity `0` and a negative quantity raise `PolicyViolation`. No line is returned.
- [ ] A passed-in discount of 10 is ignored. The returned discount is zero.
- [ ] A `fixed_offer` decision whose band is `low` raises `PolicyViolation`. `price` does not repair the decision.

### [design/clauses.md](design/clauses.md)

- [ ] Signature recorded: `select_clauses(decision, facts, job_type, policy) -> ClauseSelection`.
- [ ] The selection carries conditions and the decision's customer template. It does not invent a second safety sentence.
- [ ] Placeholders `{deposit_percent}` and `{validity_days}` are filled from settings. The design records the fixture settings. A missing setting raises `PolicyViolation`. The characters `{deposit_percent}` are never returned.
- [ ] Each selected condition records `clause_id`, `clause_version`, kind, rendered text, and `if_not_true`.
- [ ] Carport facts of only 6.0 m by 7.0 m select CARPORT-A1, A2, A3, A4, A5, A6, CARPORT-X1, CARPORT-X2, GEN-V1, GEN-V2, and GEN-S1. A1's rendered text contains `6.0 m x 7.0 m`.
- [ ] A stated roof covering omits CARPORT-A5. The other assumptions remain.
- [ ] CARPORT-A2 names a `variation_item_code` that exists on the fixture rate card. A template whose code is absent raises `PolicyViolation`.
- [ ] A selection records the template's `clause_version`. A later call with a newer template versions the new selection only. The first selection's version does not change.
- [ ] WATER-E03 returns Wednesday's isolate-power template and attaches no assumption that states a price.
- [ ] Clause text is data in the test policy. `select_clauses` does not hard-code a rand amount.

### [design/quote-fixture.md](design/quote-fixture.md)

- [ ] Path recorded: `tests/fixtures/quotes/aquasure_5000l.json`. Pretty-printed. A reviewer can read it without running code.
- [ ] It is the issued 5000 L replacement. Quote id `QD-1042`. State `ISSUED`. Rule `WATER-F01`. Policy `water-policy-v1.0`. Version 1.
- [ ] One line, item `TANK-5000`, quantity `1`, unit price and total the placeholder `4250.00`. Money is a decimal string, never a JSON number.
- [ ] Expiry is `2026-11-07`. The card will show that as `7 November 2026`.
- [ ] Clauses are the water sentences from `design/clauses.md`, with placeholders already filled.
- [ ] No float, no second price, and no field that `Decision` does not already allow except the priced lines on the quote itself.

### [design/quote-card-refresh.md](design/quote-card-refresh.md)

- [ ] Agents update `fixed_offer.json`, `range.json`, `site_visit.json`, and `hazard.json` from Thursday's committed quote and the price examples. They do not add an eleventh state.
- [ ] Fixed offer: headline `Fixed quote`, amount `R 4 250.00`, expiry `7 November 2026`, rule `WATER-F01`, clauses copied from the printable quote.
- [ ] Hazard: the body is WATER-E03's customer template. No amount and no fee.
- [ ] Display rules stay Tuesday's: space as the thousands separator, dates as `7 November 2026`, no WhatsApp logo, no amount hard-coded in a template.

### [design/webhook-outbox.md](design/webhook-outbox.md)

- [ ] `tests/fixtures/whatsapp/text_message.json` is one Cloud API text message. The body is customer text. It is not a commercial rule.
- [ ] The outbox is an adapter model. A test can append one pending row and read it back. The test does not import `quotedesk.domain`.
- [ ] The outbox does not call the network and does not send the row.
- [ ] No database table is created today.

## Tests to create

Tests are written failing, against the design files above. They assert the boundary values below. They do not contain the implementation. Empty packages may be added so pytest can collect them.

### `tests/unit/domain/test_quote.py`

- [ ] `test_issued_version_is_immutable` — an issued line price, clause, or expiry cannot be patched. Each raises `PolicyViolation`. The previous values remain.
- [ ] `test_new_version_revises_the_previous` — version 1 issued, version 2 created. Version 1 is `REVISED`. Version 2 is current. Version 1's line items are still readable. D6.
- [ ] `test_illegal_transitions` — `ISSUED` to `DRAFT`, `EXPIRED` to `BOOKING_CONFIRMED`, `REJECTED` to `ISSUED`, `ESCALATED` to `ISSUED`. Each raises `InvalidTransition` with code `quote.invalid_transition`.
- [ ] `test_every_legal_transition` — one step for each of the 22 pairs in `design/quote.md`. Each ends in the named state.
- [ ] `test_stale_version_is_rejected` — a write of version 1 after version 2 exists raises `StaleQuote` with code `quote.stale`. A write of the current version does not.
- [ ] `test_approval_is_bound_to_one_version` — version 1's approval applied to version 2 raises. An instant after `expires_at` raises. The named version at `expires_at` keeps the approval. D9.
- [ ] `test_outcome_picks_the_issued_state` — `fixed_offer` and `indicative_range` become `ISSUED`. `site_assessment` becomes `SITE_ASSESSMENT_OFFERED`. `escalation` becomes `ESCALATED`.
- [ ] `test_quote_id_is_assigned_not_chosen_by_the_caller` — `QD-1042` is stored. `QD-1` raises `ValidationError` with code `quote_id.invalid`.
- [ ] `test_fixture_quote_5000l_replacement` — `tests/fixtures/quotes/aquasure_5000l.json` loads as the issued quote. One line, `TANK-5000`, total `4250.00` as `Money`. State `ISSUED`. No float in the file.

### `tests/unit/domain/test_price.py`

The fixture rate card is Python in the test. `TANK-5000` is `4250.00`. The two roof coverings are `8500.00` and `12400.00`. The visit fee setting is `750.00`. All of those are `Money`.

- [ ] `test_price_fixed_offer_line_items` — quantity `Decimal("1")` totals `4250.00`. Quantity `Decimal("2.5")` totals `10625.00`. The unit price is the card's price. D5.
- [ ] `test_price_range_has_min_and_max` — two coverings. `min` is `8500.00` and `max` is `12400.00`. Line items empty. Both ends are rate-card values.
- [ ] `test_price_range_collapses_when_min_equals_max` — one covering. `min == max`. `price_type` stays `range`.
- [ ] `test_price_site_visit_fee_only` — `price_type` is `none`. Fee is `750.00`. Line items empty. Range empty. No deposit.
- [ ] `test_price_escalation_has_no_amount` — every money field empty. No fee.
- [ ] `test_price_unknown_item_code` — one unknown code raises. One known code and one unknown code raise. The error has no line items.
- [ ] `test_price_rejects_zero_quantity` — `0` and a negative quantity raise `PolicyViolation`.
- [ ] `test_price_does_not_apply_a_discount` — a fixture discount of 10 is ignored. The returned discount is zero.
- [ ] `test_price_refuses_low_confidence_fixed_decision` — outcome `fixed_offer` and band `low` raises `PolicyViolation`.

### `tests/unit/domain/test_clauses.py`

- [ ] `test_clauses_for_the_carport_with_only_a_size` — only 6.0 m by 7.0 m. The eleven ids from `design/clauses.md` are present. A1 contains `6.0 m x 7.0 m`.
- [ ] `test_clauses_omit_a_confirmed_assumption` — roof covering stated. CARPORT-A5 is absent. The other assumptions remain.
- [ ] `test_clauses_fill_placeholders` — `{deposit_percent}` and `{validity_days}` are replaced from settings. A missing setting raises. The raw token `{deposit_percent}` is absent.
- [ ] `test_clauses_pin_version` — the selection stores `clause_version`. A newer template on a second call does not change the first selection.
- [ ] `test_clauses_name_a_real_variation_item` — CARPORT-A2's `variation_item_code` is on the card. A missing code raises `PolicyViolation`.
- [ ] `test_escalation_still_gets_its_customer_sentence` — WATER-E03's text is `Please isolate the power near the water, and stay clear of it until we've checked the site.` No price assumption is attached.

### Adapter tests the agents implement against

Written after the two adapter designs. Agents do not edit them.

- [ ] `tests/adapters/test_outbox.py` — one pending row can be appended and read back. The test imports no domain module and opens no network connection.
- [ ] `tests/adapters/test_whatsapp_fixture.py` — the text fixture has one message, type `text`, and a non-empty body.

### Morning close

- [ ] Domain tests fail because the types are not implemented yet, and they fail for the right reason.
- [ ] `tests/fixtures/quotes/aquasure_5000l.json` is in the commit. A person can open it and read the 5000 L line.
- [ ] Designs and failing tests are committed before the handoff.

## Build

### You, 18:00–22:00 — quote, price, and clauses

Implement only what the tests describe.

- [ ] `quotedesk/domain/quotes/` for the aggregate, versions, and approvals.
- [ ] `quotedesk/domain/services/price.py`.
- [ ] `quotedesk/domain/services/select_clauses.py`.
- [ ] `pytest tests/unit/domain -q` is green.
- [ ] `lint-imports` is green.
- [ ] `price` does not write an amount onto a `Decision`.

### Agents, daytime — cards, webhook fixture, outbox

Do not add a quote-card state. Do not add a table. Do not parse Excel.

- [ ] `fixed_offer.json`, `range.json`, `site_visit.json`, and `hazard.json` match `design/quote-card-refresh.md`.
- [ ] The hazard body is the E03 template. The fixed-offer amount is `R 4 250.00`.
- [ ] `tests/fixtures/whatsapp/text_message.json` matches the fixture test.
- [ ] The outbox model satisfies `tests/adapters/test_outbox.py` and does not send.
- [ ] Adapter tests above pass.
- [ ] The diff contains no edit under `quotedesk/domain/`, ports, DTOs, seeds, or `tests/unit`.

## Handoff at 08:00

Send this after the printable quote is committed. One midday check is enough.

```text
Slice: quote-card refresh for four states, WhatsApp text fixture, outbox shell
Design: docs/build/2026-10-29/design/quote-card-refresh.md, docs/build/2026-10-29/design/webhook-outbox.md
Tests: tests/adapters/test_outbox.py, tests/adapters/test_whatsapp_fixture.py. Do not edit them. Do not weaken an assertion.
You may edit: quotedesk/adapters/inbound/http/templates/, quotedesk/adapters/outbound/channels/, tests/fixtures/quote_card/fixed_offer.json, tests/fixtures/quote_card/range.json, tests/fixtures/quote_card/site_visit.json, tests/fixtures/quote_card/hazard.json, tests/fixtures/whatsapp/
You must not edit: quotedesk/domain, quotedesk/application/ports, quotedesk/application/dto, seeds, tests/unit
Done when: the two adapter tests pass, the four card fixtures match the design, and lint-imports passes.
Out of scope today: database tables, schedule, GetQuote, FrameWorks, live WhatsApp, Excel parsing, a new card state.
```

- [ ] Handoff sent.
- [ ] Midday check done. Agent questions answered. Domain diffs, if any, reverted.

## Evening gate, 21:00–22:00

- [ ] `pytest tests/unit/domain -q` passes.
- [ ] `pytest tests/adapters/test_outbox.py tests/adapters/test_whatsapp_fixture.py -q` passes.
- [ ] `lint-imports` passes.
- [ ] You opened the fixed-offer card. Headline `Fixed quote`. Amount `R 4 250.00`. Expiry `7 November 2026`. Clause sentences match the printable quote.
- [ ] You read `tests/fixtures/quotes/aquasure_5000l.json`. One line. No float.
- [ ] Agent diff contains no edit under `quotedesk/domain/`, ports, DTOs, or seeds.
- [ ] `.env` is untracked.
- [ ] Slip list below is filled if anything is still red.
- [ ] Tomorrow's function is named: `schedule`, the case file, and `GetQuote`.

## Slip list

Write one line per red item: id, failing check, and where it moves. Friday morning starts on this list if a line is still open.

- [ ] Slip list reviewed. Empty is fine.

| Item | Failing check | Moves to |
| --- | --- | --- |
|  |  |  |
