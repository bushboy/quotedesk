# QuoteDesk Implementation Review

Oct 30, 2026 · @Bushboy

## Verdict

The commercial core is still sound, but the last four days of work have moved business knowledge into the wrong places, and the agent can still go silent. Do not seed a third business yet: today, adding Oakmere Doors means editing code in at least six places, and a single tool error can leave a customer unanswered while the worker retries forever. Fix the shape first; it is about two days of work and it is what makes the third business a configuration task.

Reviewed: the repository as of commit `04e14d2` plus uncommitted changes, 30 October 2026, by reading the code. Your last local test run passed 297 tests; I could not run them myself.

| Area | Status | Main finding |
| --- | --- | --- |
| Domain core (quote, money, decide, reply checker) | Strong | Pure, immutable, well tested; still the best part of the build |
| Persistence and tenancy | Partial | Postgres with row-level security works, but adapters live in `infrastructure/` and a database outage silently falls back to memory |
| Business as data | Gap | Prompts, required facts, pricing rules and tenant list are Python code, chosen by matching words in the trade name |
| Agent loop | Gap | 1,117-line use case; silent paths; reply text rewritten by per-trade heuristics; no inspection booking or escalation tool |
| Owner handover | Gap | The owner's brief is a list of job types; not enough to call the customer back |
| Evaluation | Gap | No accuracy measurement yet; `eval/` is empty |

## What the agent must do

The agent stands in for an absent owner and plugs leaking leads, so every conversation must move to one of four outcomes, and every customer message must get a sensible reply. Code decides which outcome applies; the model gathers the facts and does the talking.

&#91;embedded content: Target turn flow · four outcomes, one guarantee\]

Asking a question loops back to the customer until the planner has what it needs, the customer says they don't know, or the same question has gone unanswered twice.

**Testable outcomes**

1. **Quote within policy.** When the job type's required facts are known and a priced rule matches, the customer gets a fixed price or a range with its conditions and a card link, in the same turn.
2. **Inspection when policy requires it.** When an inspection trigger matches, the customer is told why in one sentence, offered the fee and the earliest window, and the inspection is recorded.
3. **Escalation for everything else.** Safety, complaints, claimed approvals, out-of-scope work, unknown facts with no inspection route, or any system failure: the customer is told a person will reply, and the owner gets a complete brief.
4. **Clarifying questions until then.** One question at a time, aimed at the next missing fact, in the business's own terms.
5. **Never silent, never garbled.** No tool errors, refusals or empty replies reach the customer; no price, date or inclusion that a tool did not return.

## Architecture alignment

The layer boundaries still hold where import-linter checks them, but the clean-architecture intent is broken in places the linter cannot see: business rules in the application and adapter layers, and adapters in the infrastructure layer.

**Still aligned**

- Domain imports nothing from outer layers; `decide()`, `price()`, `select_clauses()` and `check_reply()` are pure.
- Ports and DTOs separate the use cases from models, storage and channels; `SparkTurn` is a proper adapter behind `AgentModel`.
- Row-level security is set per transaction; webhook signatures are verified.

**Misaligned**

