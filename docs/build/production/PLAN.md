# QuoteDesk production plan

Written from the 30 October 2026 implementation review. That review's improvement table is the sequence. Stage 1 is steps 1 and 2. Stage 2 is steps 3 to 7, one increment at a time, each leaving the running app working.

The half-day sizes in the review are hackathon estimates. This plan keeps the order and drops the sizing. A slice is done when its exit gate is green, not when the afternoon ends.

Tick a box only when that item is actually done. A design box is ticked when the design file exists. A test box is ticked when the test fails for the reason the design names, or passes once the slice is implemented. A gate box is ticked when that behavior has been seen, not when the code looks finished. The next slice waits until the current gate is green.

The numbered lists inside the review (robustness 1 to 6, policy 1 to 7) are absorbed by the improvement table. "Recommendations 1 and 2" in this plan means that table, not those inner lists.

## What is wrong, and why this order

The domain core is sound: `decide()`, `price()`, `select_clauses()`, and `check_reply()` are pure, and the layer boundaries that import-linter can see still hold. The failures are around that core.

A customer can get no reply. `RunAgentTurn.execute` closes a batch after an empty model reply, and any exception skips `_close`, so the worker in `container.py` calls the model again every 0.25 seconds. Tool errors and the refusal sentence are sent as if they were answers. A database outage in `open_thread` installs the in-memory app, so a lead accepted during the outage is gone on restart. Message status and photo enrichment live on the use-case instance (`_closed`, `_seen`, `_change_key`).

Business knowledge is in the wrong layer. Prompts are chosen by matching "water tank" or "carport" in the trade name. Reply text is rewritten by trade heuristics after the model speaks. Required facts for anything except a tank replacement are an empty tuple on `Catalog`. A second system prompt in the Spark adapter overlaps the first. Adding a business means editing code.

Later work (a planner, inspection booking, rate-card units, rules as data, a third tenant) is unsafe until a turn cannot go silent and the business is data on the policy version. That is stage 1. Everything else builds on those two facts.

## Confirm decisions, before slice 1.1

Overturn one by editing it here, in writing, before any test for the slice it governs. After the box is ticked, it is the rule.

- [x] Memory is a test double. The harness and unit tests keep an explicit in-memory composition. A process started against Postgres never installs that composition because a connection failed. A down database is a 503 on the webhook and the live chat, after the signature check and before any write.
- [x] A closed batch ends as one outcome and one outbound message. `execute` returns a `TurnOutcome`. It does not finish by logging "no front-end reply" and marking the batch handled.
- [x] The stage 1 failure sentence is the existing handover sentence, and the outcome is escalated. The planner does not exist yet. This slice does not invent a new sentence per trade. Increment 3 replaces that sentence with the planner's own sentence.
- [x] The playbook is part of the policy version. Draft, publish, and rollback already exist and carry it. A published version is immutable. The playbook is not a side file and not a Python constant.
- [x] Stage 1 changes where the prompt comes from, not what AquaSure and FrameWorks are told. The trade-name matcher and the two hint constants are deleted. The application renders one prompt from the published playbook. A characterization test holds the rendered prompt to today's instructions for those two businesses. Reply-rewriting heuristics stay until increment 3 and are not extended.
- [x] One platform prompt, owned by the application layer. The model adapter transports it. Business rules leave `spark.py`.
- [x] New tables are adapters. They live in `adapters/outbound/persistence/`, with row-level security, and `infrastructure/container.py` only wires them. The move of the older Postgres modules is increment 6. Stage 1 does not add repositories under `infrastructure/`.
- [x] Strict fact validation waits for the planner. Stage 1 stores typed fact definitions and the prompt names the canonical keys. `update_case` rejects unknown keys and aliases in increment 3, in the same change that tells the model those keys. Rejecting aliases in stage 1, while the old prompt still invites them, would escalate customers for a key the prompt still teaches.
- [x] WATER-E02 stays as published. The seed already maps it to a site assessment. No slice retargets it in code. An owner changes it by publishing a policy.
Overturned for increment 6. There is an expression language over typed facts. The operators are `all`, `any`, `equals`, `in`, `greater_than`, `is_missing`, and `is_unknown`. One pure function evaluates them. `decide()` does not branch on the business. Safety rules stay locked templates: their wording can be edited, and their conditions cannot.

