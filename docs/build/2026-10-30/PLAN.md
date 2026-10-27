# Friday 30 October 2026

One commitment, from facts to a quote. This is the working list for the day. Tick a box only when that item is actually done. The week plan is [QuoteDesk_Build_Plan.md](../QuoteDesk_Build_Plan.md). Designs written this morning go in [design/](design/) before any test for that artifact.

Thursday's slip list has no red test. Nothing on it moves here. Do not reopen `Quote`, `price`, `select_clauses`, `decide`, `derive_confidence`, or `classify_injection_claims`.

**You:** 05:30–06:00 confirm D8, and the two readings below. 06:00–08:00 write the designs, then the failing tests, including `GetQuote` with in-memory fakes. 18:00–21:30 implement DOM-11, DOM-13, DOM-14, APP-1, and APP-7.

**Agents, daytime:** Alembic tables for Thursday's quote models, and a status line on the existing card. They start only after those models are committed. They do not edit `quotedesk/domain/`, `quotedesk/application/ports/`, `quotedesk/application/dto/`, `seeds/`, `tests/unit/`, or `tests/use_cases/`.

**Done when:** `pytest tests/unit/domain tests/use_cases -q` and `lint-imports` are green, `GetQuote` on the 5000 L facts returns an issued quote and the fake unit of work recorded one audit event, and you have read that quote back.

**Out of scope today:** `RequestChange`, applying a discount, `RunAgentTurn`, the commitment checker, `ReceiveInboundEvent`, the input gate, `UpdateCase`, `CheckAvailability`, `HoldSlot`, `GetQuoteStatus`, `CreateDepositLink`, FrameWorks `decide`, `validate_policy`, `seeds/aquasure.yaml`, case-file tables, conversation tables, row-level security, deposit links, and live WhatsApp.

## Confirm decisions, 05:30–06:00

Re-read these in the week plan. Overturn one there, in writing, before any test. After 06:00 they are the rules.

- [x] D8. Schedule dates are civil dates in Africa/Johannesburg. The domain receives that date. It does not call `datetime.now`.
- [x] D4 and D7 stay as already confirmed. A contradiction is stored and not resolved. A hold exists only after the deposit is paid. A site assessment and an escalation do not carry a deposit.
- [x] "No price" on the low-confidence `GetQuote` means no line total, no range, and no deposit. `price` still returns the visit fee. Do not change `price` so the fee comes back empty.
- [x] SCHED-07 sets schedule status `escalated`. It does not move the quote to `PENDING_APPROVAL`. That state change waits for Saturday's `RequestChange`.

`Outcome` stays `fixed_offer`, `indicative_range`, `site_assessment`, `escalation`. `Decision` still has no amount.

Proposed shapes, confirm or replace in the design files before the tests:

`schedule` takes a structured request, a capacity snapshot, settings, a deposit state, the civil `today`, and an `at` instant. It returns a new commitment and, when a hold succeeds, a new capacity snapshot. It does not mutate its inputs, parse a customer sentence, read the clock, or mint an id. "Now now" is a request whose date is `today`. A guarantee is a request kind, not a phrase match.

`civil_date(at, zone)` turns one injected instant into a civil date. The zone is an argument. The Friday test passes 30 October 2026 22:30 UTC and `Africa/Johannesburg`, and gets Saturday 31 October 2026.

`CaseFile` stores sourced facts. It does not replace `quotedesk.domain.case.facts.CaseFacts`. The caller passes every fact id and every event id. A correction supersedes. The reader sees one current value. `detect_contradiction` reports a disagreement and deletes nothing.

`Conversation` appends events. A repeated provider message id does not append a second event. Read order is the provider timestamp. A body is not edited. Enrichment is stored on the original event.

`GetQuote` is a use case. It loads the case file and the published policy bundle, then calls `decide`, `price`, and `select_clauses`. It opens a quote with an id from the id port and an expiry from the clock's civil date plus the published `validity_days`. The schedule status on that quote is `none`. It does not call `schedule`. It saves the quote and one audit event in the same fake unit of work, or it saves neither.

## Design to create

Written 30 October 2026. A test starts only after its design file is ticked. Domain designs come first, then the use-case designs, then the two adapter designs, before the 08:00 handoff.

### [design/schedule.md](design/schedule.md)