| # | Finding | Where | Why it matters | Fix |
| --- | --- | --- | --- | --- |
| A1 | Per-trade prompts are constants in the use case, picked by matching "water tank" or "carport" in the trade name | `run_agent_turn.py` (`WATER_HINTS`, `FRAME_HINTS`, `task_for`) | A third business gets the generic prompt; prompts are not versioned with the policy | Move into a per-tenant business playbook (section on the agent) |
| A2 | Reply text is rewritten after the model by trade-specific heuristics | `run_agent_turn.py` (`_carport_question`, `_indicative_reply`, `_recording`, `_recorded_sized_install`, `_fabrication`) | Fragile string matching decides what the customer reads; each new business needs new heuristics | Compute the next step in code from the playbook; let the model phrase it |
| A3 | Pricing rule for carports in the quote use case | `get_quote.py` (`_scale_carport`, `_match_card`) | Price-per-square-metre is a rate-card fact, not application logic | Add a pricing unit to rate-card items; price in the domain |
| A4 | Required facts per job type live in a demo fake | `infrastructure/demo.py` (`Catalog.required`) | FrameWorks has no required facts, so the agent has nothing telling it what to ask | Required facts and their questions belong to the published policy |
| A5 | Two system prompts with overlapping, partly different rules | `spark.py` (`INSTRUCTIONS`) and `run_agent_turn.py` (`AGENT_TASK`) | The model receives both; edits to one drift from the other | One platform prompt in the application layer; the adapter only transports it |
| A6 | Postgres adapters live in `infrastructure/` | `stored.py`, `commercial.py`, `tenants.py`, `rate_cards.py` | Infrastructure should only wire; import-linter cannot catch this because infrastructure may import anything | Move to `adapters/outbound/persistence/`; keep `container.py` as the only wiring |
| A7 | A database outage silently falls back to in-memory stores | `stored.py`, `rate_cards.py`, `tenants.py` docstrings | Messages and cases accepted during an outage vanish on restart: a leaking lead, the thing the product exists to stop | Fail closed: return 503 to the webhook so WhatsApp retries |
| A8 | Use-case instances hold process state | `RunAgentTurn._closed`, `_seen`, `_change_key` | Not restart-safe; two workers would double-answer | Persist message status and enrichment results |
| A9 | One tenant per process, chosen by an environment variable; tenants are a hard-coded list of two | `tenants.py`, `config.py` | A third business needs a code change and its own process | Resolve the tenant from the WhatsApp `phone_number_id` on each webhook |
| A10 | Use case reaches into another use case's private field | `run_agent_turn.py` (`self._handover._cases`) | Hidden coupling | Inject `CaseFileRepository` directly |
| A11 | Decision rules are Python functions keyed by rule ID | `decide.py` (`_PREDICATES`) | The policy editor can only switch rules on or off; a new business needs new code | Rule conditions as data over typed facts (section on policy) |

## Agent and prompts

The model is currently asked to decide what to do next, from a generic prompt plus one paragraph of trade hints, and code then patches its reply. Invert that: code decides the next step from the business's playbook and the case; the model extracts facts from what the customer said and phrases the reply.

**What the model receives today**

- One user message containing the whole context as a JSON blob: messages, case facts, rate-card codes and descriptions, extractions, tool payloads, and business name, trade, area and a one-line description.
- Two system prompts (A5). Neither says which facts each job type needs, how to ask for them, what triggers an inspection, or when to hand over.
- Tool schemas generated from the input models, which still ask the model for UUIDs such as `conversation_id` and nested `quote_id` objects; the turn patches some of them afterwards.
- No reasoning-effort setting, so latency and quality are left to the default.

**What is missing for the target behaviour**

- No tool to book an inspection and no tool to hand over to the owner; both happen only as side effects of `get_quote`.
- No notion of "the customer does not know": the agent can only ask again or guess.
- No list of required facts for most job types (A4), so "ask one clarifying question" has nothing to aim at.

**Recommendation: a business playbook per tenant, versioned with the policy**

| Part | Contents | Used by |
| --- | --- | --- |
| Profile | Name, trade, area served, hours, tone, languages, what the business does not do | Prompt; out-of-scope replies |
| Job types | For each: description, the rate-card items it can use, how it is priced (each, per m², per metre), what installation and delivery add | Prompt; pricing |
| Facts per job type | Key, type (number, choice, yes/no, text), unit, allowed values, the question to ask, whether a photo can answer it, whether it is required | Next-step planner; `update_case` validation; prompt |
| Inspection triggers | Plain-language conditions, mapped to rules (new opening, sloped ground, borehole) and the fee | Rules; customer wording |
| Escalation triggers | Safety, complaints, legal threats, claimed approvals, out-of-scope requests | Rules; handover |
| Common questions | Delivery areas, lead times, payment methods, showroom address | Grounded answers without a tool |

**Recommendation: a next-step planner in code**