- [x] Build-plan decision D1 is overturned at increment 6, and only there. D1 says there is no expression language. Increment 6 adds one, over typed facts, with safety rules kept as locked templates whose wording can still be edited. Do not start that language early. Tick this box again, with the overturn written above it, before increment 6 tests.
- [x] A third business is not given a live number in stage 1. A playbook draft may be written from a conversation with the owner. It is served only after increments 3 and 4 are green and its evaluation set has passed three times. The review's note that steps 1 and 2 are enough for a Saturday demo is the hackathon path. This plan does not take it.
- [x] The existing architecture rules stay. Dependencies point inward. Money is `Decimal` ZAR. Every write is one use case and one transaction, with the audit event in that transaction. Tenant context is an argument. The domain does not read the clock, the environment, or the network.
- [x] An escalated conversation stays escalated until the owner releases it in the console. While it is escalated, the agent still answers each new customer message with one short acknowledgement ("Thanks, I've added that for the team."), records any new facts, and refreshes the owner brief. It does not call `get_quote`, `request_change`, `hold_slot`, or `create_deposit_link`. Releasing the conversation returns it to the normal turn.
- [x] An empty model reply is retried once, with a nudge to answer the customer in one sentence, before it escalates. A greeting or small talk must not land in the owner's escalation list. From increment 3, tool arguments that are not valid JSON go back to the model as an error result for one retry inside the tool loop; only a second failure escalates. In stage 1 they escalate directly, as a stopgap.
- [x] The planner works per job from increment 3. `plan_next_step` returns one step for the conversation, chosen from the per-job steps by a fixed order (escalate, then inspection, then ask, then quote). Increment 5 adds per-job pricing and decisions; it does not reopen the planner.
- [x] Each escalation sends the owner one immediate notification: a WhatsApp message to the owner's own number in the playbook profile, falling back to email. One notification per escalation, never repeated. This is not a reminder scheduler. Overturn here if the owner prefers the console only.
- [x] Playbook text is owner-written data. The platform prompt renders it inside a fenced reference block, marked as business information and not as instructions, and `validate_policy` caps each field's length at 4000 characters. A playbook line that reads as an instruction to the assistant has no more authority than a customer message.
- [x] Inspections use the existing capacity table with job type `inspection`. There is no second calendar.
- [x] Evaluation starts in stage 1, not at the end. Conversation sets are drafted from the seeds during slice 1.4. A small set (ten conversations per business) runs after increment 3 and gates increment 4. Increment 7 remains the full release gate.

## Hackathon cut line

Submission closes 4 November 2026 at 21:00 ET (about 04:00 on 5 November in Johannesburg). The video and README are recorded on 3 November. This plan keeps its order; this section says how far it reaches by then.

- **In the submission:** stage 1 (slices 1.1 to 1.4), increment 3, the minimum of increment 4 (`book_inspection`, `escalate_to_owner`, the owner brief, the `unknown` fact state and the two-attempt limit, the escalation notification), and the small evaluation set with its numbers in the README.
- **After the submission:** the rest of increment 4 (console list polish, out-of-scope notes), increment 5, increment 6, and the full increment 7 gate.
- **README:** states plainly that rate-card units, rules as data, and routing by phone number are the next increments. A stated roadmap is better than a half-built increment.
- **Saturday 31 October, Oakmere Doors:** demo AquaSure or FrameWorks as they run. Show the door rate card as a sample of what would be set up. Leave with their job types, prices, inspection rules and common questions. That is the input to their playbook; it is not served before increment 7.

If a slice is not green by 2 November, cut from the bottom of the "in the submission" list, never by skipping a gate.

## Stage 1 — a turn always ends, and the business is data

Four slices. Each ends with `pytest`, `lint-imports`, and the current click-path on AquaSure and FrameWorks. Do not start the next slice on a red suite.

### Slice 1.1 — fail closed

Removes the silent memory fallback (review finding A7, robustness path R5).

`open_thread` today catches a database error, logs `source=memory`, and returns nothing. `create_app` then starts the in-memory app. The same catch exists for rate cards and for tenant lookup, which falls back to the hard-coded profile.

- [x] A configured database that cannot be reached does not install the memory stores.
- [x] The webhook keeps 403 for a bad signature and 400 for a malformed body. If the store is down, it returns 503 and writes nothing.
- [x] The live chat returns the same 503. The harness still constructs memory on purpose and still runs without Postgres.
- [x] `/health` on the live app reports the store. A down database is not `ok`.
- [x] The worker does not run turns against memory when this process was started against Postgres.
- [x] A caught database error while loading the tenant or the rate card is the same failure, not a built-in row.

Slice 1.1 gate:

