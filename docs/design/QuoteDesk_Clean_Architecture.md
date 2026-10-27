# QuoteDesk Clean Architecture

Oct 26, 2026 · @Bushboy

## Purpose and principles

This document fixes how the QuoteDesk code is organised so that the product's central promise, models interpret and code commits, is enforced by the structure of the code and not only by prompts. It complements the build spec: the spec says what to build; this says where each piece lives and which way dependencies point.

**Principles**

1. **Dependencies point inward.** Domain code imports nothing from the outer layers; use cases depend only on the domain and on ports they define; adapters implement ports. An `import-linter` contract in CI fails the build if this breaks.
2. **Models are adapters.** Muse Spark, Muse Wonder, SAM 3.1 and Voice Transcribe sit behind ports and return typed facts. Only domain code creates a decision, a price, a condition or a schedule commitment.
3. **The agent is a client, not the core.** The conversational agent calls use cases through tool adapters exactly as a web form would. Tool inputs carry no prices, outcomes or clause text.
4. **Every write is a use case.** Each state change runs inside one unit of work that also records its audit event, so the audit trail cannot drift from the data.
5. **Tenant context is explicit.** Every use case receives a tenant context; repositories apply it to row-level security per transaction.
6. **Swappable at the edges.** Changing Spark 1.3 for Muse Spark Open, the web chat for real WhatsApp, or local files for object storage is a configuration change in the composition root.

## Layers

Four layers, each allowed to depend only on the layers inside it. The domain at the centre holds every commercial rule; the outer layers deliver messages, call models and store data on its behalf.

&#91;embedded content: QuoteDesk layers · dependencies point inward\]

Read from the outside in: a framework receives a request, an adapter turns it into a use case call, the use case asks the domain what may be committed, and the domain answers without knowing any of the outer layers exist.

| Layer | Responsibility | Must not |
| --- | --- | --- |
| Domain | Commercial rules: decisions, prices, conditions, schedules, policy validity | Import adapters, call models, read the clock or touch storage |
| Application | Use cases that orchestrate one action each; ports they need | Know which model, database or channel is behind a port |
| Interface adapters | Translate HTTP, WhatsApp payloads, tool calls, model and database responses | Contain commercial rules |
| Frameworks and drivers | FastAPI, PostgreSQL, SDKs, parsers | Be imported by the domain or application |

## Domain layer

The domain is plain Python: Pydantic models and pure functions with no I/O, no framework imports and no model calls. It is where every commercial rule lives, so it gets the most tests and changes only by your hand.

**Entities and aggregates**

| Aggregate | Contains | Invariants it protects |
| --- | --- | --- |
| `Quote` | Quote versions, line items, conditions, evidence references, decision, approvals, schedule commitment | A version is immutable once issued; a change creates a new version; state moves only along allowed transitions |
| `PolicyVersion` | Rate card items, clause templates, settings, scheduling settings, rule parameters, job types | Drafts are editable, published versions never are; locked safety rules cannot be changed |
| `CaseFile` | Jobs, case facts, open questions, contradictions, older-turn summary | Corrections supersede facts, never overwrite; every fact names its source event |
| `Conversation` | Ordered events with their media enrichment results | Events are append-only and unique per provider message ID |
| `ImportJob` | Imported rows with source locations and flags | Rows reach a draft only after owner review |

**Value objects:** `Money` (ZAR, `Decimal`, no floats), `DateWindow`, `QuoteId` (`QD-` pattern), `RuleId`, `PolicyVersionId`, `ConfidenceBand`, `Outcome`.

**Domain services** (pure functions)

| Service | Input | Output |
| --- | --- | --- |
| `decide()` | Case facts, extraction facts, segmentation facts, published policy | `Decision`: outcome, rule ID, reasons, confidence band |
| `derive_confidence()` | Required-field completeness, cross-model agreement, measurement source, media usability (blur, darkness, unintelligible audio), rate card match | `ConfidenceBand` |
| `select_clauses()` | Decision, unconfirmed facts, job type, policy | Conditions with placeholders filled from settings |
| `price()` | Decision, facts, rate card | Line items or a range, as `Money` |
| `schedule()` | Request, capacity snapshot, scheduling settings, deposit state | Schedule commitment and what the agent may say |
| `validate_policy()` | Policy draft | List of validation errors |
| `detect_contradiction()` | New fact, existing facts | Contradiction or none |
| `classify_injection_claims()` | Extracted text from media or messages | Flags for claimed approvals or instructions |