Before each model call, a pure function `plan_next_step(case, playbook, policy)` returns exactly one of: ask for a named fact (with its question), ready to quote, inspection needed, or escalate (with reason). The prompt tells the model which one applies, so the model's job is to extract facts from the latest messages and phrase the step naturally. This replaces every heuristic in A2 and works the same for every business.

**Recommendation: tool loop and reply guarantees**

- A real loop: up to four model calls per turn, with each tool result returned as a `function_call_output` item, not re-serialised into the user message.
- The server binds `conversation_id`, `job_id` and `quote_id`; remove them from the tool schemas so the model never invents identifiers.
- Add `book_inspection` and `escalate_to_owner` (the latter with a summary the model writes, stored alongside the code-built brief).
- Remove business-specific instructions from the platform prompt; render the playbook into the prompt instead.
- Set reasoning effort explicitly (low for phrasing, medium for extraction) and measure latency.
- If the final model text is empty or fails the reply check, send the planner's own sentence (the question, the inspection offer, or the handover line) rather than a refusal.

## Policy and decision engine

`decide()` is the right idea in the right layer, but its rules are code rather than the business's policy, and the case facts it reads are untyped strings with aliases. That is why each business has needed new predicates, new fact names and new heuristics.

**Findings**

- **Rules are Python functions keyed by rule ID** (`_PREDICATES`). The YAML only sets priority, outcome and wording. A door showroom cannot express "a new opening needs a site measure" without a code change, even though FAB-S01 already says it.
- **Facts are untyped strings with aliases.** `GetQuote._facts` accepts `size_litres` or `tank_size`, `size` or `dimensions`, and `item` or `finish`, then fuzzy-matches rate-card descriptions. Every alias is a guess about what the model wrote.
- **The rate card has no pricing unit.** `RateCardItem` is code, description and price. Carport area pricing is bolted on in the use case (A3); door, frame, handle and installation lines cannot be combined into one quote.
- **One job per case.** `GetQuote` and the planner use `jobs[0]`; a second job in the same chat is ignored.
- **An inspection is only a message.** The site-assessment outcome returns a template and a fee; nothing books a slot, records the address, or tracks the inspection.
- **WATER-E02 now books an inspection instead of escalating.** That may be the owner's intent, but it is one of the locked safety rules; decide it explicitly.
- **Quotes still don't store their decision.** Rule ID, reasons and policy version are returned to the agent but not saved on the quote version, so the console and audit trail cannot say why a quote was issued.
- **Revising after escalation or expiry is still illegal** in the quote state table, so a customer who adds details after an escalation triggers an `InvalidTransition` (see robustness).

**Recommendations**

1. **Typed fact definitions per job type** in the playbook. `update_case` validates against them and normalises units; no aliases anywhere downstream.
2. **Rule conditions as data.** A small condition language over typed facts (`all`, `any`, `equals`, `in`, `greater_than`, `is_missing`, `is_unknown`), evaluated by one pure domain function. Safety rules stay locked templates with editable wording. `decide()` stops caring which business it serves.
3. **Rate-card items with a unit and a role.** Unit: each, per m², per metre. Role: product, frame, hardware, installation, delivery, inspection. Each job type lists which roles it adds, so a pivot door quote is door + frame + handle + installation + delivery, priced in the domain.
4. **Decide per job**, and quote per job.
5. **An inspection aggregate**: job, address, reason (rule ID), fee, proposed window, status (offered, booked, completed). Quote state gains `INSPECTION_BOOKED`.
6. **Persist the decision** (outcome, rule ID, reasons, policy version, facts used) on each quote version.
7. **Allow revision from `ESCALATED` and `EXPIRED`**, creating a new version under the current policy.

## Conversation robustness

There are six ways a customer can get no answer or a meaningless one today. All of them are fixed by one rule: every closed batch of customer messages produces exactly one outbound message and one recorded outcome, by construction.

