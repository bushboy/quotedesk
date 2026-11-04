# QuoteDesk build appraisal, 31 October 2026

Audience: the builder (Cursor or Devin) and the owner. This is a read-only review. No code was changed. Section 7 is the instruction to give the agent.

Snapshot: branch `owner-console` at `04b2751`, 7 commits ahead of `origin/owner-console`, plus uncommitted changes. 128 Python modules in `quotedesk/`, `eval/` and `scripts/`, with 413 functions, 370 methods, 262 classes and 326 module-level names. 430 test functions. The last recorded pytest run (31 Oct, 15:53) had 4 failures; section 2.3 covers what happened to them. The gate ran 54/54 on 31 October against a scripted customer, with no live model.

Compared against: `docs/design/QuoteDesk_Hackathon_Build_Spec.md`, `docs/design/QuoteDesk_Clean_Architecture.md`, `docs/build/production/PLAN.md` (121 of 121 boxes ticked), `docs/build/production/design/planner.md` and `prompts.md`.

## 1. Verdict

The build has moved past the spec in the quoting core:
- a planner chooses the next step;
- facts carry a status (stated, inferred, confirmed);
- quotes price from confirmed facts only;
- SAM 3.1 is now called for real, through `sam_geometry.py`;
- rate-card rows carry `applies_to`, `job_types` and `when`;
- the image reads are trade-aware.

Those are improvements, and the spec should be updated to match them (section 3, "Superseded").

Nothing has been lost without a trace. Every removed function either has a named replacement or was planned for removal. One removal is a policy change made by rewriting tests that were failing, and the owner should confirm it (section 2.3).

The gaps are at the edges the spec promised:
- voice transcription;
- the real WhatsApp sender and the echo listener;
- rate-card upload, rollback and the audit timeline (built and tested, but not reachable from any page);
- most of the policy editor beyond rate-card rows;
- a live-model eval.

## 2. Deletion audit

### 2.1 Files
| Change | Commit | Status |
|---|---|---|
| `adapters/inbound/http/templates/editor.html` deleted | 1c959da | Superseded: the editor was merged into `console.html` ("one page with an activity feed"). OK. |
| `infrastructure/{commercial,stored,rate_cards,tenants}.py` moved to `adapters/outbound/persistence/` | 0c8f45f | Layering fix in line with the architecture doc. `rate_cards.py` became `stored_rate_cards.py`. OK. |
| `eval/conversations/kingdom-doors.yaml` renamed to `oakmere.yaml` | d936f83 | Fictional-tenant fix. OK at HEAD, but see 6.1. |

### 2.2 Functions and classes removed with no same-named replacement (61)
Each group has a stated replacement:

| Group | Removed | Replaced by | Verdict |
|---|---|---|---|
| Rule predicates in `domain/services/decide.py` (`_e01`…`_l02`, `_fab_*`, `_installation_damaged`, `_sized_install`, `_finish_chosen`, `_text_mentions_stand_hazard`) | 0c8f45f | Condition data in `domain/policy/when.py` (`_RULES` keyed by rule ID) | Superseded. But see 4.4: the conditions are still Python. |
| Reply rewriters in `run_agent_turn.py` (`_fabrication`, `_case_values`, `_has_span`, `_has_sheet`, `_carport_measured`, `_carport_question`, `_customer_template`, `_recording`, `_recorded_sized_install`, `_indicative_reply`, `_states_indicative`), `task_for` | efb8a72, 159dd68 | The planner sentence and `_task_for` (per `planner.md`: "the five reply rewriters are deleted") | Planned. OK. |
| `get_quote.py` `_span`, `_match_card`, `_scale_carport` | efb8a72, 0c8f45f | `price._composed` with `_quantity` by unit (per m² and per metre) | Superseded. OK. |
| `image_context.py` `_segment_body`, `_with_masks` | d936f83 | `_sam_body`, `_segment`, `_probe` and `meta/sam_geometry.py` (a real SAM 3.1 call instead of Spark imitating SAM) | Superseded, and fixes an earlier review finding. OK. |
| `plan.py` `_states` | d936f83 | `case_file.status_of` / `derived_status` | Superseded. OK. |
| `console.py` `_page`, `editor.py` `_page`, `_sentences`, `card.py` `_headline`, `demo.py` `_Capacity` | 1c959da, 04e14d2 | The merged console and the Postgres-backed capacity | OK. |
| Tests for the old tenant name | d936f83 | The `oakmere` set | OK. |
| `tests/unit/test_health.py::test_health` | 159dd68 | **None found.** | Check that `/health` still exists and has a test; restore the test if it does. |

