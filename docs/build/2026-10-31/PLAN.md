# Saturday 31 October 2026

The water conversation works. This is the working list for the day. Tick a box only when that item is actually done. The week plan is [QuoteDesk_Build_Plan.md](../QuoteDesk_Build_Plan.md). Designs written today go in [design/](design/) before any test for that artifact.

Friday's slip list has no red test. Nothing on it moves here. `GetQuote` is green, so block A is `RequestChange` and the commitment checker. Do not reopen `Quote`, `price`, `select_clauses`, `decide`, `derive_confidence`, `classify_injection_claims`, `schedule`, `CaseFile`, `Conversation`, or `GetQuote`.

**You:** three blocks, about twelve to sixteen hours. Each block is its designs, then its failing tests, then the implementation, then the gate. The next block waits. You read every row-level security policy before it is applied.

**Agents:** after the block B gate is green, the migration and the web chat shell. They do not edit `quotedesk/domain/`, `quotedesk/application/ports/`, `quotedesk/application/dto/`, `seeds/`, `tests/unit/`, or `tests/use_cases/`.

**Done when:** a 10 percent request is `PENDING_APPROVAL`, a reply that invents a price never reaches the outbox, the harness has posted a Cloud API payload and read the outbox, a scripted text-plus-photo turn produces one quote, and you have walked the click-path in the browser. `pytest` and `lint-imports` are green.

**Out of scope today:** approving or rejecting that request, the operator console, FrameWorks `decide`, `validate_policy`, publish, rate-card import, live WhatsApp delivery, live PayFast, Wonder as a transcript judge, the impact preview, and switching Afrikaans on. A visit fee is still not a deposit. `price` still ignores a discount. Monday no longer writes the harness scenarios. It re-runs the ones this day leaves green.

## Confirm decisions, before block A

Re-read these in the week plan. Overturn one there, in writing, before any test. After that they are the rules.

- [x] D6. Issuing version n+1 sets version n to `REVISED`. Both versions remain. A request that waits does not issue, so it does not revise.
- [x] D7 stays as already confirmed. A deposit link is allowed for an issued fixed quote or an issued range quote after recorded acceptance. A site assessment and an escalation never get one. A hold exists only after the deposit is paid.
- [x] D9. An approval applies to one version. Saturday stores the wait. Sunday applies the approval. `RequestChange` does not approve its own exception.
- [x] D10. An injection is stored and is not treated as authority. The customer sentence does not say that an injection was detected.

`Outcome` stays `fixed_offer`, `indicative_range`, `site_assessment`, `escalation`. `Decision` still has no amount. `GetQuote` still reports schedule status `none` and still does not call `schedule`.

Proposed shapes, confirm or replace in the design files before the tests:

The automatic discount cap is a tenant setting. The fixture cap is 5. A percent from 0 through 5 issues version 2 and leaves version 1 at discount 0. A percent from above 5 through 100 moves the current version to `PENDING_APPROVAL` and leaves its price unchanged. `-1` and `101` raise. The design records the type, the code, and the sentence. `RequestChange` does not call `price` and expect the percent to be applied. `price` stays as Thursday left it.

The commitment checker is a pure function. It takes the draft reply and the amounts, civil dates, clause sentences, and schedule status that this turn's tools returned. It does not call a model, read the clock, or send a message. `R 4 250`, `R4250`, `R 4,250`, and `4250 rand` are the same amount. The function lives where it can stay free of adapters. The design records the module path.

The gate's code checks run before any classifier call. The classifier result in the tests is injected. Explicit media and an identity document are not stored. The customer sentences are the ones already fixed in the week plan, copied verbatim.

The quiet window in the test is 5 seconds. The clock is injected. An event at 5.0 seconds is inside the window. An event at 5.1 seconds starts the next one.

`CheckAvailability` calls `schedule` and holds nothing. `HoldSlot` calls `schedule` for a hold. An unpaid quote does not change capacity.

`GetQuoteStatus` returns one empty result for a wrong code, a missing code, and a code that belongs to a different quote. The empty result does not say whether the quote id exists. The right code on an expired quote returns `EXPIRED`.

`CreateDepositLink` returns one sandbox URL. It does not call PayFast. The same idempotency key returns the same URL.

## Design to create

A test starts only after its design file is ticked. Block A designs before block A tests. Do not write a later block's tests while the current gate is red.

### [design/request-change.md](design/request-change.md)