- [x] Stop Postgres, post a signed webhook, receive 503, start Postgres, and find no conversation row for that message.
- [x] The harness still passes without a database.

### Slice 1.2 — durable turn ledger

Removes process state on the use case (A8, R6) and makes the send idempotent (robustness item 6).

`RunAgentTurn` remembers handled messages, enrichment results, and the last change key on the instance. Startup calls `acknowledge()` so a restart treats stored messages as already answered. Two workers would both answer.

- [x] `conversation_event` gains a status: `pending`, `claimed`, `answered`, `escalated`, `failed`.
- [x] An `enrichment` table, keyed by tenant and provider message id, with row-level security. A later turn reads it and does not call the image models again.
- [x] The outbound row carries the batch id, unique per tenant and batch. It is inserted before the channel send, as `unsent`, then marked `sent`. A restart sends an `unsent` row once and does not call the model again for a batch already `answered` or `escalated`.
- [x] The worker claims `pending` rows with `FOR UPDATE SKIP LOCKED`. A second worker cannot claim the same batch.
- [x] The Postgres path does not use `_closed`, `_seen`, `_change_key`, or startup `acknowledge()`.

Slice 1.2 gate:

- [x] Kill the process after the outbound insert and before the send, restart, and observe one customer message.
- [x] Kill during enrichment, restart, and observe the stored extraction reused.
- [x] Two workers produce one reply.

### Slice 1.3 — the turn guard

Removes the six ways a customer gets silence or a meaningless reply (R1 to R4), given that R5 and R6 are already closed.

Today an empty model reply is logged and the batch is closed with no send. An exception never closes the batch, so the 0.25 second loop calls the model forever. Invalid tool JSON becomes "That tool is not available." A commitment check that fails twice becomes "I can only repeat what the quote says."

- [x] Add `TurnOutcome`: `asked`, `quoted`, `inspection_offered`, `inspection_booked`, `escalated`, `answered`. `execute` returns one. The worker stores it on the batch.
- [x] One exception boundary. `InvalidTransition`, `PolicyViolation`, a model failure after the single retry, and tool arguments that are not valid JSON all become `escalated`. The customer receives the existing handover sentence. The error is stored on the escalation record and in the log, not in the customer text.
- [x] The model transport retries a timeout or an HTTP 5xx once, then returns a typed failure. The worker polls `pending` rows only. It does not select a batch it has already escalated.
- [x] The three "Turn produced no front-end reply" paths retry the model once with a nudge to answer in one sentence. If the retry is also empty, they send the handover sentence and record `escalated`. They do not close a batch in silence.
- [x] A message on an escalated conversation gets the acknowledgement sentence, its facts are recorded, and the brief is refreshed. No pricing or booking tool runs. The owner can release the conversation from the console.
- [x] Neither the tool-error sentence nor the refusal sentence is sent. Until increment 3, a failed commitment check uses the handover sentence as well.

Slice 1.3 gate:

- [x] Each of those paths produces one outbound message and one stored outcome.
- [x] A thrown `InvalidTransition` does not call the model on the next tick.
- [x] No customer text is the tool-error sentence or the refusal sentence.
- [x] The current priced click-path still quotes.
- [x] A greeting whose first model reply is empty gets a reply on the retry and is not escalated.
- [x] A second message after an escalation is acknowledged, adds to the brief, and does not call `get_quote`.

### Slice 1.4 — the playbook on the policy version

Removes prompts chosen by trade name (A1), required facts living on the demo catalog (A4), the second system prompt (A5), and the data side of the hard-coded tenant list (A9). It does not remove the reply heuristics (A2). That is step 3.

The playbook is a frozen domain model with no I/O:

| Part | Contents |
| --- | --- |
| Profile | Name, trade, area, hours, tone, languages, what the business does not do |
| Job types | Description, the rate-card items it can use, how it is priced, what installation and delivery add |
| Facts | Key, type (`number`, `choice`, `yes/no`, `text`), unit, allowed values, the question, whether a photo can answer it, whether it is required |
| Inspection triggers | Plain-language condition, the existing rule id, the fee |
| Escalation triggers | Plain-language condition, the existing rule id |
| Common questions | Delivery areas, lead times, payment methods, showroom address |

Triggers name a rule that already exists. They do not grow a condition language. That is increment 6.