- [x] Purpose: one function creates a date commitment. The sentence comes from a template in settings.
- [x] Signature recorded: `schedule(request, capacity, settings, deposit_state, *, today, at) -> ScheduleResult`.
- [x] Status values recorded: `none`, `indicative`, `held`, `confirmed`, `escalated`.
- [x] Module paths recorded. The commitment type lives in `quotedesk/domain/quotes/schedule.py`. The function lives in `quotedesk/domain/services/schedule.py`.
- [x] The function imports only the standard library, Pydantic, and `quotedesk.domain`. It does not call `datetime.now` or `date.today`.
- [x] D8 recorded. `today` is a `datetime.date` and not a `datetime`. `civil_date` is the only conversion, and the test supplies the zone.
- [x] Fixture settings recorded: replacement lead time 5 working days, minimum notice 2 working days, hold period 48 hours, working days Monday to Friday, blocked date 2 November 2026.
- [x] No quote yields status `none`, a sentence that contains the lead time, and no window id.
- [x] An issued quote asking for the earliest window yields `indicative`. Remaining capacity is unchanged.
- [x] An open requested Saturday is `indicative`. Hold fields are empty. The sentence offers a hold on payment.
- [x] A full Saturday returns the next two open working days and does not describe Saturday as held.
- [x] A date inside the minimum notice is `indicative`, returns the earliest legal window, and the request model has no override field.
- [x] A paid deposit on an open window yields `held`. `hold_expires_at` is `at` plus 48 hours. The returned capacity is one lower. The input capacity is unchanged.
- [x] An unpaid deposit raises `PolicyViolation` with code `policy.violation`. Capacity is unchanged.
- [x] Confirmed requires site measure signed off and materials confirmed. One dependency missing stays `held`.
- [x] A guarantee request yields `escalated`, holds nothing, and does not change a quote state.
- [x] A request dated `today` takes the same path as a date inside the minimum notice.
- [x] A Saturday request skips Sunday and the blocked Monday and offers Tuesday 3 November 2026.
- [x] Capacity 1: the first hold succeeds, the second raises, and the slot stays at zero.
- [x] A hold whose `hold_expires_at` is before `at` does not consume capacity. The design records whether an instant equal to `hold_expires_at` is still held.
- [x] Customer sentences are settings data. The function does not hard-code a date or a rand amount.

### [design/case-file.md](design/case-file.md)

- [x] Purpose: one current value per key, and the history kept beside it.
- [x] `CaseFacts` in `facts.py` stays the input `decide` already uses. This file does not change it.
- [x] Module path recorded: `quotedesk/domain/case/case_file.py`. `detect_contradiction` lives in `quotedesk/domain/case/contradictions.py`.
- [x] A fact without an `event_id` is rejected. The design records the code and the sentence.
- [x] Legal sources recorded: `customer_text`, `voice_transcript`, `photo_extraction`, `video_extraction`, `owner`.
- [x] 2500 L then 5000 L on the same key: the reader sees 5000 L. The 2500 L fact remains, with `superseded_by` set. The caller passes both fact ids.
- [x] Two active facts for one key are rejected. The design records the type, the code, and the sentence. The legal write is the correction, which supersedes.
- [x] A text fact `roof` and a photo fact `ground level` on the same key stores both and records one contradiction. Neither fact is deleted. D4.
- [x] Two sources that both say 5000 L record no contradiction.
- [x] A tank job and a pump job keep their facts apart.
- [x] `start_over` closes that job. Facts stay readable. Nothing is deleted.
- [x] The type does not read the clock, the environment, or the network, and it does not mint an id.

### [design/conversation.md](design/conversation.md)

- [x] Purpose: the log is append-only and unique per provider message id.
- [x] Module path recorded: `quotedesk/domain/conversation/events.py`.
- [x] The same provider message id twice stores one event. The second call reports duplicate and does not raise.
- [x] A later timestamp stored first, then an earlier one, reads in timestamp order.
- [x] Replacing a body raises. The design records the type, the code, and the sentence. The stored text stays.
- [x] A transcript id and an extraction id attach to the original event. They do not create a second customer event.
- [x] The type does not read the clock or the network, and it does not mint an id.

### [design/tool-dtos.md](design/tool-dtos.md)