The domain never decides how to talk to a customer; it decides what may be committed to. Wording belongs to the agent, within limits the domain sets.

## Application layer

Use cases orchestrate: they load aggregates through ports, call domain services, save results and record audit events in one unit of work. Each use case is a class with one `execute()` method taking an input DTO and a tenant context, returning an output DTO.

**Use cases**

| Area | Use cases |
| --- | --- |
| Conversation | `ReceiveInboundEvent`, `EnrichMedia`, `RunAgentTurn`, `HandoverToHuman` |
| Case and quotes (agent tools) | `AssessMedia`, `UpdateCase`, `GetQuote`, `RequestChange`, `CheckAvailability`, `HoldSlot`, `GetQuoteStatus`, `CreateDepositLink` |
| Owner and operator | `ApproveException`, `RejectException`, `ListApprovalQueue`, `GetAuditTimeline` |
| Policy editor | `EditPolicyDraft`, `ValidatePolicyDraft`, `PreviewPolicyImpact`, `PublishPolicy`, `RollbackPolicy`, `ProposeChangeFromText` |
| Rate card import | `StartImport`, `ReviewImportRows`, `MergeImportIntoDraft` |
| Evaluation | `RunScenario`, `JudgeTranscript` |

**Ports** (Python `Protocol` classes owned by the application layer)

| Port | Purpose | Hackathon adapter |
| --- | --- | --- |
| `QuoteRepository`, `PolicyRepository`, `CaseFileRepository`, `ConversationRepository`, `ImportRepository` | Load and save aggregates | SQLAlchemy on PostgreSQL |
| `AuditLog` | Append audit events inside the unit of work | `audit_events` table, insert-only grant |
| `UnitOfWork` | Transaction boundary, tenant context for RLS | SQLAlchemy session |
| `CapacityCalendar` | Read windows, place and release holds | `capacity_slots` table |
| `AgentModel` | One agent turn: context in, reply and tool calls out | Muse Spark 1.3; Muse Spark Open via Baseten (optional) |
| `MediaExtractor` | Photo or video to typed facts | Muse Spark 1.3 structured output |
| `Segmenter` | Image or video plus phrases to masks | SAM 3.1 |
| `Transcriber` | Audio to text with language and keyword biasing | Muse Voice Transcribe |
| `InputClassifier` | Gate category for an inbound event | Muse Spark 1.3 |
| `PolicyAssistant` | Plain-language change or messy import to a draft diff | Muse Wonder |
| `TranscriptJudge` | Scores a scenario transcript on the rubric | Muse Wonder |
| `DocumentParser` | Office and PDF files to rows and text | `openpyxl`, `python-docx`, `python-pptx`, `pdfplumber` |
| `ChannelSender` | Send a reply to the customer | WhatsApp Cloud API format; outbox in test mode |
| `PaymentLinks` | Create a deposit link, read its status | Sandbox stub |
| `MediaStore` | Store and fetch media with expiry | Local disk |
| `TaskQueue` | Run enrichment and turns in the background | In-process asyncio worker |
| `ConversationLock` | One turn at a time per conversation | PostgreSQL advisory lock |
| `Clock`, `IdGenerator` | Time and IDs, replaceable in tests | System clock, UUIDs and `QD-` sequence |

Ports speak in domain and DTO types only. No port returns a vendor response object, and no use case knows which model or database sits behind a port.

## Interface adapters and frameworks

Adapters translate between the outside world and use cases. Inbound adapters turn requests into use case calls; outbound adapters implement ports. Frameworks are details the adapters wrap.

**Inbound adapters**

| Adapter | Turns this | Into this |
| --- | --- | --- |
| WhatsApp webhook router | Cloud API payloads (text, image, audio, video, status updates) | `ReceiveInboundEvent` |
| Web chat router | Browser messages and uploads | `ReceiveInboundEvent` (same path as WhatsApp) |
| Agent tool adapter | The agent's function calls | Tool use cases; function schemas generated from the input DTOs |
| Quote card views | Customer opening a quote link with its verification code | `GetQuoteStatus`, rendered with Jinja2 |
| Operator console views | Owner approvals and audit browsing | Owner and operator use cases |
| Policy editor views | Form edits, uploads, typed text | Policy editor and import use cases |
| Harness client | Scenario YAML | Cloud API payloads posted to the webhook, outbox reads |

**Outbound adapters**