- [x] `PublishedPolicy` and `PolicyDraft` include the playbook. `validate_policy` checks that every required fact has a question, every job-type item code exists on the rate card, every trigger names a rule on the policy, and fact keys are unique per job type.
- [x] Publish and rollback carry the playbook. Publishing a change and rolling it back restores the previous questions.
- [x] The AquaSure and FrameWorks seeds are taken from `AGENT_TASK`, `WATER_HINTS`, `FRAME_HINTS`, and `Catalog.required`. FrameWorks gains required facts. Today it has none.
- [x] `task_for` and the trade-name match are deleted. The application renders one platform prompt from the published playbook and passes it to the adapter. `INSTRUCTIONS` in the Spark adapter no longer states business rules.
- [x] `Catalog.required` reads the published playbook.
- [x] A characterization test holds the AquaSure and FrameWorks prompts to today's instructions. A difference is a written change in this plan, not a silent rewrite.
- [x] `_carport_question`, `_indicative_reply`, `_recording`, `_recorded_sized_install`, and `_fabrication` stay, are not extended, and are deleted in increment 3. Tests that encode them stay green and are rewritten in that increment, not weakened here.
- [x] The prompt renders playbook text inside a fenced reference block, and `validate_policy` caps each playbook field's length.
- [x] Draft ten evaluation conversations per business from the seeds: expected outcome, expected rule id, required facts, phrases that must not appear. They run after increment 3.

Written difference: the previous AquaSure and FrameWorks hint sentences are unchanged. They sit inside a fenced business block, under a line that marks them as owner data rather than instructions. Each playbook field is capped at 4000 characters.

Slice 1.4 gate:

- [x] A business whose trade name contains neither "water tank" nor "carport" still receives its own questions from its published playbook.
- [x] FrameWorks has required facts.
- [x] Rollback restores the previous playbook.
- [x] Both current click-paths still complete.
- [x] `pytest` and `lint-imports` are green.

Stage 1 is finished when those four gates are ticked. It is not finished by pointing a phone number at a third business.

## Stage 2 — one increment at a time

The next increment starts only when the previous exit gate is green. The design for an increment is written before its tests. The domain model and the ports are specified before the adapter and the migration.

### Increment 3 — the planner and the tool loop

Review step 3. Removes the reply heuristics (A2) and the use case reading another use case's private cases (A10).

Code decides the next step. The model extracts facts from the latest messages and phrases that step.

- [x] `plan_next_step(case, playbook, policy)` is a pure domain function. It returns exactly one of: ask for a named fact, ready to quote, inspection needed, or escalate, with the reason. It plans per job and returns the conversation's step by the fixed order in the decisions above.
- [x] The platform prompt states that step and renders the playbook. It does not ask the model to decide the step.
- [x] Delete the five reply rewriters in the same change. Rewrite the tests that encode them so they assert the planner's step. Do not weaken them to keep the old strings.
- [x] The server binds `conversation_id`, `job_id`, and `quote_id`. Those fields leave the tool schemas, so the model cannot invent them.
- [x] A turn makes at most four model calls. Each tool result goes back as a `function_call_output` item, not as another copy of the whole user message.
- [x] Tool arguments that are not valid JSON, or that fail their input model, go back to the model as an error result for one retry. A second failure escalates.
- [x] If the final text is empty or fails `check_reply`, send the planner's sentence for that step. This replaces the stage 1 handover sentence on those paths. A real exception still escalates with the handover sentence.
- [x] Set reasoning effort on the adapter: low for phrasing, medium for extraction. Record latency.
- [x] Inject `CaseFileRepository`. Delete the read of `self._handover._cases`.
- [x] `update_case` accepts only keys defined for the job type, normalizes units, and rejects aliases. `GetQuote` stops accepting `size_litres` or `tank_size` and the other paired names.

Increment 3 gate:

- [x] A missing fact produces that fact's question for both businesses, with no trade branch in the use case.
- [x] The scripted AquaSure replacement still issues the fixed price from `get_quote`.
- [x] An empty model reply sends the planner sentence, and that sentence contains no price, date, or inclusion the tool did not return.
- [x] A conversation with two jobs gets one step, chosen by the fixed order.
- [x] Latency on text-only turns, measured on the evaluation set: median under 8 seconds, slowest 10 percent under 15 seconds.
- [x] The small evaluation set (ten per business) has run, its numbers are recorded, and no conversation in it went without a reply. Increment 4 starts only when this is ticked.

### Increment 4 — inspection, escalation, and the owner brief

Review step 4, and the case-capture section.

When the agent cannot quote, the owner can call the customer back without reading the chat.

