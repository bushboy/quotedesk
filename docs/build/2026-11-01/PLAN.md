# Sunday 1 November 2026

The owner can approve the waiting discount, publish a policy, and price a FrameWorks job on the same engine. This is the working list for the day. Tick a box only when that item is actually done. The week plan is [QuoteDesk_Build_Plan.md](../QuoteDesk_Build_Plan.md). Designs written today go in [design/](design/) before any test for that artifact.

Saturday's slip list has no red test. Nothing on it moves here. The generated voice note and tank photo stay generated. The owner still has to read the row-level security policies. Those two lines are not Sunday tasks.

**You:** three blocks. Block A is the approval. Block B is FrameWorks `decide`, then validate and publish. Block C is the Excel import, and it starts only after block B's gate is green. Each block is its design, then its failing tests, then the implementation, then the gate. The next block waits.

**WhatsApp builder:** already on the page, from [the Saturday handoff](../2026-10-31/design/whatsapp-simulator-handoff.md). They keep `quotedesk/adapters/inbound/http/templates/chat.html` and `quotedesk/adapters/inbound/http/chat.py`. They do not take a Sunday use case. Sunday does not edit those two files, and it does not add chat states, typing rows, or a second inbound dialect.

**Agents:** after the block A gate is green, the operator console. After the block B gate is green, the deposit field on the editor. They do not edit `quotedesk/domain/`, `quotedesk/application/ports/`, `quotedesk/application/dto/`, `seeds/`, `tests/unit/`, `tests/use_cases/`, or the two chat files.

**Done when:** approving the 10 percent request issues the next version at the discounted total and leaves the pending version as the pre-approval record, a rejection leaves that price unchanged, FrameWorks `decide` returns FAB-R01 for the 6 m by 7 m carport, a draft deposit change does not affect an issued quote until publish, and `pytest` and `lint-imports` are green.

**Out of scope today:** the WhatsApp page, live WhatsApp delivery, live PayFast, Wonder, the impact preview, Afrikaans switched on, Word, PowerPoint, and photo import, a clause word processor, and any change to `price`. `price` still ignores a discount. The visit fee is still not a deposit.

## Confirm decisions, before block A

Re-read these in the week plan. Overturn one there, in writing, before any test. After that they are the rules.

- [x] D6 stays. Issuing version n+1 sets version n to `REVISED`. Both versions remain.
- [x] D9 stays. An approval applies to one version. An approval after `expires_at` does not apply. `RequestChange` does not approve its own exception.
- [x] The week plan's "pending on version 2, approve to version 3" is replaced by Saturday's code. A 10 percent request on an issued version 1 moves version 1 to `PENDING_APPROVAL` and does not append a version. Approve then issues version 2. Version 1 remains, `REVISED`, with its original lines.
- [x] `PENDING_APPROVAL` gains one legal outbound pair, to `REVISED`, so `revise` can run from the waiting version. The other 22 pairs stay. `tests/unit/domain/test_quote.py` changes `22` to `23` in the same change, and the new pair is named. No other pair is added or removed.
- [x] Reject moves that same version back to `ISSUED`. It does not append a version. The lines stay. It does not use `REJECTED`, because the customer already holds this quote.
- [x] The discount on the new version is the reduction `RequestChange` already uses for a percent inside the cap. Approve does not call `price` and expect the percent to be applied.

`Outcome` stays `fixed_offer`, `indicative_range`, `site_assessment`, `escalation`. `Decision` still has no amount. `GetQuote` still does not call `schedule`. Water predicates in `decide` stay as Wednesday left them.

## Design to create

A test starts only after its design file is ticked. Block A before block A tests. Do not write a later block's tests while the current gate is red.

### [design/approve-exception.md](design/approve-exception.md)