### 2.3 Tests rewritten after failing: a policy change to confirm
At 15:53 on 31 October these 4 tests failed:
- `test_blur_does_not_issue_a_fixed_price`
- `test_sam_error_does_not_issue_a_fixed_price`
- `test_blur_or_sam_error_does_not_issue`
- `test_a_sheet_choice_without_a_size_asks_for_one`

In 5f85138 (21:51) they, along with `test_water_f01_requires_high_confidence`, `test_water_l01_low_confidence` and the three five-check confidence tests, were replaced by tests asserting the opposite. For example, `test_a_blurry_photo_still_quotes_a_confirmed_replacement` and `test_a_confirmed_swap_quotes_when_the_photo_disagrees`.

Behind it, `derive_confidence` was cut down to two inputs: `rate_card` and `required_fields`. Photo quality, SAM, agreement and measurement no longer affect the band.

- **Blur or a SAM miss, with the customer having stated or confirmed the facts:** quoting is consistent with the confirm-first design in `prompts.md`. Accept, and record it in the spec.
- **The photo contradicts the customer (`agreement=False`) and a fixed quote still goes out:** this contradicts the spec ("when the photo and the customer disagree, ask one question") and the platform prompt. **Recommend restoring a guard:** a contested fact or `agreement=False` blocks a fixed offer until the customer answers one question.
- **The low-confidence rules can no longer fire.** `confidence=low` now happens only on an unknown rate-card code, so `WATER-L01` and `FAB-L01` are effectively unused. Either redefine "low", or remove the two rules from the seeds with a note.
- **The four photo checks are still computed and stored, but read by nothing that decides.** See 4.3.

### 2.4 Uncommitted working tree
- `README.md`, 4 Alembic migrations and 9 docs show about 1,500 changed lines, but **only line endings changed** for the migrations and README (`git diff --ignore-cr-at-eol` shows nothing for them). Set `.gitattributes` (`* text=auto eol=lf`) before committing, so applied migrations don't look edited.
- Real content changes: short "As of 31 October" notes in 7 design docs, plus `planner.md` and `prompts.md`. Fine to commit.
- Untracked: `docs/build/production/PLAN.md` (commit it), and **two different files named `swap-vs-new.md`**: `production/` (234 lines) and `production/design/` (59 lines). Keep one, or rename one so each has a clear purpose.
- `deployment/` (254 MB) is git-ignored. Good.

## 3. Spec alignment

**Delivered as specified:**
- webhook in the Cloud API format, with deduplication by message ID;
- the outbox in test mode;
- web chat and simulator with media upload;
- quiet-window batching and one turn at a time per conversation (turn ledger, `SKIP LOCKED`);
- case file with sources and contradictions, and several jobs per case;
- the five pure domain functions (`decide`, `price`, `select_clauses`, `schedule`, `check_reply`);
- tools whose commitments come from tool results only;
- quote card, acceptance, deposit link and slot hold;
- the injection gate and per-sender limits;
- the Afrikaans flags (text and voice, off by default);
- the video acknowledgement ("Got your video, having a look");
- tenant per phone number with Postgres row-level security, failing closed;
- owner console with approvals, handovers and the owner brief;
- policy draft and publish;
- the eval gate with history.

