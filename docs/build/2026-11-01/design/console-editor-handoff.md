# Console and editor

Written 28 October 2026. This hands the two owner pages to another builder. The quoting turn, the Spark adapter, and the photo slice stay with the other track.

The use cases are green. The pages are not registered. `GET /console` and `GET /editor` do not exist. The in-memory app can issue a quote and store a change, and it cannot yet list a pending row or publish a draft, because `Unit` and `Policies` in `quotedesk/infrastructure/demo.py` do not implement the methods those use cases already call.

## Read first

| Topic | File |
| --- | --- |
| Approval, reject, queue, timeline | [approve-exception.md](approve-exception.md) |
| Draft, validate, publish | [policy-publish.md](policy-publish.md) |
| Use cases, do not edit | `tests/use_cases/test_approve_exception.py`, `tests/use_cases/test_publish_policy.py` |
| Photo slice, do not start | [2026-11-03/PLAN.md](../../2026-11-03/PLAN.md) |

`ApproveException`, `RejectException`, `ListPending`, and `PublishPolicy` are the only writers. The page displays their results. It does not multiply a price, choose a version, or decide that a draft is valid.

## What you build

Two plain pages, opened in a second window. No Meta mark, no WhatsApp mark, no change to the chat page.

### `GET /console`

Calls `ListPending.execute(context)`.

Each row shows the quote id, the version, the requested percent, the cap, and the current total. For the fixture that is `QD-1042`, version `1`, `10` percent, cap `5`, total `R 4 250.00`. The cap is on the row so the owner can see the ask is above it. The page does not compare the two numbers and does not block Approve.

Approve and Reject are on that row. Both stay disabled until the version, the percent, and the total are visible. The form posts the quote id and the version. It does not post a new total or a percent. The server builds the input:

| Call | Input |
| --- | --- |
| Approve | `ApproveExceptionInput` with that quote id, that version, a new idempotency key, and `expires_at` seven days after the app clock |
| Reject | `RejectExceptionInput` with that quote id, that version, and a new idempotency key |

`QuoteId` is constructed in the page from the posted string. The input models are not changed.

After Approve, the page shows the `ApproveResult`: version `2`, state issued, and the line total from the result. For the fixture that total is `R 3 825.00`. The same quote leaves the waiting list. After Reject, the page shows version `1` still issued and the total still `R 4 250.00`.

An empty queue says `There is nothing waiting.`

Money is rendered from the `Money` value: a rand sign, a space as the thousands separator, two decimals. `4250.00` is `R 4 250.00`. The page does not format through `float`.

### `GET /editor`

One field, the deposit percent. One field, the reason. The validation sentences from `validate_policy`. A Publish button.

The running app has no draft until this page stores one. `install` holds a `PolicyDraft` copied from the published bundle, with that bundle's deposit percent. Posting a new percent replaces `deposit_percent` on that draft and nothing else. Rate rows, clauses, rules, required facts, and settings stay the copy. Safety rules stay enabled.

The page calls `validate_policy(draft)` and lists each `PolicyError.sentence`. Publish stays disabled while that tuple is non-empty or the reason is blank. The button does not post when it is disabled.

Publish calls `PublishPolicy.execute` with `PublishInput(reason=..., idempotency_key=...)`. The key is generated per click. The page shows the returned policy version id. It does not write the published bundle itself.

A deposit of `40` on the AquaSure copy is the fixture change. A deposit of `100` is an error, sentence `A deposit percent is a whole number from 0 to 99.` The published bundle stays on the previous percent.

## Wiring the running app

The protocols already declare these methods. `quotedesk/infrastructure/demo.py` does not implement them. Add the methods. Do not add a port and do not change a use case.

On `Unit`, matching `UnitOfWork`:

| Method | Behaviour |
| --- | --- |
| `list_changes` | The `ChangeRecord` values already stored for that tenant |
| `find_operator_result` | The `ApproveResult` stored for that tenant and key, or `None` |
| `save_operator_result` | Stage that result; `commit` makes it visible; `rollback` drops the stage |
| `list_audits` | The audit events already stored for that tenant |

On `QuoteLookup`:

| Method | Behaviour |
| --- | --- |
| `list_for` | The committed quotes for that tenant |

On `Policies`, matching the library in `tests/use_cases/test_publish_policy.py`:

| Method | Behaviour |
| --- | --- |
| `draft` | The in-memory draft, or `None` before the editor has stored one |
| `get` | A published bundle by version id |
| `save_published` | That bundle becomes what `published()` returns. The previous version stays readable |
| `find_publish` | The version id already stored for that idempotency key |
| `remember_publish` | Store that key |

`install` constructs `ListPending`, `ApproveException`, `RejectException`, and `PublishPolicy` with the objects it already builds, and stores them on `app.state`. `quotedesk/infrastructure/container.py` includes the two routers. It does not change `_model`, `QuoteScript`, or `SparkTurn`.

Tenant A is `11111111-1111-4111-8111-111111111111`, the id `install` already puts on `app.state.tenant_id`. The pages use that context. They do not take a tenant from the query string.

## Tests you add

`tests/adapters/test_console.py` and `tests/adapters/test_editor.py`. The TestClient drives the pages. The use-case tests stay untouched.

Seed the console test the way `tests/use_cases/test_approve_exception.py` seeds a pending quote: version `1`, state `PENDING_APPROVAL`, line total `4250.00`, requested percent `Decimal("10")`, stored on the app's unit. Then:

- `GET /console` shows `QD-1042`, version `1`, `10`, cap `5`, and `R 4 250.00`.
- Approve returns version `2` and `R 3 825.00`. A second `GET /console` does not list that quote as waiting.
- Reject on a second pending quote leaves `R 4 250.00`.
- A queue with no pending quote says `There is nothing waiting.`

Seed the editor test from the published bundle `install` already loads. Then:

- Posting deposit `100` lists `A deposit percent is a whole number from 0 to 99.` and does not change `published()`.
- Posting deposit `40` and a reason publishes a new version id. `published()` returns that version. A quote issued before the post still has the clauses it already had.

Neither test opens a socket and neither calls `api.meta.ai`.

## Files

You may edit:

- `quotedesk/adapters/inbound/http/` for `console` and `editor` only, plus their templates
- `quotedesk/infrastructure/demo.py` for the methods and the four use-case constructors above
- `quotedesk/infrastructure/container.py` for the two `include_router` lines
- `tests/adapters/test_console.py` and `tests/adapters/test_editor.py`

You must not edit:

- `quotedesk/domain/`
- `quotedesk/application/`
- `seeds/`
- `tests/unit/`
- `tests/use_cases/`
- `quotedesk/adapters/inbound/http/templates/chat.html`
- `quotedesk/adapters/inbound/http/chat.py`
- `quotedesk/adapters/outbound/models/`
- `quotedesk/infrastructure/config.py`
- `pyproject.toml`

## Done when

`GET /console` lists the pending ask, and Approve issues the next version through `ApproveException`. A typed deposit publishes through `PublishPolicy`, and an already issued quote keeps the clauses it had. `pytest tests/adapters/test_console.py tests/adapters/test_editor.py tests/use_cases/test_approve_exception.py tests/use_cases/test_publish_policy.py -q` passes. `lint-imports` passes. The chat files and the Spark adapter are unchanged.

## Out of scope

The chat turn, `MODEL`, the Spark adapter, photo enrichment, voice, video, SAM, Excel import on the page, a clause word processor, an impact preview, rollback on the page, Wonder, live WhatsApp, and live PayFast. `RollbackPolicy` stays a use case with no button. `ImportRateCard` stays a use case with no upload on this page.