- [x] Purpose: the owner decides a waiting change. Approval issues one new version for that request. Rejection restores the issued quote.
- [x] Module paths recorded: `quotedesk/application/use_cases/operator/approve_exception.py`, `quotedesk/application/use_cases/operator/reject_exception.py`, `quotedesk/application/use_cases/operator/list_pending.py`, `quotedesk/application/use_cases/operator/audit_timeline.py`.
- [x] Approve reads the stored `ChangeRecord.requested_discount_percent`. It does not take a new price in the input. `extra` is forbid.
- [x] The input carries the quote id, the pending version, the idempotency key, and `expires_at`. The clock is injected.
- [x] `apply_approval` runs on the pending version first. `at` after `expires_at` raises `PolicyViolation`, code `policy.violation`, sentence `An approval after expiry does not apply.` No version is appended.
- [x] A successful approve calls `revise`. Version 1 becomes `REVISED` at `4250.00`. Version 2 is `ISSUED`. Its line total is `4250.00` reduced by 10 percent, the same rounding `RequestChange` uses under the cap. Version 2's `approvals` stay empty. The approval remains on version 1.
- [x] Applying that approval to version 2 raises. The sentence is `An approval applies to one version.`
- [x] The same idempotency key twice returns the first result and does not create a third version.
- [x] Reject of the same pending version returns state `ISSUED`, total `4250.00`, and one version. The audit action is `quote.change_rejected`.
- [x] The queue is the quotes in `PENDING_APPROVAL` for the tenant in the context, with the requested percent, the cap, the current total, and the version. Tenant B's row is absent from tenant A's list. A quote that has already been approved is absent.
- [x] The timeline returns the write path for one conversation, in record order: quote issued, change requested, approved. Each row has an actor. The existing `AuditEvent` fields stay. `actor` and `at` are added with defaults so Saturday's constructors still build. `conversation_id` is optional. The block A tests use the in-memory unit. They do not add a column to `audit_event`.

### [design/frameworks-decide.md](design/frameworks-decide.md)

- [x] Purpose: the same `decide` prices a fabricator from a second policy. Water rules are not edited to make a FrameWorks case pass.
- [x] Module path recorded: predicates added in `quotedesk/domain/services/decide.py`. Rule ids `FAB-E01`, `FAB-E02`, `FAB-E03`, `FAB-S01`, `FAB-S02`, `FAB-F01`, `FAB-R01`, `FAB-B01`, `FAB-L01`, `FAB-L02`. The fixture policy is `tests/unit/domain/fabricator_policy.py`, version `fab-policy-v1.0`.
- [x] An unknown rule id is still skipped. A policy that matches nothing still raises `PolicyViolation`.
- [x] FAB-E01 matches a claimed approval in text, in a transcript, and in image text, and it beats a fixed offer.
- [x] FAB-E02 matches a cracked lintel and broken glass in place. A hairline mark the extractor did not call a crack does not match.
- [x] FAB-E03 matches possible asbestos. A new freestanding carport without that fact does not match.
- [x] FAB-S01 matches a new opening and a widened opening. A replacement in the existing opening does not match.
- [x] FAB-S02 matches above ground floor and a multi-unit job. A ground-floor single opening does not match.
- [x] FAB-F01 matches a standard replacement at high confidence with a stated or reference size. Medium confidence does not match.
- [x] FAB-R01 matches 6 m by 7 m with the finish unspecified, at medium confidence and at high confidence. Low confidence does not match. Outcome `indicative_range`.
- [x] FAB-B01 matches a budget under the range minimum. Outcome `indicative_range`. The result names the nearest affordable option's item code. The budget alone does not set a site-visit schedule status. `decide` still returns no schedule status.
- [x] FAB-L01 matches low confidence. FAB-L02 matches an unmatched medium case.
- [x] `Decision` still has no amount. No water test changes its rule id.

### [design/policy-publish.md](design/policy-publish.md)

- [x] Purpose: a draft is editable. Publish is a new version. An issued quote keeps the version it was priced on.
- [x] Module paths recorded: `quotedesk/domain/services/validate_policy.py`, `quotedesk/application/use_cases/editor/publish_policy.py`, `quotedesk/application/use_cases/editor/rollback_policy.py`.
- [x] `validate_policy` is a pure function. It does not call a model, read the clock, or publish.
- [x] An unknown `variation_item_code` returns an error that names the clause id.
- [x] A required fact with no question, and a required fact with a blank question, each return an error.
- [x] Price 0, a negative price, deposit percent `-1`, deposit percent `100`, a discount cap above 100, and validity days `0` each return an error. Deposit percent `0` and deposit percent `99` are inside the range the design records.
- [x] A clause containing `{unknown_token}` returns an error. A clause whose tokens are all settings passes.
- [x] One rate-card row VAT-inclusive and one exclusive returns an error. Every row on the tenant basis passes.
- [x] A payload that disables WATER-E01, WATER-E02, WATER-E03, FAB-E01, FAB-E02, or FAB-E03 returns an error from the pure function and from the publish use case. The use-case error is `PolicyViolation`.
- [x] Changing the deposit on a draft leaves `GetQuote` on the published percent. This is the test already named `test_get_quote_uses_the_published_policy_only`. Do not weaken it.
- [x] Publish with a blank reason raises. The same idempotency key returns the same version and does not create two.
- [x] A quote issued under `water-policy-v1.0` still renders v1.0's deposit clause after v1.1 is published. A new `GetQuote` uses v1.1's percent.
- [x] Rollback of v1.0 after v1.1 creates v1.2 with v1.0's content. v1.0 and v1.1 remain readable. Nothing is deleted.
- [x] `seeds/frameworks.yaml` loads to `fab-policy-v1.0` and the same rule ids as the fixture. The loader follows `quotedesk.adapters.outbound.parsers.aquasure`. `decide` is not changed to make the comparison pass.