- [x] Purpose: tools take identifiers and structured facts. The agent cannot pass a commercial result.
- [x] `GetQuote` input has `conversation_id` only. `extra` is forbid.
- [x] `unit_price`, `outcome`, `clause_text`, and `discount_percent` each fail validation.
- [x] An empty body fails. An unknown field fails. A fact missing `source` fails.
- [x] `TenantContext` is required. `execute` without one raises. The design records the exception. It is not a domain `PolicyViolation`.
- [x] A context for tenant A is the tenant the fake repository records.
- [x] Ports recorded: case file, published policy, quote, audit, clock, id generator, and a unit of work that commits them together or not at all.
- [x] Fakes live in the tests. No port imports an adapter.

### [design/get-quote.md](design/get-quote.md)

- [x] Purpose: one use case turns the current case into one quote version.
- [x] Module path recorded: `quotedesk/application/use_cases/tools/get_quote.py`.
- [x] The published bundle is Wednesday's AquaSure policy, Thursday's rate card, and the clause settings already used: deposit 30, validity 14 days, visit fee `750.00`.
- [x] A draft v1.1 with a different tank price is not read. The line stays `4250.00` and the policy version stays `water-policy-v1.0`.
- [x] High-confidence like-for-like facts follow WATER-F01. One line, `TANK-5000`, total `4250.00`. State `ISSUED`. The condition tuple is the empty selection `select_clauses` returns for `replacement`. The customer template is present. Schedule status `none`.
- [x] The fake unit of work records one audit event for that save.
- [x] When the fake audit raises, the quote repository has no new row.
- [x] Two failed checks, with no earlier rule, follow WATER-L01. State `SITE_ASSESSMENT_OFFERED`. No line total, no range, and no deposit. The visit fee is the settings fee.
- [x] A leaning stand follows WATER-E02. State `ESCALATED`. The customer template is present. No fee and no deposit.
- [x] A second call after the size fact changes from 2500 L to 5000 L appends version 2. Version 1 is `REVISED` and still readable. Both calls are fixed offers. The use case does not skip a version because the total matches.
- [x] A case that exists only for tenant B is not returned to tenant A. No quote is saved and no audit event is written.
- [x] The decision and the quote both record `water-policy-v1.0`.
- [x] Expiry is the injected civil date plus 14 days. The use case does not hard-code 7 November 2026.
- [x] The id comes from the id port. `QD-1042` is the first id the fake returns. The aggregate still does not mint one.
- [x] `GetQuote` does not call a model, open a database connection, or call `schedule`.

### [design/quote-tables.md](design/quote-tables.md)

- [x] Agents add tables only for the quote models already committed: quote versions, line items, conditions, evidence, and approvals.
- [x] No table for the case file, the conversation, or a schedule commitment.
- [x] A repository contract test, which you write, saves the 5000 L quote and loads the same version, line, clauses, and state.
- [x] The test runs against the Compose database. Agents do not weaken it.
- [x] Row-level security is Saturday. Today's migration does not add it.

### [design/quote-card-status.md](design/quote-card-status.md)

- [x] The fixed-offer card shows a status line from the fixture: state `ISSUED`, version 1, expiry `7 November 2026`, schedule status `none`.
- [x] No eleventh card state. No new route. `GetQuoteStatus` is Saturday.
- [x] Display rules stay Tuesday's. The amount stays `R 4 250.00` and is not hard-coded in the template.

## Tests to create

Tests are written failing, against the design files above. They assert the boundary values below. They do not contain the implementation. Empty packages may be added so pytest can collect them.

### `tests/unit/domain/test_schedule.py`