- [x] `book_inspection` and `escalate_to_owner` are use cases. The model writes a summary; the brief itself is built from the case, the decision, and the planner.
- [x] An inspection is an aggregate: job, address, rule id, fee, proposed window, and status (`offered`, `booked`, `completed`). It has a table with row-level security. Quote state gains `INSPECTION_BOOKED`. Its windows come from the capacity table with job type `inspection`.
- [x] Each escalation sends the owner one notification, WhatsApp to the profile's owner number with email as the fallback, carrying a link to the brief. It is sent once, recorded, and never repeated.
- [x] "I don't know" is a fact state, `unknown`, tied to the message it came from. It is not a missing fact. The planner stops asking. If the job type allows an inspection, it offers one. Otherwise it escalates.
- [x] The same path runs after two unanswered attempts at the same question. The customer is told that plainly.
- [x] The owner brief contains the fields in the review: who the customer is, what they want, job types, facts known and their sources, facts missing and facts unknown, photos and voice notes with their summaries, the outcome and rule, any quote or inspection, the suggested next action, and the last customer message and its time.
- [x] The console lists open cases by outcome (escalated, inspection offered, quote issued), newest first. Each row opens the brief. No reminder scheduler.
- [x] An out-of-scope request uses the playbook profile: a specific reply, and a short note for the owner. A greeting or a common question is answered from the playbook, then one question moves toward a job.
- [x] WATER-E02 is not retargeted.

Increment 4 gate:

- [x] A damaged installation records an inspection rather than only sending a template.
- [x] An "I don't know" is not asked again.
- [x] An owner can place the next call from the brief alone.
- [x] A tool failure still escalates, and that escalation has the brief.
- [x] The owner receives exactly one notification for that escalation.

### Increment 5 — price, decision, and revision

Review step 5, and policy findings A3 plus the quote-state gap. This removes the `InvalidTransition` that today fires when a customer adds detail after an escalation. The stage 1 guard already stops that from going silent. This increment makes the transition legal.

- [x] A rate-card item has a unit (`each`, `per m²`, `per metre`) and a role (`product`, `frame`, `hardware`, `installation`, `delivery`, `inspection`).
- [x] A job type lists the roles it adds. A pivot door is door, frame, handle, installation, and delivery. `price()` composes them in the domain.
- [x] Delete `_scale_carport` and the description matching in `GetQuote`. Area pricing is the rate-card unit times the measured quantity.
- [x] Decide per job, and quote per job. A second job in the same conversation is not ignored. The planner already plans per job (increment 3) and is not reopened.
- [x] Each quote version stores the outcome, rule id, reasons, policy version, and the facts used.
- [x] `ESCALATED` and `EXPIRED` may open a new version under the current policy. The previous version remains. Issuing the new version still marks the old one `REVISED` where that rule already applies.

Increment 5 gate:

- [x] A carport price comes from the rate card with no formula in the use case.
- [x] A second job is quoted.
- [x] A revision after escalation creates a version.
- [x] The console can show why a quote was issued.

### Increment 6 — rules as data, adapters in their layer, tenant from the webhook

Review step 6. Removes decision rules as Python functions (A11), Postgres adapters living in `infrastructure/` (A6), and one tenant per process (A9).

Edit the D1 decision in this file before writing these tests. That edit overturns build-plan decision D1.

- [x] Rule conditions are data: `all`, `any`, `equals`, `in`, `greater_than`, `is_missing`, `is_unknown`, evaluated by one pure function. `decide()` does not branch on which business it serves.
- [x] Safety rules stay locked templates. Their wording can be edited. Their conditions cannot.
- [x] Move the Postgres adapters that still live in `infrastructure/` (`stored.py`, `commercial.py`, `tenants.py`, `rate_cards.py`) into `adapters/outbound/persistence/`. `container.py` remains the only composition root. `infrastructure/` keeps configuration, the app factory, and the worker loop.
- [x] The tenant table stores the WhatsApp `phone_number_id`. Each webhook resolves the tenant from that id. The `TENANT` environment variable remains a default for the simulator, not the live routing key. One process serves every tenant.

Increment 6 gate:

- [x] A published policy can express "a new opening needs a site measure" with no new predicate. Seen: `FAB-S09` with `opening in (new, widened)` decides a site measure.
- [x] Two phone numbers on one process reach two tenants, and row-level security still isolates them. Seen: `PHONE-AQUA` and `PHONE-FRAME` stored `aqua-only` and `frame-only` on one process, each visible only to its tenant.
- [x] `infrastructure/` contains no repository. The four Postgres modules are gone. Memory doubles stay in `demo.py`, which is the test double. `db.py` stays as the engine factory.