### [design/rate-card-import.md](design/rate-card-import.md)

The design is written. The tests and the implementation follow it.

- [x] Purpose: an Excel card becomes draft rows. Publish is still block B's use case.
- [x] Module path recorded: `quotedesk/application/use_cases/imports/import_rate_card.py`. The number in a cell is the number stored. A model may only label a column. The design records that the Sunday tests use a fake labeller, not a live model.
- [x] Two `.xlsx` items match the cells, including cents. A label that names the wrong column does not move the number.
- [x] `.xlsm` is rejected before a parse call. `.docm` and `.pptm` stay rejected by the same check, and they are not parsed.
- [x] The same two items as `.csv` and `.xlsx` produce the same rows.
- [x] A missing price, a blank unit, and unit `each` where the job type expects `m2` flag the row. The row is kept.
- [x] A paragraph that is not a price appears in `unmapped_text`.
- [x] The same code at 850 and at 900 is `needs_review`. No merged price.
- [x] After the rows are merged into the draft, the published policy is unchanged.
- [x] An empty file and a file over the size limit each fail with a fixed owner-facing error and leave no partial draft rows. The design records the size limit and the sentence.
- [x] PDF, Word, PowerPoint, and photo are not this file. They stay on the cut line.

## Tests to create

Tests are written failing, against the design files above. They assert the boundary values below. They do not contain the implementation.

### Block A

#### `tests/use_cases/test_approve_exception.py`

Fakes for the quote repository, the change records, the settings, the clock, and the unit of work. No model and no database. Start from a quote `RequestChange` has already moved to `PENDING_APPROVAL` at `4250.00`, requested percent 10, cap 5.

- [x] `test_approve_exception_issues_one_new_version` — approve. Version 2 issued. Its total is the 10 percent reduction. Version 1 is `REVISED` at `4250.00`. The approval sits on version 1. Applying it to version 2 raises.
- [x] `test_approve_expired_request_fails` — `expires_at` before the injected clock. No version 2. Version 1 stays `PENDING_APPROVAL`.
- [x] `test_reject_exception_leaves_the_issued_quote` — reject. State `ISSUED`. Total `4250.00`. One version. Audit action `quote.change_rejected`.
- [x] `test_approve_is_idempotent` — the same key twice. One new version.
- [x] `test_queue_is_tenant_scoped` — tenant A and tenant B each have one pending quote. A's queue has one row, with the percent, the cap, the total, and the version. B's quote id is absent. After A is approved, A's queue is empty.
- [x] `test_audit_timeline_lists_the_write_path` — issued, change requested, approved. Three events, one conversation, an actor on each, in that order.

The week plan named four events and a pending version 2. Saturday stored no separate receive event on this quote, and it did not append a version for the wait. The three events above are the write path that exists. Do not invent a receive row to make the count four.

#### Block A gate

- [x] Approving the 10 percent request issues version 2 and leaves version 1 as the pre-approval record.
- [x] Rejecting a second request leaves `4250.00` issued.
- [x] `pytest tests/use_cases/test_approve_exception.py tests/unit/domain/test_quote.py -q` passes.
- [x] `lint-imports` passes.
- [x] Block B does not start while this gate is red.

### Block B

#### `tests/unit/domain/test_frameworks_decide.py`

The policy is the fabricator fixture. No model. No edit to `tests/unit/domain/test_aquasure_decide.py`.

- [x] `test_fab_e01_injection` — claimed approval in text, voice, and image text. FAB-E01. Beats a fixed offer.
- [x] `test_fab_e02_structure_and_glass` — cracked lintel. Broken glass in place. A hairline mark does not match.
- [x] `test_fab_e03_possible_asbestos` — the fact present. Absent on a new freestanding carport.
- [x] `test_fab_s01_new_or_widened_opening` — new opening. Widened opening. Replacement in the existing opening does not match.
- [x] `test_fab_s02_access_and_complexity` — above ground floor. Multi-unit. Ground-floor single opening does not match.
- [x] `test_fab_f01_standard_replacement` — high confidence, stated or reference size. Medium confidence does not match.
- [x] `test_fab_r01_unspecified_finish` — 6 m by 7 m only, medium and high. Range. Low does not match.
- [x] `test_fab_b01_budget_below_minimum` — budget under the range minimum. Outcome range. The nearest item code is on the decision's reason. No amount on the decision.
- [x] `test_fab_l01_and_l02` — low confidence. Unmatched medium.