| Adapter | Implements | Notes |
| --- | --- | --- |
| `MetaAgentModel` | `AgentModel` | `openai` SDK at `api.meta.ai/v1`, Responses API, prompt caching on the stable prefix |
| `BasetenAgentModel` | `AgentModel` | Muse Spark Open; same contract, chosen by configuration |
| `MetaMediaExtractor`, `MetaClassifier` | `MediaExtractor`, `InputClassifier` | Spark 1.3 structured output against schemas generated from DTOs |
| `MetaSegmenter` | `Segmenter` | SAM 3.1; includes the parser that turns its text geometry into masks |
| `MetaTranscriber` | `Transcriber` | Voice Transcribe file endpoint; ffmpeg converts WhatsApp voice notes first |
| `WonderPolicyAssistant`, `WonderJudge` | `PolicyAssistant`, `TranscriptJudge` | Muse Wonder |
| SQLAlchemy repositories | Repository ports, `UnitOfWork`, `AuditLog` | Sets `app.current_tenant_id` at the start of every transaction |
| `CloudApiSender`, `OutboxSender` | `ChannelSender` | Selected by configuration |
| File parsers | `DocumentParser` | Rejects macro-enabled files before parsing |

**Rules for adapters**

- Model adapters validate every response against its DTO schema; a response that fails validation is a failure, never a partial result.
- Retries, timeouts and rate-limit handling live in adapters; use cases see a typed success or a typed failure.
- Vendor names never appear above the adapter layer. Swapping a vendor touches one adapter and one line of configuration.

**Frameworks and drivers:** FastAPI, Uvicorn, PostgreSQL 16 with row-level security, SQLAlchemy 2 and Alembic, Jinja2 and HTMX, the `openai` SDK, ffmpeg, Pillow, `openpyxl`, `python-docx`, `python-pptx`, `pdfplumber`, Docker Compose.

## Package structure

One top-level package per layer; folder names match the layer names so `import-linter` contracts read naturally.

```text
quotedesk/
  domain/
    shared/          money.py, ids.py, windows.py, errors.py
    quotes/          quote.py, conditions.py, schedule.py, evidence.py
    policy/          policy_version.py, rate_card.py, clauses.py, rules.py, validate.py
    case/            case_file.py, facts.py, contradictions.py
    conversation/    events.py
    services/        decide.py, confidence.py, select_clauses.py, price.py, schedule.py
  application/
    ports/           repositories.py, models.py, channel.py, payments.py, storage.py, runtime.py
    dto/             tool_inputs.py, tool_outputs.py, editor.py, imports.py
    use_cases/
      conversation/  receive_event.py, enrich_media.py, run_agent_turn.py, handover.py
      tools/         assess_media.py, update_case.py, get_quote.py, request_change.py,
                     check_availability.py, hold_slot.py, get_quote_status.py, create_deposit_link.py
      operator/      approvals.py, audit_timeline.py
      editor/        drafts.py, validate.py, preview.py, publish.py, rollback.py, propose.py
      imports/       start_import.py, review_rows.py, merge.py
      evaluation/    run_scenario.py, judge.py
  adapters/
    inbound/
      http/          whatsapp_webhook.py, web_chat.py, quote_card.py, console.py, editor.py
      agent_tools/   registry.py, schemas.py
    outbound/
      models/meta/   agent.py, extractor.py, classifier.py, segmenter.py, sam_parser.py,
                     transcriber.py, wonder.py
      models/baseten/ agent.py
      persistence/   sqlalchemy_repos.py, unit_of_work.py, audit_log.py, tables.py
      channels/      cloud_api_sender.py, outbox_sender.py
      parsers/       excel.py, word.py, powerpoint.py, pdf.py
      payments/      sandbox.py
      storage/       local_media.py
  infrastructure/
    config.py        settings, feature flags, model routing
    container.py     composition root: wires adapters to ports
    db.py            engine, sessions, Alembic
    workers.py       background task loop, debounce, conversation locks
    main.py          FastAPI app factory
seeds/               aquasure.yaml, frameworks.yaml (fictional tenants)
harness/             scenarios/*.yaml, media/, runner.py
eval/                photo_cases/, run.py, results/
tests/               unit/, use_cases/, adapters/, e2e/
docs/design/         prepared before the event: spec, strategy, this document
```

**Import contracts** (`.importlinter`)

- `domain` may import only the standard library and Pydantic.
- `application` may import `domain`, never `adapters` or `infrastructure`.
- `adapters` may import `application` and `domain`, never `infrastructure`.
- Only `infrastructure.container` imports concrete adapters.