- [x] `test_sched_01_lead_time_before_a_quote` — no quote. Status `none`. The sentence contains the configured lead time. No window id.
- [x] `test_sched_02_earliest_window_is_indicative` — status `indicative`. Remaining capacity is unchanged.
- [x] `test_sched_03_requested_date_open` — requested Saturday is open. Status `indicative`. Hold fields empty. The sentence offers a hold on payment.
- [x] `test_sched_03_requested_date_closed` — Saturday is full. The next two open working days are returned. Saturday is not described as held.
- [x] `test_sched_04_inside_minimum_lead` — the request is inside the minimum notice. Status `indicative`. The earliest legal window is returned. The request has no override field.
- [x] `test_sched_05_hold_after_deposit` — deposit paid and the window open. Status `held`. `hold_expires_at` is `at` plus the hold period. Returned capacity is one lower.
- [x] `test_sched_05_hold_without_deposit_refused` — deposit unpaid. `PolicyViolation`. Capacity unchanged.
- [x] `test_sched_06_confirmed_when_dependencies_met` — both dependencies met. Status `confirmed`. One missing stays `held`.
- [x] `test_sched_07_no_guarantee` — a guarantee request. Status `escalated`. No window held.
- [x] `test_sched_now_now_is_a_date_request` — requested date is `today`. Same result as a date inside the minimum notice.
- [x] `test_sched_skips_weekends_and_blocked_dates` — working days Monday to Friday, one blocked Monday, a Saturday request. The offered window is Tuesday 3 November 2026.
- [x] `test_sched_second_hold_of_a_full_slot_fails` — capacity 1. The first hold succeeds. The second raises.
- [x] `test_sched_expired_hold_releases` — `hold_expires_at` before the injected `at`. The slot is available.
- [x] `test_sched_local_date_not_utc` — 30 October 2026 22:30 UTC and `Africa/Johannesburg` produce Saturday 31 October 2026. D8.

### `tests/unit/domain/test_case_file.py`

- [x] `test_fact_requires_a_source_event` — a missing `event_id` is rejected. Each of the five legal sources is accepted.
- [x] `test_correction_supersedes` — 2500 L then 5000 L. The reader sees 5000 L. The 2500 L fact remains with `superseded_by` set.
- [x] `test_two_active_facts_for_one_key_rejected` — a second active fact, without superseding, raises.
- [x] `test_contradiction_is_stored_not_resolved` — text says roof, photo extraction says ground level. One contradiction. Neither fact is deleted.
- [x] `test_detect_contradiction_when_values_agree` — both sources say 5000 L. No contradiction.
- [x] `test_several_jobs_in_one_case` — a tank job and a pump job. Facts stay on their job.
- [x] `test_start_over_closes_the_job_and_keeps_the_facts` — the job is closed. Facts remain readable. Nothing is deleted.

### `tests/unit/domain/test_conversation.py`

- [x] `test_duplicate_provider_id_is_ignored` — the same provider message id twice stores one event. The second call reports duplicate.
- [x] `test_events_order_by_provider_timestamp` — a later timestamp is stored first. The read order is timestamp order.
- [x] `test_events_are_append_only` — changing the text raises. The stored text stays.
- [x] `test_enrichment_attaches_to_the_event` — a transcript id and an extraction id are stored on the original event.

### `tests/use_cases/test_tool_inputs.py`

- [x] `test_get_quote_input_forbids_commercial_fields` — `unit_price`, `outcome`, `clause_text`, and `discount_percent` each fail. `conversation_id` alone passes.
- [x] `test_tool_inputs_require_ids_not_prose` — an empty body fails, an unknown field fails, and a fact missing `source` fails.
- [x] `test_tenant_context_is_required` — `execute` without a `TenantContext` raises. Tenant A is the tenant the fake repository records.

### `tests/use_cases/test_get_quote.py`

Fakes for the case file, the published policy, the quote repository, the audit log, the clock, and the id generator. No model and no database.

- [x] `test_get_quote_fixed_offer_for_the_5000l_replacement` — WATER-F01, one line, the empty condition tuple `select_clauses` returns for `replacement`, the customer template present, state `ISSUED`, schedule status `none`, one audit event in the same fake unit of work.
- [x] `test_get_quote_rolls_back_when_audit_fails` — the fake audit raises. The quote repository has no new row.
- [x] `test_get_quote_uses_the_published_policy_only` — published v1 and a draft v1.1 with a different price. The quote uses v1 and `4250.00`.
- [x] `test_get_quote_low_confidence_has_no_price` — two failed checks. State `SITE_ASSESSMENT_OFFERED`. No line total, no range, and no deposit.
- [x] `test_get_quote_hazard_has_no_price` — a leaning stand. State `ESCALATED`. The customer template is present.
- [x] `test_get_quote_second_call_creates_version_two` — first call 2500 L, then the fact superseded to 5000 L. Version 2 is current. Version 1 is `REVISED`.
- [x] `test_get_quote_is_tenant_scoped` — tenant A does not see a case that exists only for tenant B.
- [x] `test_get_quote_pins_policy_version` — `water-policy-v1.0` is on the decision and on the quote.