**Superseded (better than the spec; update the spec):**
| Spec | Build |
|---|---|
| Agent decides each turn | Planner (`plan_next_step`) decides; the model phrases the step and extracts facts |
| Five-check confidence band | Confirmed-fact readiness (section 2.3 has the one exception to restore) |
| Size bands per item | Units (each, per m², per metre), roles, `applies_to`, `job_types`, `when` per row |
| Generic image extraction | Trade-aware reads (`_CARPORT_READ`, `_TANK_READ`) plus SAM 3.1 per object |
| Separate editor page | Merged console with an activity feed |
| Facts as values | Facts with a status: stated, inferred, confirmed, contested, unknown |

**Partial:**
| Spec | State |
|---|---|
| Policy editor: rate card, commercial settings, scheduling, clauses, rule parameters, job-type facts | The page edits rate-card rows (code, price, unit, role, applies_to, when, job) and the deposit. Clauses, scheduling, rule thresholds and job-type facts are not editable. |
| Draft is "previewed against real cases before publish" | No preview or replay found in `publish_policy.py` |
| Rate-card import from PDF, image, Excel, Word, PowerPoint or text (marked "core, not stretch") | `ImportRateCard` exists with CSV parsing, a column labeller port and macro rejection, and is tested. **No route or console control calls it.** There are no Word, PowerPoint, PDF or image readers. |
| Rollback of a published policy | `RollbackPolicy` is used only by tests. No route. |
| Audit timeline | `AuditTimeline` is used only by tests. |
| Multimodal | Images: done. Video: acknowledgement plus frames. Voice: `transcript` is read from the inbound payload, but **no Muse Voice Transcribe adapter exists**, so a real WhatsApp voice note arrives with no text. |
| Live-number readiness: three passing gate runs | The gate runs a scripted customer ("no live model call"). It proves the planner and templates, not the prompts. |

**Missing:**
- **A real WhatsApp sender.** `container._sender` accepts only `outbox`.
- **The echo listener** (`smb_message_echoes`, off by default), which the spec says should be built but off.
- **Muse Wonder** (stretch).
- **A model registry.** The spec's `models_registry.py` is replaced by config plus `container.py`, which is fine. Update the spec.

## 4. Purpose audit

### 4.1 Modules with no docstring stating their purpose (64 of 128)
`adapters/inbound/http/{quote_card,whatsapp}.py`, `adapters/outbound/channels/outbox.py`, `adapters/outbound/models/{spark,recorded_extraction}.py`, `adapters/outbound/models/baseten/sam_parser.py`, `adapters/outbound/parsers/{aquasure,macros}.py`, `adapters/outbound/persistence/quotes.py`, `application/dto/{agent,audit,changes,inbound,published,tenant,tool_inputs,tool_outputs}.py`, `application/errors.py`, `application/ports/{agent,gate,media,repositories,runtime}.py`, `application/prompts.py`, every module under `application/use_cases/` except those already documented (`conversation/{receive_inbound,run_agent_turn}`, `editor/{publish,rollback}_policy`, `imports/import_rate_card`, `operator/{approve_exception,audit_timeline,list_pending,reject_exception}`, `tools/{accept_quote,check_availability,create_deposit_link,get_quote,get_quote_status,hold_slot,request_change,update_case}`), `domain/case/{case_file,contradictions,facts}.py`, `domain/conversation/events.py`, `domain/policy/{clauses,draft,playbook,rules}.py`, `domain/quotes/{quote,schedule}.py`, `domain/services/{commitments,confidence,injection,price,schedule,select_clauses,validate_policy}.py`, `domain/shared/{errors,ids,money,windows}.py`, `infrastructure/{config,container}.py`.

**Rule to adopt:** each module opens with one sentence: what it owns, which layer it is in, and who calls it.

### 4.2 Code with no caller in production (verified by search)
Framework-registered names are excluded: routes, Pydantic validators and `model_post_init`.