| # | Path | What the customer sees | Where |
| --- | --- | --- | --- |
| R1 | Model returns no text and no tool call | Nothing; the batch is marked handled | `execute`: "Turn produced no front-end reply" (three places) |
| R2 | Any exception from a use case or the model transport (for example `InvalidTransition` when revising an escalated quote, `PolicyViolation` from a malformed flag, an HTTP 5xx from the model) | Nothing. The batch is not marked handled, so the worker retries every 0.25 seconds, calling the model each time, indefinitely | `container.py` worker catches and logs; `_close` never runs |
| R3 | Tool arguments are not valid JSON | "That tool is not available." | `spark.py` `_reply` returns the tool error as reply text |
| R4 | The reply fails the commitment check twice | "I can only repeat what the quote says." | `_REFUSAL` |
| R5 | Database outage | Messages accepted into memory, lost on restart | A7 |
| R6 | Process restart | Earlier messages are marked handled only by `acknowledge()` at startup; partial turns are lost | `_closed` in memory (A8) |

**Recommendations**

1. **A turn returns a `TurnOutcome`** (asked, quoted, inspection offered, inspection booked, escalated, answered) and the use case cannot finish without one. A top-level guard catches every exception, sends a safe sentence ("Thanks, I've passed this to the team and someone will reply shortly."), records an escalation with the error, and marks the batch handled.
2. **Retry budget:** one retry for a timeout or 5xx, then the guard. Never an unbounded loop.
3. **Persist message status** (`pending`, `answered`, `escalated`, `failed`) in Postgres; the worker picks up `pending` rows only. This also makes a second worker safe.
4. **Never send a tool error or a refusal sentence to the customer.** If the reply check fails, send the planner's sentence for the step instead (the question, the quote card link, the inspection offer or the handover line), all of which are built from tool results.
5. **Return 503 from the webhook while the database is down**, so WhatsApp redelivers the message later.
6. **Idempotent sends:** store the outbound message with the batch ID before sending, so a crash between sending and recording cannot double-send.

## Case capture and owner handover

When the agent cannot quote, the owner must be able to pick the case up without scrolling the chat. Today the handover note's brief is the job types joined by commas (for example "replacement"), plus a reason such as "The quote needs a person." That is not enough to call the customer back.

**The owner brief should contain**

| Field | Source |
| --- | --- |
| Customer number and name, if given | Webhook contact |
| What they want, in two sentences | Model-written summary, checked against the facts |
| Job type(s) | Case |
| Facts known, with where each came from (said, photo, voice note) | Case facts |
| Facts missing, and facts the customer said they don't know | Planner and case |
| Photos and voice notes, with transcripts and extraction summaries | Media and enrichment |
| Outcome, rule ID and the reason in plain words | Decision |
| Quote or inspection status, if any | Quote and inspection records |
| Suggested next action (call to confirm the opening size, book a site measure) | Planner |
| Last customer message and time | Conversation |

**"I don't know" is an answer**

- Record it as a fact state (`unknown`, with the message it came from), not as a missing fact.
- The planner stops asking for that fact. If the job type allows an inspection, it offers one; otherwise it escalates with the brief.
- The same applies after two unanswered attempts at the same question: stop asking, move to inspection or escalation, and say so plainly to the customer.

**Out of scope and small talk**

- An out-of-scope request (a plumber call-out at a door showroom) gets a polite, specific reply and a short note for the owner, since it may still be a lead.
- A greeting or an "are you open?" gets an answer from the playbook's common questions and one question that moves towards a job.

**Owner visibility, without reminders**

The console lists open cases by outcome (escalated, inspection offered, quote issued), newest first, each opening to the brief. No reminder scheduling is needed now; the list is the queue.

## Persistence, tenancy and data model

Postgres is now the system of record for conversations, cases, quotes and rate cards, with row-level security on every table. The remaining gaps are where data silently isn't persisted, and the one-business-per-process model.