### Adapter test the agents implement against

Written after `design/quote-tables.md`. Agents do not edit it.

- [x] `tests/adapters/test_quote_tables.py` — the 5000 L quote round-trips through the Compose database. Version, line, clauses, and state match what was saved.

### Morning close

- [ ] Domain and use-case tests fail because the types are not implemented yet, and they fail for the right reason.
- [ ] Designs and failing tests are committed before the handoff.
- [ ] Thursday's quote, price, and clause modules are committed, so the table handoff has models to store.

## Build

### You, 18:00–21:30 — schedule, case file, conversation, ports, GetQuote

Implement only what the tests describe.

- [x] `quotedesk/domain/quotes/schedule.py` and `quotedesk/domain/services/schedule.py`.
- [x] `quotedesk/domain/case/case_file.py` and `quotedesk/domain/case/contradictions.py`.
- [x] `quotedesk/domain/conversation/events.py`.
- [x] `quotedesk/application/ports/` and `quotedesk/application/dto/` for the contracts the tests call.
- [x] `quotedesk/application/use_cases/tools/get_quote.py`.
- [x] `pytest tests/unit/domain tests/use_cases -q` is green.
- [x] `lint-imports` is green.
- [x] `GetQuote` does not call `schedule`, and it does not write an amount onto a `Decision`.

### Agents, daytime — quote tables and a status line

Do not add a case-file table. Do not add a card state. Do not call `GetQuoteStatus`.

- [x] The migration matches `design/quote-tables.md`.
- [x] `tests/adapters/test_quote_tables.py` passes against Compose.
- [x] The fixed-offer card shows the status line from `design/quote-card-status.md`.
- [ ] The diff contains no edit under `quotedesk/domain/`, ports, DTOs, seeds, `tests/unit/`, or `tests/use_cases/`.

## Handoff at 08:00

Send this after the designs, the failing tests, and Thursday's quote models are committed. One midday check is enough.

```text
Slice: quote tables for the committed models, and a status line on the fixed-offer card
Design: docs/build/2026-10-30/design/quote-tables.md, docs/build/2026-10-30/design/quote-card-status.md
Tests: tests/adapters/test_quote_tables.py. Do not edit them. Do not weaken an assertion.
You may edit: quotedesk/adapters/outbound/persistence/, quotedesk/infrastructure/db.py, the Alembic tree, quotedesk/adapters/inbound/http/templates/quote_card.html, tests/fixtures/quote_card/fixed_offer.json
You must not edit: quotedesk/domain, quotedesk/application/ports, quotedesk/application/dto, seeds, tests/unit, tests/use_cases
Done when: the table test passes against Compose, the fixed-offer card shows state, version, expiry, and schedule status none, and lint-imports passes.
Out of scope today: case-file tables, conversation tables, row-level security, GetQuoteStatus, live WhatsApp, a new card state.
```

- [ ] Handoff sent.
- [ ] Midday check done. Agent questions answered. Domain diffs, if any, reverted.

## Evening gate, 21:30–22:00

- [x] `pytest tests/unit/domain tests/use_cases -q` passes.
- [x] `lint-imports` passes.
- [x] `GetQuote` on the 5000 L facts returns one issued quote. The fake unit of work recorded one audit event. Schedule status is `none`.
- [x] You read that result. Rule `WATER-F01`. One line. Total `4250.00`. No float.
- [x] If `schedule` is still red, it is the first line of the slip list and it moves to Saturday block A. `GetQuote` is still green with schedule status `none`.
- [ ] Agent diff contains no edit under `quotedesk/domain/`, ports, DTOs, or seeds.
- [x] `.env` is untracked.
- [x] Slip list below is filled if anything is still red.
- [x] Saturday does not start while `GetQuote` is red. Tomorrow's first block is `RequestChange` and the commitment checker, unless this gate says otherwise.

## Slip list

Write one line per red item: id, failing check, and where it moves. A red `GetQuote` stays here. It does not move to Saturday.

- [x] Slip list reviewed. Empty is fine.

| Item | Failing check | Moves to |
| --- | --- | --- |
|  |  |  |