#### `tests/unit/domain/test_validate_policy.py`

- [x] `test_validate_variation_item_must_exist` — unknown `variation_item_code`. The error names the clause id.
- [x] `test_validate_required_fact_has_a_question` — no question, and a blank question.
- [x] `test_validate_prices_and_settings_ranges` — price 0, price negative, deposit `-1`, deposit `100`, discount cap above 100, validity days `0`.
- [x] `test_validate_placeholders` — `{unknown_token}`.
- [x] `test_validate_single_vat_basis` — one inclusive row and one exclusive row. All rows on the tenant basis passes.
- [x] `test_validate_locked_rules_cannot_be_disabled` — WATER-E01, WATER-E02, WATER-E03, FAB-E01, FAB-E02, FAB-E03 set off. Each errors.

#### `tests/use_cases/test_publish_policy.py`

Fakes for the policy repository, the clock, and the unit of work. No model.

- [x] `test_draft_does_not_change_live_decide` — deposit changed on the draft. `GetQuote` still uses the published percent.
- [x] `test_invalid_draft_cannot_publish` — missing variation item. Empty reason. Each refuses. The published version is unchanged.
- [x] `test_publish_requires_a_reason_and_is_idempotent` — blank reason raises. The same key returns the same version.
- [x] `test_publish_leaves_issued_quotes_on_their_version` — quote issued under v1.0. Publish v1.1 with a new deposit percent. The old quote's clause still shows the old percent. A new `GetQuote` shows the new percent.
- [x] `test_rollback_republishes_as_a_new_version` — rollback of v1.0 after v1.1 creates v1.2 with v1.0's content. v1.0 and v1.1 remain.
- [x] `test_locked_rule_rejected_by_the_use_case` — disable WATER-E01 through publish. `PolicyViolation`. The published rules still contain WATER-E01.

#### `tests/adapters/test_frameworks_seed.py`

- [x] `test_frameworks_seed_matches_fixtures` — `seeds/frameworks.yaml` loads to the same rule ids as `tests/unit/domain/fabricator_policy.py`.

#### Block B gate

- [x] FAB-R01 is the carport result. A water F01 case is still WATER-F01.
- [x] An issued AquaSure quote keeps its deposit clause after a later publish.
- [x] `pytest tests/unit/domain/test_frameworks_decide.py tests/unit/domain/test_validate_policy.py tests/use_cases/test_publish_policy.py tests/adapters/test_frameworks_seed.py -q` passes.
- [x] `lint-imports` passes.
- [x] Block C does not start while this gate is red.

### Block C

Skip the whole block when block B is red. The floor is Excel. PDF, Word, PowerPoint, and photo are not written.

#### `tests/use_cases/test_import_rate_card.py`

- [x] `test_excel_numbers_come_from_cells` — two items. Cents match. A wrong column label does not move the number.
- [x] `test_macro_files_rejected` — `.xlsm` rejected before a parse call.
- [x] `test_csv_and_xlsx_same_rows` — the same two items.
- [x] `test_import_flags_incomplete_rows` — missing price, blank unit, unit `each` against `m2`.
- [x] `test_import_keeps_unmapped_text` — a non-price paragraph is listed.
- [x] `test_import_conflict_is_not_averaged` — 850 and 900. `needs_review`. No merged price.
- [x] `test_import_does_not_publish` — the published policy is unchanged after the draft merge.
- [x] `test_oversize_and_empty_upload` — empty file, and a file over the limit. No partial rows.

#### Block C gate

- [x] The two Excel rows are on the draft, and the published card is the one from before the upload.
- [x] `pytest tests/use_cases/test_import_rate_card.py -q` passes.
- [x] `lint-imports` passes.

## Build

### You, block A — approve and reject

Implement only what the block A tests describe.

- [x] The one new transition, `PENDING_APPROVAL` to `REVISED`, and the `23` in `test_every_legal_transition`.
- [x] `ApproveException`, `RejectException`, `ListPending`, and `AuditTimeline`.
- [x] The block A gate is green.
- [x] `price` still returns discount 0 when the facts carry a discount of 10.

