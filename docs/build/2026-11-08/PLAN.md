# Owner console

Written 1 November 2026, from a read of `owner-console` at `12616fd` plus the uncommitted changes, run against a fresh Postgres. Tick a box only when that item is actually done. One commit per numbered section.

The console becomes a product app with tabs, and it can read its numbers out loud. No quote changes: this plan does not touch `decide`, `price`, `get_quote`, the planner, the prompts, or the quote sentences.

## Rules

- The console reads quotes. It never creates, prices, or changes one.
- Every number on screen and every spoken number comes from one read-only use case, `OwnerSummary`. The page does not add up totals itself.
- Approve, reject, release, publish, import, and rollback keep using the use cases they use today.
- The owner never sees a raw error, SQL, or a stack trace. A friendly sentence is shown and the detail is logged.
- Speech starts in the browser (`speechSynthesis`). No new paid service is called in this plan.
- Fictional tenants only. Existing console tests change only where this plan moves a section to another tab.

## 1. Check before the demo

- [x] Find out why a customer's first quote shows "Version 2" on the console. Fix it, or write down why it is right.
  - Why: in one turn `get_quote` issues version 1, then revises it, so version 1 is stored as REVISED and version 2 as ISSUED at the same moment. That is quote logic, so it is left alone. The Quotes table shows the version only when it is above 1, and the case page says "revised 1×".
- [ ] `python-multipart` is installed where the demo runs. The rate-card upload returns 500 without it. (It is in `pyproject.toml`. Check the demo machine's venv.)
- [x] A fresh database built with `alembic upgrade head` starts with `store=postgres` and no raw error on `/console`.

## 2. App shell and tabs

- [x] A shared shell: business name, the signed-in user, sign-out.
- [x] Tabs: Today, Inbox, Quotes, Customers, Rates & policy, Settings. Each has its own route under `/console`.
- [x] Inbox shows a count badge when something waits for the owner.
- [x] The existing sections move into their tabs. No section stays on one long page.
- [x] Start from `owner-app-tabs.patch` (Today, Quotes, Customers, Rates & policy), rebased onto this branch. (Built fresh on this branch instead; that patch was too far behind.)
- [ ] `/editor` and the old `#policy`, `#approvals`, `#handovers`, `#cases` links redirect to the right tab. (`/editor` and `/console?published=` redirect. A `#fragment` never reaches the server, so the old anchors still open Today.)

## 3. OwnerSummary and the Today tab

- [x] A read-only `OwnerSummary` use case takes a tenant and a date range (SAST) and returns:
  - [x] new enquiries (customers and messages),
  - [x] quotes sent, their value, and deposits due,
  - [x] deposits paid,
  - [x] inspections offered and booked,
  - [x] handovers and approvals waiting, with the oldest wait.
- [x] A range quote counts by its stored range, not R 0.00.
- [x] Today shows these as tiles, then the approvals queue, then a short timeline.
- [x] A switcher for Today, Yesterday, and This week.
- [x] `GET /console/summary` returns the same numbers as JSON, plus one sentence to speak.
- [x] Tests: the tiles and `/console/summary` agree, two tenants never mix, and an empty day shows zeros and an empty state.

## 4. Read it to me

- [x] The spoken sentence names each number once, says rand amounts in words ("sixteen thousand six hundred and fifty rand"), and gives times in SAST.
- [x] A name is spoken only when it is a real contact name, not the simulator default. (The summary speaks no names at all.)
- [x] "Read today's summary" on Today, plus a read button on each tile.
- [x] Pause, stop, and speed controls.
- [x] The words being spoken are shown as captions in an `aria-live` region.
- [x] No voice in the browser shows the sentence as text and a note, not an error.
- [x] Tests: the sentence for a known day, rand in words at the boundaries (R 0, R 1, R 1 000, R 16 650.50), and no unsure name is spoken.

## 5. Quotes, Customers, and Inbox tables

- [x] Quotes: quote id, customer, item summary, amount, deposit, status badge, sent, expiry. The outgoing WhatsApp text and the rule code move to the detail view.
- [x] Customers: name or number, last message, message count, latest quote, status.
- [x] Inbox: escalations, inspections, and approvals in one queue. Customer, what they want, amount, and time waiting.
- [x] Labels are words in Title Case ("Quote issued", "Escalated"), not stored codes.
- [x] Long text is cut with a link to the full view.
- [ ] Search, status filter, and paging on each table. (Done on Quotes and Customers. The Inbox has none yet.)
- [x] Every table has an empty state.

## 6. Case page

- [x] Replaces the plain-text brief at `/console/brief/{conversation_id}`.
- [x] Header: customer name, number, status, first contact.
- [x] What they want, in one sentence.
- [x] Facts with their source (said, photo, owner), and what is still missing.
- [x] Photos, the rule that fired and why, and the quote or inspection.
- [x] The audit timeline and the conversation.
- [x] Actions: Approve, Reject, Release to the assistant, Open in WhatsApp.

## 7. Rates & policy tab

- [x] The rate card is a table grouped by role: Product, Frame, Hardware, Installation.
- [x] Add, edit, and remove rows in place.
- [ ] Upload shows the rows it read before they go into the draft. (For now the rows go into the draft and are listed with an Undo button. Nothing goes live until you publish.)
- [ ] Quote terms (deposit, validity, discount cap, site visit fee) and rule switches, with safety rules locked on. (Only the deposit can be edited on this branch.)
- [x] Publish needs a reason.
- [x] Version history lists every publish. Restore is a button on a row, with a confirm step, not a typed version id. (The history and its reasons are kept in memory until the app restarts.)

## 8. Sign-in and audit

- [x] Every `/console` route needs a signed-in owner. (Set `OWNER_PASSWORD`. Unset leaves sign-in off and shows "Sign-in off".)
- [x] Approve, reject, release, publish, import, and rollback record who did it and when. (Kept in memory until the app restarts.)
- [x] Settings shows the business details and who has access.

## 9. Finish

- [x] Works on a phone: tabs collapse, tables become cards.
- [x] Today and Inbox refresh on their own without losing a half-filled form.
- [x] One visual style: type, spacing, badges, buttons.
- [x] `pytest` is green and `lint-imports` passes.
- [ ] A click-path from a fresh database: a customer writes in, Today counts it, the summary is read out, approve in Inbox, edit a price, publish, restore the old version.