## Key flows

Three flows show the layers working together. Each step names the layer it runs in.

**1. A customer message becomes an agent reply**

1. *Adapter:* the webhook router validates the payload, maps it to an `InboundEvent` DTO and calls `ReceiveInboundEvent`; it returns HTTP 200 immediately.
2. *Use case:* `ReceiveInboundEvent` drops duplicates by provider message ID, appends the event to the `Conversation`, runs code checks and `InputClassifier`, and queues `EnrichMedia` for any media.
3. *Use case:* `EnrichMedia` calls `Transcriber`, `MediaExtractor` and `Segmenter` as needed and attaches typed results to the event.
4. *Infrastructure:* the worker waits for the quiet window, takes the `ConversationLock` and queues `RunAgentTurn`.
5. *Use case:* `RunAgentTurn` loads the `CaseFile`, recent events and policy summary, and calls `AgentModel`.
6. *Adapter:* each tool call from the model goes through the agent tool adapter to its use case (for example `UpdateCase`, then `GetQuote`), and the results go back to the model.
7. *Use case:* the final reply is checked against that turn's tool results (no price, date or inclusion that did not come from a tool), then sent through `ChannelSender`.

**2. `GetQuote` produces a commitment**

1. *Use case:* loads the case file, the latest extraction and segmentation facts, and the tenant's published `PolicyVersion`.
2. *Domain:* `derive_confidence()`, then `decide()` returns the outcome and rule; `price()` and `select_clauses()` build line items or a range and the conditions.
3. *Domain:* the `Quote` aggregate creates a new version in `ISSUED`, `SITE_ASSESSMENT_OFFERED`, `ESCALATED` or `PENDING_APPROVAL`.
4. *Use case:* saves the quote and its audit event in one unit of work and returns the quote DTO, which the agent may relay but not alter.

**3. The owner publishes a policy change**

1. *Adapter:* the editor form posts changes; `EditPolicyDraft` updates the draft `PolicyVersion`.
2. *Domain:* `validate_policy()` returns errors; publishing is blocked until there are none.
3. *Use case:* `PreviewPolicyImpact` reruns stored test cases and recent quotes through `decide()` against both versions and returns the differences.
4. *Use case:* `PublishPolicy` marks the draft published with the owner's reason; issued quotes keep their version.

## Cross-cutting concerns

Each concern has one home, so it is implemented once and not scattered through use cases.

| Concern | Where it lives | How |
| --- | --- | --- |
| Tenancy | `UnitOfWork` adapter | Every transaction sets `app.current_tenant_id`; RLS policies on every table; use cases receive a `TenantContext` and cannot omit it |
| Audit | `AuditLog` port inside `UnitOfWork` | Each use case that writes records actor, action, entity, before and after summary in the same transaction; insert-only database grant |
| Idempotency | Inbound adapter and consequential use cases | Provider message ID for events; idempotency key on `HoldSlot`, `CreateDepositLink` and `PublishPolicy` |
| Concurrency | `ConversationLock` and the worker | One agent turn per conversation; quiet-window batching; mid-turn messages queue for the next turn |
| Errors | Domain and application error types | Domain raises typed errors (`PolicyViolation`, `InvalidTransition`, `StaleQuote`); adapters map them to HTTP responses or fixed customer replies; unknown errors fail closed to a handover |
| Configuration | `infrastructure/config.py` | Typed settings from environment: model routing per port, quiet window, limits, feature flags; secrets only from `.env`, never committed |
| Feature flags | Configuration, read by use cases through a `Flags` value | `afrikaans_text`, `afrikaans_voice`, `open_weight_agent`, `wonder_assist`; all default off except the core |
| Observability | Adapters and worker | Structured logs with conversation, turn and tenant IDs; per-call latency and token counts from model adapters feed the evaluation metrics |
| Privacy | `MediaStore` and input gate | Explicit images and identity documents never stored; media expires after a set period; only fictional tenants in the public repo |

## Testing and parallel work

The layers give each kind of test a natural boundary, and they let you and Devin build in parallel against the same ports without stepping on each other.

| Level | Tests | Speed | Uses real models? |
| --- | --- | --- | --- |
| Domain unit | `decide()`, confidence, pricing, clause selection, scheduling, policy validation, contradictions; one test per rule ID | Milliseconds | No |
| Use case | Each use case with in-memory fakes for every port, including a fake `AgentModel` that replays scripted tool calls | Fast | No |
| Adapter contract | Each adapter against its port's contract: repositories on a test database, model adapters against recorded responses, SAM parser on saved outputs | Seconds | Recorded only |
| End to end | Harness scenarios S01 to S12 through the webhook, plus the 50 photo cases | Minutes | Yes |
| Architecture | `import-linter` contracts in CI | Seconds | No |