| Gap | Effect | Fix |
| --- | --- | --- |
| Silent memory fallback (A7) | Leads accepted during an outage are lost | Fail closed; 503 to the webhook |
| Message status and enrichment results live in process memory (A8) | Restarts replay or drop work; image results are recomputed | `conversation_event.status`, an `enrichment` table keyed by message |
| Tenant chosen by an environment variable, two tenants hard-coded | One process per business; a third business is a code change | Tenant table with WhatsApp `phone_number_id`; resolve per webhook |
| Playbook and fact definitions not stored | Cannot be edited, versioned or published | Store with the policy version (draft, publish, rollback already exist) |
| Decision not stored on the quote version | No "why" in console or audit | Columns for outcome, rule ID, reasons, policy version |
| No inspection record | Inspections cannot be tracked or counted | `inspection` table with RLS |
| Contradictions typed as `Any` | Cannot be shown to the owner reliably | A typed `Contradiction` (fact key, two values, two sources) |

## Tests and evaluation

The 297 tests prove the code does what each slice designed; nothing yet measures whether the agent reaches the right outcome with a real model. "Great accuracy" needs a number, per business, from scripted conversations run against Spark.

**Gaps**

- `eval/photo_cases` and `eval/results` are empty; no run has produced accuracy, latency or cost figures.
- Most turn tests use scripted model replies, so they test plumbing, not judgement.
- Harness scenarios S01 to S12 are text only and assert little about outcomes.
- Several tests encode the heuristics in A2, which will make refactoring painful; expect to rewrite them with the planner.

**Evaluation to add**

- **A conversation set per business**: 20 to 30 short scripted customers each, written from the playbook. Each has an expected outcome (quote, inspection, escalation), expected rule ID, required facts, and phrases that must not appear.
- **Customer simulator**: Muse Wonder plays the customer from a short persona ("knows the width but not the height; impatient; mixes English and Afrikaans words") so conversations vary run to run, while the expected outcome stays fixed.
- **Metrics, reported per business**: outcome accuracy; questions asked before the outcome; conversations with no reply (target zero); unfounded commitments (target zero); re-asked facts; brief completeness (fields filled); median and slowest-10% latency; cost per conversation.
- **Gate**: no business goes to a demo or pilot until its set passes the targets above at least three runs in a row.

## Improvement plan

Do these in order; each step leaves the app working. Steps 1 to 4 are the minimum before seeding the door showroom; with them, the third business is a playbook file and a rate card, not code.

| Step | Work | Removes | Size |
| --- | --- | --- | --- |
| 1 | Turn guard: `TurnOutcome`, top-level catch, retry budget, persisted message status, planner sentence as fallback, 503 when the database is down | R1 to R6, A7, A8 | Half a day |
| 2 | Business playbook model (profile, job types, typed facts with questions, inspection and escalation triggers, common questions), stored with the policy version; seed AquaSure and FrameWorks from today's constants | A1, A4, A5, A9 (data side) | Half a day |
| 3 | `plan_next_step()` in the domain, one platform prompt that renders the playbook and the planned step, server-bound tool identifiers, multi-step tool loop; delete the trade heuristics | A2, A10 | Half a day |
| 4 | `book_inspection` and `escalate_to_owner` tools, inspection record, owner brief, "unknown" fact state, two-attempt limit | Section on case capture | Half a day |
| 5 | Rate-card units and roles; per-job pricing; decision stored on quote versions; revision from escalated and expired | A3, policy findings | Half a day |
| 6 | Rule conditions as data; move Postgres adapters into `adapters/`; tenant resolved from `phone_number_id` | A6, A9, A11 | One day |
| 7 | Evaluation set and simulator for all three businesses; publish the numbers in the README | Section on evaluation | Half a day, then ongoing |

**For Saturday's conversation with Oakmere Doors**, steps 1 and 2 are enough to seed the door showroom as a playbook with the rate card already prepared, and to demo it without the risk of a silent chat. Present it as a working prototype, and use the meeting to collect their real job types, prices and inspection rules for the playbook.

**Hackathon note:** steps 1 to 4 also strengthen the submission. A planner that decides the next step, an agent that always answers, and measured accuracy per business are a clearer story for judges than more features.
