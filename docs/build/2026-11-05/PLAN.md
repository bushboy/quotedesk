# Remaining work

Written 1 November 2026 from the [31 October appraisal](../../reviews/QuoteDesk_Build_Appraisal_2026-10-31.md) and the decisions made after it. Tick a box only when that item is actually done. One commit per numbered section. A design box is ticked when the design file exists. A test box is ticked when the test fails for the reason named here, or passes once the behaviour is in. A gate box is ticked when that behaviour has been seen.

The `/health` route already has tests. The `agreement` flag stays out of quoting. Those two appraisal items are closed in the first section and are not rebuilt.

## Closed

- [x] Leave `/health` as it is. `test_health_reports_an_explicit_memory_store` and `test_health_is_unavailable_when_postgres_is_down` already cover the route.
- [x] Leave `agreement` out of the quote decision. It records whether SAM drew a mask for a Spark object. A fixed quote waits for the customer to confirm the replayed spec.

## Rules for the open work

- Media assists. A photo can suggest a size, a material, or a fault, and it can be unreadable. The priced value on a fixed quote is one the customer has confirmed.
- Before a fixed quote, the agent reads the whole spec back and waits for a yes. The spec is the price facts: size, material, base or opening, and any clash already settled.
- A clash between the customer's words and other evidence is shown once. The side they choose is stored, with the value, and a later turn uses it.
- A blurry or unreadable photo is one sentence plus an offer of another picture.
- If they do not confirm the spec, or a required fact is still open, the result is a price range or an escalation.
- `ImportRateCard`, `RollbackPolicy`, and `AuditTimeline` stay. They are wired in section 5.
- Fictional tenant names only. A test's expected outcome changes only when this plan says the behaviour changes, and the spec section that contradicts it is updated in the same commit.
- `run_agent_turn.py` stays one file.

## 1. Line endings and the stray notes

- [x] Add `.gitattributes` with `* text=auto eol=lf`.
- [x] Renormalise, so the Alembic migrations and `README.md` show no content diff.
- [x] Commit `docs/build/production/PLAN.md`.
- [x] Keep one `swap-vs-new` note. Rename the other so each file has one purpose, or delete the duplicate and record it in `docs/reviews/REMOVED.md`. The checklist stays `docs/build/production/swap-vs-new.md`. The price design is `docs/build/production/design/applies-to-price.md`.

## 2. Spec replay and contradiction record

Design before tests, in `docs/build/2026-11-05/design/spec-replay.md`.

- [ ] A fixed quote is sent only after the customer confirms the replayed spec.
- [ ] The replay names every price fact and any settled clash.
- [ ] A clash stores both sides, the value, and which side the customer confirmed. A later turn does not ask it again unless new evidence arrives.
- [ ] An inferred photo size stays off the quote until the customer confirms it in the replay.
- [ ] No confirmation, or a required fact still open, yields a price range or an escalation.
- [ ] Test: replay, then yes, issues the fixed quote.
- [ ] Test: a photo size that differs from the customer's words is asked once, the choice is kept, and the quote uses that value.
- [ ] Test: no confirmation yields a range or an escalation, and no fixed total.
- [ ] Update the spec section that still says a photo disagreement only lowers a confidence check.

## 3. Blur notice, then retire the unused photo checks

This starts after section 2 is green, because the replay replaces what `agreement` and `measurement` were standing in for.

- [ ] A blurry or unreadable photo tells the customer and asks whether they have another picture. `media_usable` is that notice.
- [ ] A confirmed spec still quotes when the photo is blurry or SAM misses. The existing blur and SAM tests stay.
- [ ] Remove `agreement` and `measurement` from the quote path, and add a `REMOVED.md` line for each: name, commit, reason, replacement.
- [ ] Retire `WATER-L01` and `FAB-L01`, with a note. An unconfirmed spec is a range or an escalation.
- [ ] Update the tests and the spec section those two rules came from.

## 4. Record the deletions already made

`acknowledge`, `_speak`, `_close`, the `_closed` set, `_REFUSAL`, `_BLOCKED_WHILE_HELD`, `QuoteClock`, `save_with_audit`, `resolve_tenant`, and `unknown_tenant_sentence` are already gone from the working tree. The live audit insert in `stored.py` and `open_tenant` stay.