### You, block B — FrameWorks, then publish

Implement only what the block B tests describe.

- [x] The FAB predicates and `tests/unit/domain/fabricator_policy.py`.
- [x] `validate_policy`.
- [x] `PublishPolicy` and `RollbackPolicy`.
- [x] `seeds/frameworks.yaml` and the loader.
- [x] The block B gate is green.
- [x] A water case still resolves through the Wednesday predicates.

### You, block C — Excel only, if block B is green

- [x] `ImportRateCard` for `.xlsx` and `.csv`, and the macro rejection.
- [x] The block C gate is green, or the slip list names the first red test.

### Agents, after the gates — console and editor

They start the console only after the block A handoff below, and the editor only after the block B handoff. The pages call the use cases. They do not calculate a discount or choose a policy version.

Console, at `GET /console`:

- [ ] The queue shows the ask, the cap, the current total, and the version.
- [ ] Approve shows that version and the percent, then the new version. The button does nothing until those are on screen.
- [ ] Reject leaves the issued total on screen.
- [ ] An empty queue says there is nothing waiting.

Editor, at `GET /editor`:

- [ ] One deposit percent, the validation errors, a reason, and publish.
- [ ] Publish stays disabled while an error is listed.
- [ ] A typed percent and a reason are enough. There is no clause editor.

The handoff for both pages is [design/console-editor-handoff.md](design/console-editor-handoff.md).

## Handoff, after the block A gate

```text
Slice: operator console for the pending 10 percent
Design: docs/build/2026-11-01/design/approve-exception.md
Tests: tests/use_cases/test_approve_exception.py. Do not edit them. Do not weaken an assertion.
You may edit: quotedesk/adapters/inbound/http/ for the console only
You must not edit: quotedesk/domain, quotedesk/application/ports, quotedesk/application/dto, seeds, tests/unit, tests/use_cases, quotedesk/adapters/inbound/http/templates/chat.html, quotedesk/adapters/inbound/http/chat.py
Done when: GET /console lists the pending ask and an approval issues the next version through ApproveException.
Out of scope today: the WhatsApp page, FrameWorks, publish, rate-card import, live WhatsApp, live PayFast.
```

- [x] Handoff sent. [design/console-editor-handoff.md](design/console-editor-handoff.md)

## Handoff, after the block B gate

```text
Slice: policy editor, enough to publish a deposit change
Design: docs/build/2026-11-01/design/policy-publish.md
Tests: tests/use_cases/test_publish_policy.py. Do not edit them. Do not weaken an assertion.
You may edit: quotedesk/adapters/inbound/http/ for the editor only
You must not edit: quotedesk/domain, quotedesk/application/ports, quotedesk/application/dto, seeds, tests/unit, tests/use_cases, quotedesk/adapters/inbound/http/templates/chat.html, quotedesk/adapters/inbound/http/chat.py
Done when: a draft deposit change publishes through PublishPolicy, and an already issued quote still shows the old percent.
Out of scope today: a clause word processor, the impact preview, Wonder, the WhatsApp page, Excel import.
```

- [x] Handoff sent. [design/console-editor-handoff.md](design/console-editor-handoff.md)

## Evening gate

Repair only inside this list. No new artifact. The WhatsApp builder's page is not a gate item.

- [ ] `pytest -q` passes.
- [ ] `lint-imports` passes.
- [ ] From the Saturday quote, a 10 percent request is approved. Version 2 is the discounted quote. Version 1 is still the pre-approval record.
- [ ] A rejection on a second quote leaves the issued total.
- [ ] A deposit change is published. The earlier quote keeps its clause. A new `GetQuote` uses the new percent.
- [ ] FrameWorks facts for a 6 m by 7 m carport return FAB-R01, a range, and no hold.
- [ ] `.env` is untracked.
- [ ] The agent diff contains no edit under `quotedesk/domain/` except the one transition pair, and no edit to the two chat files.
- [ ] Slip list below is filled if anything is still red.
- [ ] Nothing is tagged `submission`.

The week plan's seven-step browser demo stays Monday's rehearsal. Sunday walks the four checks above. Slow media, the sparking photo, and the handwritten note stay on the chat page the other builder owns.

## Slip list

Write one line per red item: id, failing check, and where it moves. A red approval or a red FrameWorks `decide` stays here. Excel moves to Monday only as a repair of a test this day wrote. PDF, Word, PowerPoint, and photo do not move. They are already on the cut line.

- [ ] Slip list reviewed. Empty is fine.

| Item | Failing check | Moves to |
| --- | --- | --- |
| | | |