| Name | Where | Recommendation |
|---|---|---|
| `QuoteTables.save_with_audit` | `persistence/quotes.py` | Unused. Delete, or wire it if quotes should be audited (the spec says they should). |
| `resolve_tenant`, `unknown_tenant_sentence` | `persistence/tenants.py` | Unused. Tenant resolution now happens elsewhere. Delete after confirming. |
| `MediaEnricher` port | `ports/media.py` | Unused. `ImageEnricher` is used directly. Either type the container against the port, or delete the port. |
| `AuditLog` port | `ports/repositories.py` | Unused. It belongs with the audit work in 4.3. |
| `_REFUSAL`, `_BLOCKED_WHILE_HELD` | `run_agent_turn.py` | Unused constants. `_BLOCKED_WHILE_HELD` looks like a guard that was meant to be enforced: check whether tools are blocked while a case is held, then wire it or delete it. |
| `RunAgentTurn.acknowledge`, `._speak`, `._close` | `run_agent_turn.py` | Unused methods. Delete. |
| `QuoteClock` | `infrastructure/demo.py` | Unused. Delete. |

**Used only by tests** (production code with no production caller): `RollbackPolicy`, `ImportRateCard`, `AuditTimeline`. These are spec features: wire them up, don't delete them. Also:
- `reject_macros_before_parse`: only reachable through `ImportRateCard`;
- `ScheduleTables`: used only by the RLS test, so check the scheduler's storage path;
- `CaseFile.start_over`: the spec says "start over" should be understood;
- `Conversation.replace_body`, `Quote.set_expiry`, `required_fields_complete`, `demo.Ids`, `demo.TENANT_A`, `demo.Conversations.trail`.

For each, either wire it, or keep it with a docstring saying it is a test helper and move it under `tests/`.

### 4.3 Values computed for nothing
`ConfidenceChecks.agreement`, `.measurement` and `.media_usable` are still computed by `cross_model_agreement`, `measurement_acceptable` and `media_is_usable` in `confidence.py` and the turn, then stored, but `derive_confidence` ignores them. Give them a purpose, for example:
- `agreement=False` blocks a fixed offer (the guard to restore in 2.3);
- `media_usable=False` adds "a clearer photo would help" to the next ask;
- `measurement` sets whether a size is `inferred` or can be suggested.

Otherwise remove them with the tests. Don't leave them half-alive.

### 4.4 Trade-specific code where the architecture says data
- **Rule conditions** live in `domain/policy/when.py` as a Python dict keyed by rule ID (`"WATER-F02": one_of("size_litres", ("2500","5000","10000"))`, `"FAB-S01": …`). An owner who edits a rule in the console can't change its condition, and a third business (doors) needs a code change. **Move each condition into the policy version** (the seed YAML, then the database), using the same `when` vocabulary the rate-card rows already use.
- **Image reads** `_CARPORT_READ`, `_TANK_READ`, `_carport_notes` and `_tank_notes` are in an adapter. Build them from the playbook (job descriptions, facts, options, `look_for`) so a door showroom gets a read without code.
- **`plan.py`** `_sheet_job`, `_sheet_codes`, `_finish`, and the named flags (`new_tank_and_pump`, `sloped_ground`, …) map facts per trade by hand.
- **`parsers/aquasure.py`** is a single-tenant parser.
- In total there are 32 references to trade names or rule IDs inside `domain/` and `application/`.

### 4.5 Names that look duplicated
- `domain/quotes/schedule.py` (scheduling models) and `domain/services/schedule.py` (the `schedule()` function). Both are valid; give each a docstring that names the other.
- The two `swap-vs-new.md` files (2.4).

### 4.6 Size hot spots
- `run_agent_turn.py`: 1,683 lines, and it was 1,117 two days ago.
- `demo.py`: 901 lines.
- `plan.py`: 551 lines.
- `get_quote.py`: 480 lines.

`run_agent_turn.py` mixes the turn loop, tool dispatch, confidence writing, name memory, sentence building and fallbacks. Split it along those seams after the hackathon, not before.