### Increment 7 — the evaluation gate

Review step 7. This is the release gate, not a paragraph in the README.

- [x] Twenty to thirty short scripted conversations per business, written from that business's playbook. Each names the expected outcome, the expected rule id, the required facts, and phrases that must not appear. Seen: 24 for AquaSure and 24 for FrameWorks.
- [x] A customer simulator sits behind the model port. The persona varies between runs. The expected outcome does not. Seen: seed 0 and seed 1 both score outcome accuracy 1.0, and the two wordings differ.
- [x] Report, per business: outcome accuracy, questions asked before the outcome, conversations with no reply (target zero), unfounded commitments (target zero), re-asked facts, brief completeness, median and slowest 10 percent latency, and cost per conversation. Seen on 30 October 2026: both businesses accuracy 1.0, 0.33 questions, silent 0, unfounded 0, re-asked 0, brief 1.0, median 0.002s, slowest 10 percent 0.003s, cost 0. The voice is scripted, so those times are the harness, not Spark.
- [x] A business is given a live number only after its set has passed the targets on three consecutive runs. This run is the first pass, so the command refuses a number for both.
- [x] Oakmere Doors is the first business added this way. Its playbook and rate card come from the owner, not from guessed prices. Its set is written before it is served. Seen: `eval/conversations/oakmere.yaml` has 24 situations, no prices, and the slug is not a tenant.

Increment 7 gate:

- [x] A command produces the numbers. Seen: `python -m eval.run_gate`.
- [x] The README quotes the latest run and the date. Seen: 30 October 2026.
- [x] A business with no three passing runs has no live number. Seen: AquaSure, FrameWorks, and Oakmere Doors.

## Swap and new installation

Follows increment 7. The working checklist, the tests, and the document pass are [swap-vs-new.md](swap-vs-new.md). Tick the boxes there as the work is done. Tick the gate here when that file's matching gate is green.

- [x] Increment 1 gate. `price()` keeps today's totals on a card of products, and prices a swap and a new installation differently once the card has infrastructure rows. Seen: 48 passed, and `lint-imports` kept 4 contracts.
- [x] Increment 2 gate. The console shows the unit, the role, and when the row applies. Publishing writes `applies_to`. A duplicated new-installation role does not publish. Seen: 61 passed, and `lint-imports` kept 4 contracts.
- [x] Increment 3 gate. The case decides swap or new. A plain new opening can be a fixed quote. A widened opening stays a visit. The release set is green. Seen: 181 passed, lint-imports kept 4 contracts, and python -m eval.run_gate reported accuracy 1 and unfounded 0 for both businesses, 24 and 24 conversations.
- [x] Increment 4 gate. The quote card and the owner brief list the lines, and the brief marks a swap or a new installation. Seen: 126 passed, lint-imports kept 4 contracts. The browser published a stand, showed the tank on a swap and the tank plus the stand on a new installation, and a widened opening stayed a visit.
- [x] Increment 5 gate. The production notes, the architecture note, the design notes named in the checklist, and the README describe the behavior the tests lock. The README table is the 31 October 2026 run.

## Order

Stage 1 runs 1.1, then 1.2, then 1.3, then 1.4. Slice 1.2 stores status in the database that 1.1 made the only live store. Slice 1.3 persists an outcome, so the ledger has to exist. Slice 1.4 puts business knowledge on the policy that the guard is already willing to escalate from.

Stage 2 runs 3, then 4, then 5, then 6, then 7. The planner reads the playbook. Inspection and the two-attempt limit are planner results. Pricing does not need the condition language, so it follows the brief rather than waiting for step 6. The adapter move is the first commit of increment 6 and changes no behavior. Evaluation sets are drafted in slice 1.4, a small set runs after increment 3 and gates increment 4, and the full increment 7 gate binds at the end of increment 6. The hackathon cut line above says which of these land before 4 November.

The swap and new-installation work follows increment 7, in the order in [swap-vs-new.md](swap-vs-new.md): the price engine, the console, the questions and rules, the lines on the quote, then the production, architecture, design, and README update.

## Out of scope

These are not boxes. They are not work.

- A live number for a third business during stage 1.
- Another reply heuristic, or another branch on the trade name.
- The condition language before increment 6.
- A reminder scheduler.
- A weakened `decide`, `price`, or `check_reply` test, used to absorb a slice.
- The review's half-day estimates, used as the schedule.