- [x] Purpose: a customer asks for a change. Within the cap, the quote is reissued. Above the cap, the owner must decide.
- [x] Module path recorded: `quotedesk/application/use_cases/tools/request_change.py`.
- [x] The input carries the quote id, the version, the idempotency key, and either a discount percent or a named clause change. It does not carry a new price. `extra` is forbid.
- [x] Fixture cap recorded: 5. The cap is read from settings.
- [x] Discount 5 issues version 2. Version 1 is `REVISED`. Version 1's discount stays 0. The design records how version 2's total is computed from the issued lines and the percent.
- [x] Discount 5.01 and discount 10 leave the issued price as it is and move that version to `PENDING_APPROVAL`.
- [x] `-1` and `101` raise. Discount 100 waits. The design records the type, the code, and the sentence.
- [x] A request to delete an exclusion waits. The clause remains on the issued version.
- [x] A reason that says the owner already approved 50 percent off waits. The issued discount stays 0. The claim is not authority.
- [x] The same idempotency key twice returns the first result and does not create a second version.
- [x] The use case does not call a model, and it does not approve the request.

### [design/commitment-checker.md](design/commitment-checker.md)

- [x] Purpose: a draft reply may say only what this turn's tools returned.
- [x] Module path recorded. The function does not import an adapter.
- [x] `R 4 250` in the reply passes when that amount is in the tool result, and fails when it is absent. `R4250`, `R 4,250`, and `4250 rand` are the same amount.
- [x] "7 November" passes when the availability result contains that civil date. "this Saturday" fails when the tool did not return that date.
- [x] "includes installation" passes when a clause says so. "includes council plans" fails when CARPORT-X1 excludes them.
- [x] A reply that says "guaranteed" fails when the tool status is `escalated`.
- [x] A reply that contains the tool's amount, names a range as a range, and contains the card link passes.
- [x] The function does not call a model and does not write to the outbox. `RunAgentTurn` is the caller, and it is block B.

### [design/inbound-gate.md](design/inbound-gate.md)

Read [design/whatsapp-simulator-learnings.md](design/whatsapp-simulator-learnings.md) for how a gate sentence reaches the thread. It adds no box below.

- [x] Purpose: a message is stored and checked. The agent does not run on the webhook.
- [x] Module path recorded: `quotedesk/application/use_cases/conversation/receive_inbound.py`.
- [x] One text event is stored. The agent fake is not called.
- [x] The same provider message id twice stores one event.
- [x] Code checks run before the classifier port is called. The design records the fixture size limit, the duration limit, and the allowed types.
- [x] Over size, a disallowed MIME, audio over the duration, and a zero-byte file each return the fixed sentence and store nothing usable as a fact.
- [x] The message at the fixture rate limit plus one returns "I'm getting a lot of messages at once. Please send the next one in a minute." The design records the fixture limit.
- [x] Category `explicit` stores no object and returns "I didn't keep that. Please resend without the sensitive image."
- [x] Category sensitive document uses that same sentence and stores no object.
- [x] `afrikaans_text` off, with Afrikaans text, returns "Sorry, I can't understand that yet. Could you send it in English?" The case file is unchanged. The same for voice with `afrikaans_voice` off.
- [x] An instruction in text, in a transcript, and in image text is stored as data. `classify_injection_claims` is called and not modified. No price is produced.
- [x] The use case does not read the environment for the flags. The test passes them in.

### [design/update-case.md](design/update-case.md)

- [x] Purpose: facts land on the job the tool names. `CaseFile` is not changed.
- [x] Module path recorded: `quotedesk/application/use_cases/tools/update_case.py`.
- [x] A new job and an existing job both accept a fact. An unknown key is kept as an extra and does not satisfy a required field.
- [x] 2500 L then 5000 L on the same key: the current value is 5000 L. The 2500 L fact remains.
- [x] Text `roof` and photo `ground level` store one contradiction. Neither fact is deleted.
- [x] The input is structured facts with a source and an event id. A price, an outcome, and a clause sentence fail validation.

### [design/run-agent-turn.md](design/run-agent-turn.md)

Read [design/whatsapp-simulator-learnings.md](design/whatsapp-simulator-learnings.md) for how later rows become later bubbles. It adds no box below.