**Work split**

- **You own the centre:** `domain/`, `application/ports/`, `application/dto/` and the core use cases (`GetQuote`, `RequestChange`, `RunAgentTurn`, `PublishPolicy`). Ports and DTOs are written first, so Devin always builds against a fixed contract.
- **Devin owns adapters and edges:** model adapters and the SAM parser, persistence, file parsers, the webhook mapper, the harness, HTMX views. Each task is one adapter plus its contract test.
- **Devin never edits** `domain/`, `application/ports/`, `application/dto/` or the seed policy files; a CI check rejects pull requests from Devin's branch that touch them.

## Architecture decisions

Each decision is the simplest choice that fits a nine-day solo build without blocking the path to Delegant; the last column says when to revisit it.

| # | Decision | Why | Revisit when |
| --- | --- | --- | --- |
| AD-1 | Clean architecture with `Protocol` ports and a single composition root | Enforces models interpret, code commits; lets Devin work on adapters in parallel | Never for the core |
| AD-2 | Python 3.12, FastAPI, Pydantic v2 | One language; Pydantic models double as DTOs and function-calling schemas | No planned change |
| AD-3 | PostgreSQL for data, row-level security, conversation locks (advisory locks) and the audit log; no Redis | One stateful service to run and host | Throughput needs a separate queue |
| AD-4 | In-process asyncio worker behind `TaskQueue` | Minimal moving parts for the demo | More than one app instance, or long video jobs |
| AD-5 | Jinja2 and HTMX for chat, quote card, console and editor | Server-rendered, no separate frontend build | Owners need a mobile app |
| AD-6 | No pgvector or retrieval in this build | Prices and commitments come from the policy engine; avoids the "basic RAG" pattern | FAQ answering is added |
| AD-7 | Model routing per port in configuration | Spark 1.3 or Muse Spark Open for the agent without code change; enables the open-weight comparison | New model families |
| AD-8 | Local disk for media with expiry, behind `MediaStore` | Enough for the demo | Hosted multi-instance deployment |
| AD-9 | Pydantic models in the domain | Validation and serialisation for free; one source of truth for schemas | The domain needs to be framework-free in the strictest sense |
| AD-10 | AGPL-3.0 licence for the public repository | Public repo required by the rules; deters closed hosted forks | Commercial licensing needs change |

## Mapping to the Delegant strategy

Every component named in the strategy has a home in these layers, so the hackathon code becomes Delegant's base without restructuring. Details of what is built are in QuoteDesk Hackathon Build Spec; strategy changes are tracked in Delegant Strategy Revisions.

| Strategy component | Layer | Lives in |
| --- | --- | --- |
| Channel adapters | Inbound adapter | `adapters/inbound/http/whatsapp_webhook.py`, `web_chat.py` |
| Core API, tenant resolution, idempotency | Inbound adapter and `UnitOfWork` | `adapters/inbound/http/`, `adapters/outbound/persistence/unit_of_work.py` |
| Policy Gatekeeper | Domain services and input gate use case | `domain/services/`, `application/use_cases/conversation/receive_event.py` |
| Intent Router | Use case plus model adapter | `run_agent_turn.py`, `adapters/outbound/models/meta/agent.py` |
| QuoteDesk vision | Use case plus model adapters | `enrich_media.py`, `extractor.py`, `segmenter.py` |
| Commercial Core | Domain aggregates and repositories | `domain/quotes/`, `domain/policy/`, `sqlalchemy_repos.py` |
| Model Abstraction Registry | Ports plus composition root | `application/ports/models.py`, `infrastructure/container.py` |
| Operator Console | Inbound adapter and operator use cases | `adapters/inbound/http/console.py`, `use_cases/operator/` |
| Persistence and audit | Outbound adapters | `adapters/outbound/persistence/` |
| Workflow engine (n8n) | Not in this build | Would be an outbound adapter behind `TaskQueue` or a notifications port |
| Retrieval (pgvector) | Not in this build | Would be an outbound adapter behind a new knowledge port |
| MCP and agent-facing APIs (Horizon 2) | Future inbound adapter | A second inbound adapter over the same tool use cases |