### 4.7 Not checked here
Unused imports and unused local variables inside functions. No linter could be installed in this review environment. Add `ruff` (rules F401 and F841) and `vulture --min-confidence 80` to CI. They will catch these mechanically.

## 5. What is good and must not regress
- The pure domain functions; tools filled in by the turn; failing closed when the store is down.
- Fact status, and pricing from confirmed values only (`get_quote` reads `confirmed`).
- `_checks` now defaults to **not met** when photo-sourced facts exist. This fixes an earlier review finding.
- Real SAM 3.1 calls with a parsed score.
- Row-level security on every table, and tenant resolution from the phone number ID.

## 6. Risks outside the code
1. **The real business name is in the pushed history.** `origin/owner-console` contains it in `docs/reviews/QuoteDesk Implementation Review.md`, and commits a174481 and 159dd68 are already on GitHub. HEAD is clean. Removing it from history means rewriting history and force-pushing, which is destructive and the owner's call. At minimum, remove it from that review doc in the next commit.
2. **The gate is scripted.** Before submission, run it at least once with the live model and save the result separately from the scripted run.
3. **Line-ending churn** makes applied migrations look edited (2.4).

## 7. Instruction for the agent

```
Read docs/reviews/QuoteDesk_Build_Appraisal_2026-10-31.md. Work in this order, one commit per item.

Ground rules
- Do not delete any file, function, class, test or constant unless this report marks it "Delete". For every deletion, add a line to docs/reviews/REMOVED.md: name, commit, reason, replacement (or "none").
- Do not change a test's expected outcome to make it pass. If behaviour is meant to change, say so in the commit message and update the spec section it contradicts.
- Use fictional tenant names only.

1. Add .gitattributes (* text=auto eol=lf) and renormalise, so the Alembic migrations and README show no diff. Commit PLAN.md. Resolve the two swap-vs-new.md files: keep one, or rename them by purpose.
2. Restore a disagreement guard: a contested fact, or agreement=False on a price fact, blocks a fixed offer until the customer answers one confirming question. Add tests: photo disagrees + customer reconfirms → fixed; photo disagrees, no reply → ask. Keep the blur/SAM relaxation for confirmed facts.
3. Give agreement, measurement and media_usable a purpose (as in 4.3), or remove them along with their tests and REMOVED.md entries. Redefine "low" confidence, or retire WATER-L01 and FAB-L01 with a note.
4. Restore a /health test if the route exists.
5. Delete the unused items in 4.2 marked "Delete" (acknowledge, _speak, _close, QuoteClock, _REFUSAL). For _BLOCKED_WHILE_HELD, save_with_audit, resolve_tenant, unknown_tenant_sentence, MediaEnricher and AuditLog: wire them or delete them, and record which.
6. Wire the spec features that are built but unreachable:
   - POST /console/rate-card/import → ImportRateCard → draft rows shown in the console for review. Support CSV and XLSX now; add DOCX, PPTX and PDF readers behind the ColumnLabeller.
   - POST /console/policy/rollback → RollbackPolicy.
   - The audit timeline on the case brief.
7. Add a module docstring to every module listed in 4.1: one sentence on what it owns, its layer and its caller. Add a docstring to every public class and function that lacks one.
8. Add ruff (F401, F841) and vulture (min-confidence 80) to the dev dependencies and CI. Fix or allow-list every finding, with a reason.
9. Voice: add a Muse Voice Transcribe adapter behind a port, used when an audio event has no transcript.
10. Move the rule conditions out of when.py's _RULES dict into the policy version (seed YAML, then database), using the same when vocabulary. when.py keeps only the evaluator. Gate results must not change.
11. Build the image read from the playbook (job descriptions, fact options, look_for), instead of _CARPORT_READ and _TANK_READ.
12. Run pytest and the gate. Then run the gate once with the live model, and save it as eval/results/gate-live.json.

Report back: test count before and after, gate results (scripted and live), and the REMOVED.md contents.
```