- [x] Purpose: one turn calls tools, checks the reply, and only then writes the outbox.
- [x] Module path recorded: `quotedesk/application/use_cases/conversation/run_agent_turn.py`.
- [x] The model is a fake that returns scripted tool calls. The test does not open a network connection.
- [x] Events at 0s, 1s, and 4s with a 5s window are one turn. An event at 5.0s is inside. An event at 5.1s starts the next window. The clock is injected.
- [x] A message that arrives while a turn is in progress is absent from that turn and present in the next.
- [x] A reply that echoes the tool price is sent. A reply with a different price is not sent. The outbox contains the fixed refusal or a regenerated safe reply, and never the bad number.
- [x] Unfinished video enrichment writes "Got your video, having a look." The final answer is a later turn.
- [x] The first model call times out and the second succeeds: the customer gets the answer. Both time out: the customer gets "I'll ask someone from the business to pick this up. You can keep sending details here."
- [x] "Can I speak to a person?" calls `HandoverToHuman`, attaches the case file, and does not issue a quote on that turn.

### [design/schedule-tools.md](design/schedule-tools.md)

- [x] Purpose: the conversation can read a window, and can hold one only after payment.
- [x] Module paths recorded for `CheckAvailability` and `HoldSlot`.
- [x] An open window is returned. Capacity is the same before and after the read.
- [x] The same hold key twice holds one place.
- [x] An unpaid quote holds nothing. Capacity is unchanged.
- [x] Both use cases call `schedule`. Neither one changes it.

### [design/quote-status.md](design/quote-status.md)

- [x] Purpose: the card can be opened only with the verification code.
- [x] Module path recorded: `quotedesk/application/use_cases/tools/get_quote_status.py`.
- [x] A wrong code, a missing code, and a code for a different quote return the same empty result.
- [x] The right code returns state, expiry, version, and schedule status.
- [x] The right code on an expired quote returns `EXPIRED`.
- [x] The use case does not mint a code on read. The design records which port minted it.

### [design/deposit-link.md](design/deposit-link.md)

- [x] Purpose: a deposit link follows acceptance, and only for an issued price.
- [x] Module path recorded: `quotedesk/application/use_cases/tools/create_deposit_link.py`.
- [x] `ISSUED` with an acceptance event returns one sandbox URL.
- [x] No acceptance raises. An escalated quote raises. A site-assessment quote raises. The design records the type, the code, and the sentence.
- [x] The same idempotency key returns the same URL.
- [x] The URL is not a live PayFast link.

### [design/persistence.md](design/persistence.md)

- [x] Tables for the case file, the conversation, the schedule commitment, and the audit log. The quote tables from Friday stay. Row-level security covers quotes, cases, conversations, policies, and audit rows.
- [ ] You read the policies before the migration is applied. Agents may type the SQL.
- [x] The test database is the local Postgres the quote-table test already uses, on `127.0.0.1:5432`.
- [x] Session tenant A sees only A's rows. A missing tenant setting returns nothing.
- [x] The application role can insert an audit row. It cannot update or delete one.
- [x] A quote insert and an audit insert commit together. A failure between them leaves neither row.
- [x] A quote with lines, clauses, evidence, an approval, and a schedule loads back. A case with a superseded fact loads back. A conversation stored out of order reads in provider-timestamp order.

### [design/harness.md](design/harness.md)

Pulled forward from Monday. The spec had this on Friday: scenario files posted as Cloud API payloads, then checked against the outbox. Thursday's text fixture and the outbox shell stay as they are. This file adds the runner. It does not send to WhatsApp. Read [design/whatsapp-simulator-learnings.md](design/whatsapp-simulator-learnings.md) first. It adds no box below.

- [x] Purpose: one runner posts a scenario to the webhook and reads the reply from the outbox.
- [x] Module path recorded: `harness/runner.py`. Scenarios live in `harness/scenarios/`.
- [x] A scenario event becomes one Cloud API payload in the same shape as `tests/fixtures/whatsapp/text_message.json`. The runner posts it to `POST /whatsapp/webhook` and reads `GET /whatsapp/outbox`.
- [x] The runner does not call a model and does not open a network connection to WhatsApp. The turn uses the scripted model from `design/run-agent-turn.md`.
- [x] S08 can pass once `ReceiveInboundEvent` stores events. The same provider id is one event. Two messages stored out of order read in provider-timestamp order.
- [x] A text scenario that asks for the 5000 L replacement passes once `RunAgentTurn` can call `GetQuote`. The outbox reply contains `R 4 250` and no second amount.
- [x] S01 through S06 are the block B proof. S07 follows the quiet-window test. S09, S10, S11, and S12-off follow the gate, the expiry, and the handover. S12 with the flag on stays out.
- [x] The Wonder judge is not this runner. Code checks the outbox and the case.