- [ ] Add `docs/reviews/REMOVED.md` with one line per deletion: name, commit, reason, replacement or "none".
- [ ] Delete the unused `MediaEnricher` port and record it.
- [ ] Delete the unused `AuditLog` port and record it.
- [ ] Run the turn, health, and tenant tests. They stay green.

## 5. Reach the console features that are already built

- [ ] `POST /console/rate-card/import` calls `ImportRateCard`.
- [ ] CSV upload works, and the draft rows appear in the console for review.
- [ ] XLSX upload works through the same review.
- [ ] `POST /console/policy/rollback` calls `RollbackPolicy`.
- [ ] The case brief shows the audit timeline from `AuditTimeline`.
- [ ] Exercise each path in the browser: import, review the draft, roll back, and read the timeline.
- [ ] DOCX, PPTX, and PDF readers sit behind `ColumnLabeller` after CSV and XLSX are green.

## 6. Module docstrings

One sentence each: what the module owns, which layer it is in, and who calls it. Then a docstring on every public class and function in those modules that lacks one.

- [ ] `adapters/inbound/http/quote_card.py`, `whatsapp.py`
- [ ] `adapters/outbound/channels/outbox.py`
- [ ] `adapters/outbound/models/spark.py`, `recorded_extraction.py`, `baseten/sam_parser.py`
- [ ] `adapters/outbound/parsers/aquasure.py`, `macros.py`
- [ ] `adapters/outbound/persistence/quotes.py`
- [ ] `application/dto/` modules named in appraisal section 4.1
- [ ] `application/errors.py`
- [ ] `application/ports/agent.py`, `gate.py`, `media.py`, `repositories.py`, `runtime.py`
- [ ] `application/prompts.py`
- [ ] `application/use_cases/` modules that appraisal section 4.1 still lists as undocumented
- [ ] `domain/case/case_file.py`, `contradictions.py`, `facts.py`
- [ ] `domain/conversation/events.py`
- [ ] `domain/policy/clauses.py`, `draft.py`, `playbook.py`, `rules.py`
- [ ] `domain/quotes/quote.py`, `schedule.py` (the models; name `domain/services/schedule.py` in the sentence)
- [ ] `domain/services/commitments.py`, `confidence.py`, `injection.py`, `price.py`, `schedule.py`, `select_clauses.py`, `validate_policy.py`
- [ ] `domain/shared/errors.py`, `ids.py`, `money.py`, `windows.py`
- [ ] `infrastructure/config.py`, `container.py`

## 7. Ruff and vulture

- [ ] Add ruff, rules `F401` and `F841`, to the dev dependencies and CI.
- [ ] Add vulture at min-confidence 80 to the dev dependencies and CI.
- [ ] Fix or allow-list every finding. An allow-list entry includes the reason.

## 8. Voice

- [ ] Add a Muse Voice Transcribe adapter behind a port.
- [ ] An audio event that already has a transcript skips the adapter.
- [ ] An audio event with no transcript is transcribed, and that text is what the turn reads.
- [ ] A transcription failure asks the customer to type. It does not invent a transcript.

## 9. Rule conditions as policy data

- [ ] Each condition now in `when.py` `_RULES` moves into the policy version: seed YAML, then the database, using the rate-card `when` vocabulary.
- [ ] `when.py` keeps the evaluator only.
- [ ] The scripted gate is unchanged.

## 10. Image read from the playbook

- [ ] The image read is built from the playbook: job descriptions, fact options, and `look_for`.
- [ ] `_CARPORT_READ` and `_TANK_READ` are removed, with `REMOVED.md` lines.
- [ ] The notes can be named in the spec replay. They still do not set the priced value.

## 11. Suite and gates

- [ ] `pytest` is green. Record the count before this plan and the count after.
- [ ] The scripted gate is green. Record the result.
- [ ] One live-model gate is saved as `eval/results/gate-live.json`.
- [ ] `docs/reviews/REMOVED.md` lists every deletion from this plan.

## Still outside this plan

The real WhatsApp sender and the echo listener (`smb_message_echoes`) are still absent. They are not a section here.