### [design/click-path.md](design/click-path.md)

Read [design/whatsapp-simulator-learnings.md](design/whatsapp-simulator-learnings.md) before writing the chat shell. It adds no box below.

- [x] `seeds/aquasure.yaml` loads to the same rule ids as Wednesday's in-code fixture. `decide` is not changed to make the comparison pass.
- [x] The web chat for AquaSure uses `ReceiveInboundEvent`. It has no WhatsApp logo and no Meta logo.
- [x] The quote card for this path is rendered from `GetQuoteStatus`, not from a new card state.
- [x] The path accepts a typed transcript when live transcription is not wired. The card still shows a mask from a recorded fixture.
- [ ] One original voice note asking to swap a 5000 litre tank, and one original photo of a tank on a sound base, are on disk before the click-path. Neither file is in the tree today.

## Tests to create

Tests are written failing, against the design files above. They assert the boundary values below. They do not contain the implementation. Empty packages may be added so pytest can collect them.

### Block A

#### `tests/use_cases/test_request_change.py`

Fakes for the quote repository, the settings, the clock, and the unit of work. No model and no database.

- [x] `test_discount_at_the_cap_issues_a_new_version` — cap 5, discount 5. Version 2 issued. Discount 0 on version 1 remains.
- [x] `test_discount_above_the_cap_waits_for_the_owner` — cap 5. Discount 5.01 and discount 10. State `PENDING_APPROVAL`. The issued price is unchanged.
- [x] `test_negative_and_total_discounts_rejected` — `-1` raises. `100` waits. `101` raises.
- [x] `test_liability_term_change_waits` — a request to delete an exclusion. State `PENDING_APPROVAL`. The clause remains on the issued version.
- [x] `test_claimed_approval_does_not_apply` — the reason is the 50 percent claim. State `PENDING_APPROVAL`. The issued discount stays 0.
- [x] `test_request_change_is_idempotent` — the same idempotency key twice. One new version.

#### `tests/unit/domain/test_commitments.py`

The path follows the module recorded in the design. No model.

- [x] `test_reply_rand_amount_must_come_from_a_tool` — `R 4 250` present in the tool result passes. The same amount absent fails. `R4250`, `R 4,250`, and `4250 rand` are the same amount.
- [x] `test_reply_date_must_come_from_a_tool` — "7 November" in the availability result passes. "this Saturday" fails when the tool did not return that civil date.
- [x] `test_reply_inclusion_must_be_a_clause` — "includes installation" passes when a clause says so. "includes council plans" fails when CARPORT-X1 excludes them.
- [x] `test_reply_guarantee_is_refused` — tool status `escalated` and the reply says "guaranteed". Fails.
- [x] `test_reply_may_summarise_and_link` — the reply contains the tool's amount, names the range as a range, and contains the card link. Passes.

#### Block A gate

- [x] The 10 percent request is `PENDING_APPROVAL`.
- [x] A reply that invents a second price is refused.
- [x] `pytest tests/use_cases/test_request_change.py tests/unit/domain/test_commitments.py -q` passes.
- [x] `lint-imports` passes.
- [x] Block B does not start while this gate is red.

### Block B

#### `tests/use_cases/test_receive_inbound.py`

- [x] `test_receive_persists_and_returns` — one text event stored. The agent fake was not called.
- [x] `test_receive_drops_duplicate` — the same provider id. One row.
- [x] `test_gate_rejects_oversize_and_bad_type` — over the size limit, a disallowed MIME, audio over the duration, and a zero-byte file. Each gets the fixed sentence and stores nothing usable as a fact.
- [x] `test_gate_rate_limit` — the fixture limit plus one message from one sender. The last gets the rate-limit sentence.
- [x] `test_gate_explicit_image_is_not_stored` — category explicit. The media store has no object. The fixed sentence is returned.
- [x] `test_gate_identity_document_is_not_stored` — category sensitive document. The fixed sentence is returned.
- [x] `test_gate_afrikaans_flag_off` — `afrikaans_text` off, Afrikaans text. The fixed sentence. The case file is unchanged. The same for voice with `afrikaans_voice` off.
- [x] `test_gate_hidden_instruction_is_flagged` — an instruction in text, in a transcript, and in image text. The event is stored. The injection flag is set. No price.

#### `tests/use_cases/test_update_case.py`

- [x] `test_update_case_records_a_fact_on_a_job` — a new job and an existing job. An unknown key is kept and does not satisfy a required field.
- [x] `test_update_case_supersedes` — 2500 then 5000. The current value is 5000. The old value remains.
- [x] `test_update_case_flags_contradiction` — roof versus ground level. One contradiction. No automatic winner.

#### `tests/use_cases/test_run_agent_turn.py`

The model is a scripted fake. The clock is injected.

- [x] `test_quiet_window_batches_a_burst` — events at 0s, 1s, and 4s with a 5s window. One turn. 5.0s is inside. 5.1s starts the next window.
- [x] `test_one_turn_at_a_time` — a message during a turn is absent from that prompt and present in the next.
- [x] `test_run_agent_turn_calls_tools_then_checks_the_reply` — the fake calls `update_case` and `get_quote`. The reply that echoes the tool price is sent. A different price is not sent.
- [x] `test_slow_media_acknowledgement` — enrichment unfinished. The outbox contains "Got your video, having a look."
- [x] `test_model_timeout_retries_once_then_handover` — a second success returns the answer. Two timeouts return the handover sentence.
- [x] `test_speak_to_a_person` — the phrase mid-quote. `HandoverToHuman` is called. The case file is attached. That turn does not issue a quote.

#### `tests/use_cases/test_schedule_tools.py`

- [x] `test_check_availability_reserves_nothing` — an open window is returned. Capacity is unchanged.
- [x] `test_hold_slot_idempotent` — the same key. One hold.
- [x] `test_hold_slot_requires_a_paid_deposit` — an unpaid quote. No capacity change.

#### `tests/use_cases/test_quote_status.py`

- [x] `test_status_requires_the_verification_code` — a wrong code, a missing code, and a code for a different quote return the same empty result. The right code returns state, expiry, version, and schedule status. An expired quote with the right code returns `EXPIRED`.

#### `tests/use_cases/test_deposit_link.py`

- [x] `test_deposit_link_only_after_acceptance` — `ISSUED` with acceptance returns one sandbox URL. No acceptance raises. An escalated quote raises. A site-assessment quote raises. The same idempotency key returns the same URL.

#### `tests/adapters/test_harness.py`

Written after `design/harness.md`. The runner posts to the app. It does not send to WhatsApp.

- [x] `test_harness_posts_a_text_scenario` — one YAML text event becomes one Cloud API payload. `POST /whatsapp/webhook` accepts it. `GET /whatsapp/outbox` is how the reply is read.
- [x] `test_harness_s08_duplicate_and_order` — the same webhook twice stores one event. Two messages stored out of arrival order read in provider-timestamp order.
- [x] `test_harness_fixed_offer_replies_with_the_tool_amount` — a text scenario for the 5000 L replacement. The outbox contains `R 4 250` and no other amount.

#### Block B gate

- [x] A scripted conversation of text plus a photo fact produces one quote through the turn loop.
- [x] The harness has posted that turn as Cloud API payloads and read the reply from the outbox.
- [x] A poisoned reply never reaches the outbox.
- [x] `pytest tests/use_cases -q` passes.
- [x] `lint-imports` passes.
- [x] Block C does not start while this gate is red.

### Block C

#### `tests/adapters/test_rls.py`

Written after `design/persistence.md`. You read the policies before the migration runs. Agents do not weaken the test.

- [x] `test_rls_hides_other_tenants` — two tenants. Session A returns only A's quotes, cases, conversations, policies, and audit rows. A missing tenant setting returns nothing.
- [x] `test_audit_is_insert_only` — update and delete as the application role fail. Insert succeeds.
- [x] `test_quote_and_audit_commit_together` — a failure between the quote insert and the audit insert leaves neither row.
- [x] `test_repositories_round_trip_the_aggregates` — a quote with lines, clauses, evidence, an approval, and a schedule. A case with a superseded fact. A conversation with two out-of-order events.

#### `tests/adapters/test_aquasure_seed.py`

- [x] `test_aquasure_seed_matches_fixtures` — loading `seeds/aquasure.yaml` and running the Wednesday fixture cases returns the same rule ids.

## Build

### You, block A — RequestChange and the checker

Implement only what the block A tests describe.

- [x] `quotedesk/application/use_cases/tools/request_change.py`.
- [x] The commitment checker at the path recorded in `design/commitment-checker.md`.
- [x] The block A gate is green.
- [x] `price` still returns discount 0 when the facts carry a discount of 10.

### You, block B — the turn loop, with fakes

Implement only what the block B tests describe.

- [x] `ReceiveInboundEvent` and the gate.
- [x] `UpdateCase`.
- [x] The quiet window, the lock, `RunAgentTurn`, and `HandoverToHuman`.
- [x] `CheckAvailability`, `HoldSlot`, `GetQuoteStatus`, and `CreateDepositLink`.
- [x] `harness/runner.py`, `POST /whatsapp/webhook`, and `GET /whatsapp/outbox`.
- [x] The block B gate is green. S08 and the 5000 L text scenario pass through the harness.
- [x] `GetQuote` still does not call `schedule`.

### You, then agents, block C — persistence and the click-path

You write `seeds/aquasure.yaml` and you walk the browser path. Agents may type the migration and the chat shell after the handoff below. You read the row-level security policies before they are applied.

- [x] The migration matches `design/persistence.md`.
- [x] `tests/adapters/test_rls.py` passes on the local database.
- [x] `tests/adapters/test_aquasure_seed.py` passes.
- [x] The voice note and the tank photo are on disk.
- [x] The click-path below is done by you.

Click-path:

1. Open the web chat for AquaSure.
2. Send a transcript of the 5000 L voice note and upload the tank-on-a-base photo, or the typed equivalent if live transcription is not wired.
3. Receive a reply whose only amount is the quote's amount, with a link to the card.
4. Open the card. See "Fixed quote", the line, the clauses, the rule id WATER-F01, the evidence, and the expiry.
5. Refresh. The same version is still current.

- [x] Live Spark, live SAM, and live Voice Transcribe stay parked when the fixtures are what made this path pass. The card still shows a mask from a recorded fixture.

## Handoff, after the block B gate

Send this once, when block B is green. One check before the migration is applied is enough, and that check is the row-level security policies.

```text
Slice: persistence for the committed models, row-level security, and the AquaSure web chat shell
Design: docs/build/2026-10-31/design/persistence.md, docs/build/2026-10-31/design/click-path.md
Tests: tests/adapters/test_rls.py, tests/adapters/test_aquasure_seed.py. Do not edit them. Do not weaken an assertion.
You may edit: quotedesk/adapters/outbound/persistence/, quotedesk/infrastructure/, the Alembic tree, quotedesk/adapters/inbound/http/ for the web chat
You must not edit: quotedesk/domain, quotedesk/application/ports, quotedesk/application/dto, seeds, tests/unit, tests/use_cases
Done when: the RLS tests pass on the local database at 127.0.0.1:5432, the seed matches the Wednesday fixture rule ids, and lint-imports passes.
Out of scope today: approving a discount, FrameWorks, validate_policy, publish, live WhatsApp, live PayFast, a new card state.
```

- [ ] Handoff sent.
- [ ] Row-level security policies read before they were applied.

## Evening gate

- [x] `pytest -q` passes.
- [x] `lint-imports` passes.
- [x] The 10 percent request is `PENDING_APPROVAL`, and the issued price is unchanged.
- [x] A poisoned reply is absent from the outbox.
- [x] The click-path was walked in the browser, including the refresh.
- [ ] Agent diff contains no edit under `quotedesk/domain/`, ports, DTOs, or seeds.
- [x] `.env` is untracked.
- [x] Slip list below is filled if anything is still red.
- [ ] Sunday's first block is the owner approving that 10 percent, unless this gate says otherwise.

## Slip list

Write one line per red item: id, failing check, and where it moves. A red `RequestChange` or a red commitment check stays here. The web chat does not move to the cut line.

- [x] Slip list reviewed. Empty is fine.

| Item | Failing check | Moves to |
| --- | --- | --- |
| Original voice note and tank photo | `seeds/media/5000l-voice.wav` is a generated tone and `seeds/media/tank-on-base.png` is a generated image. The click-path used the typed transcript and the mask file. | Stays until a real recording and a real photo replace them. |
| Row-level security policies read | The migration is already applied. The owner has not confirmed they read the policies. | Stays with the owner. |
| Handoff sent | This session wrote the persistence and chat work. No separate handoff was sent. | Closed for this session. The box stays open. |
| Agent diff under ports, DTOs, and seeds | This session edited application ports, DTOs, and `seeds/aquasure.yaml`. `quotedesk/domain/` was not edited. | Stays on the evening gate. |
