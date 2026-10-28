# Approve exception

Written 1 November 2026. Tests and the four use cases below implement this note and nothing beyond it.

The decisions in the Sunday plan are confirmed. D6 and D9 stay. `RequestChange` does not approve its own exception. This note applies the approval it stored.

A 10 percent request on an issued version 1 moves version 1 to `PENDING_APPROVAL` and does not append a version. Approve then issues version 2. Version 1 remains, `REVISED`, with its original lines. Reject moves that same version back to `ISSUED`. It does not append a version. The lines stay. It does not use `REJECTED`.

`price` still returns `discount_percent` `Decimal("0")` when the facts carry `Decimal("10")`. Approve does not call `price`.

## The one new transition

`PENDING_APPROVAL` gains one legal outbound pair, to `REVISED`. The other 22 pairs stay. No pair is removed.

`revise` already requires a legal pair to `REVISED`. With this pair, a waiting version can be revised. `tests/unit/domain/test_quote.py` changes the count in `test_every_legal_transition` from `22` to `23` in the same change. The new pair is `(QuoteState.PENDING_APPROVAL, QuoteState.REVISED)`.

`apply_approval` is unchanged. It stores an `Approval` on the version the write names. It does not append a version. `at` equal to `expires_at` is kept. `at` after `expires_at` raises `PolicyViolation`, code `policy.violation`, sentence `An approval after expiry does not apply.`

## Modules

| Use case | Module |
| --- | --- |
| `ApproveException` | `quotedesk.application.use_cases.operator.approve_exception` |
| `RejectException` | `quotedesk.application.use_cases.operator.reject_exception` |
| `ListPending` | `quotedesk.application.use_cases.operator.list_pending` |
| `AuditTimeline` | `quotedesk.application.use_cases.operator.audit_timeline` |

Each method is `execute(context, data)`, except `ListPending.execute(context)` and `AuditTimeline.execute(context, conversation_id)`.

Application may import `quotedesk.domain`. It does not import an adapter. None of the four calls a model, `decide`, `price`, `select_clauses`, or `schedule`.

| Piece | Module |
| --- | --- |
| `ApproveExceptionInput`, `RejectExceptionInput` | `quotedesk.application.dto.tool_inputs` |
| `ApproveResult`, `PendingRow` | `quotedesk.application.dto.tool_outputs` |
| `ChangeRecord` | `quotedesk.application.dto.changes` |
| `AuditEvent` | `quotedesk.application.dto.audit` |
| `Approval`, `Quote` | `quotedesk.domain.quotes.quote` |

Fakes for the quote repository, the change records, the settings, the clock, and the unit of work live in the tests. `commit` makes the staged quote and the audit event visible. `rollback` drops the stage. The tests do not open a database and do not add a column to `audit_event`.

## Input

Frozen Pydantic models. `extra` is forbid.

```text
ApproveExceptionInput
    quote_id: QuoteId
    version: int
    idempotency_key: str
    expires_at: datetime

RejectExceptionInput
    quote_id: QuoteId
    version: int
    idempotency_key: str
```

Neither input carries a price, a percent, or a clause sentence. The percent is read from the stored `ChangeRecord.requested_discount_percent`.

| Payload | Result |
| --- | --- |
| The fields above | Valid |
| `unit_price`, `total`, `discount_percent`, or any other unknown field | `pydantic.ValidationError` |

The failure is `pydantic.ValidationError`. It is not the domain `ValidationError`.

The fixture approve key is `approve-1`. The fixture reject key is `reject-1`. A key is a non-empty string.

## Clock and expiry

The clock is injected. The fixture `at` is `datetime(2026, 11, 1, 8, 0, tzinfo=timezone.utc)`.

`apply_approval` runs on the pending version before `revise`. The approval is `Approval(applies_to_version=version, expires_at=expires_at)`.

| `at` against `expires_at` | Result |
| --- | --- |
| `at` after `expires_at` | `PolicyViolation`, code `policy.violation`, sentence `An approval after expiry does not apply.` The quote still has one version. That version stays `PENDING_APPROVAL` at `4250.00`. |
| `at` equal to `expires_at` | The approval is stored, then version 2 is issued |
| `at` before `expires_at` | The approval is stored, then version 2 is issued |

## Starting quote

The tests start from the quote `RequestChange` leaves for a 10 percent ask. Cap 5. One version.

| Field | Value |
| --- | --- |
| `quote_id` | `QD-1042` |
| Version | `1` |
| State | `PENDING_APPROVAL` |
| Line | `TANK-5000`, quantity `1`, unit price `4250.00`, total `4250.00` |
| `requested_discount_percent` | `Decimal("10")` |
| Expiry | The expiry version 1 already has |

Tenant A is `11111111-1111-4111-8111-111111111111`. Tenant B is `22222222-2222-4222-8222-222222222222`.

## Approve

The reduction is the one `RequestChange` uses under the cap. For each line, the new unit price and the new total are `Money((amount * (100 - percent)) / 100)`. `Money` quantizes to cents with half-even rounding. `4250.00` at 10 percent is `3825.00`.

On success, in this order:

1. `apply_approval` on version 1.
2. `revise` with `Outcome.FIXED_OFFER`, the reduced lines, the same clauses, and the same expiry.

Version 1 becomes `REVISED`. Its line total stays `4250.00`. Its `approvals` contain the approval whose `applies_to_version` is `1`.

Version 2 is `ISSUED`. Its line total is `3825.00`. Its `approvals` are empty. The approval is not copied onto version 2.

Applying that same approval to version 2 raises `PolicyViolation`, code `policy.violation`, sentence `An approval applies to one version.`

The result is `ApproveResult` with `version` `2`, `state` `ISSUED`, `discount_percent` `Decimal("10")`, and those lines.

The audit action is `quote.approved`. `version` on the event is `2`. `actor` is `owner`.

The same idempotency key twice returns the first result. The quote still has two versions. `revise` does not run again.

A missing tenant raises `TenantRequired`. An unknown quote id raises `QuoteNotFound`. A version that is not current raises `StaleQuote`, code `quote.stale`, sentence `That version is no longer the current quote.` A current version that is not `PENDING_APPROVAL` raises `PolicyViolation`, code `policy.violation`, sentence `That quote is not waiting for approval.` A waiting change whose `requested_discount_percent` is `None` raises `PolicyViolation`, code `policy.violation`, sentence `That request has no discount to approve.` Sunday does not delete a clause on approve.

## Reject

`transition` of the pending version to `ISSUED`. One version remains. The line total stays `4250.00`. `approvals` stay empty. `revise` is not called. `apply_approval` is not called.

The result is `ApproveResult` with `version` `1`, `state` `ISSUED`, `discount_percent` `Decimal("0")`, and the original lines.

The audit action is `quote.change_rejected`. `version` on the event is `1`. `actor` is `owner`.

The same idempotency key twice returns the first result and does not write a second audit event.

## Queue

`ListPending` returns the quotes whose current state is `PENDING_APPROVAL` for the tenant in the context. The frozen `ChangeRecord.result.state` is not the filter. After approve, version 2 is `ISSUED`, so that quote is absent.

Each `PendingRow` carries `quote_id`, `version`, `requested_discount_percent`, `discount_cap_percent`, and `total`. The cap comes from `TenantSettings`. The total is the current version's line totals. For the fixture that is version `1`, percent `Decimal("10")`, cap `Decimal("5")`, total `4250.00`.

Tenant A and tenant B each have one pending quote. A's list has one row. B's quote id is absent from A's list. A missing tenant raises `TenantRequired`.

## Timeline

`AuditEvent` keeps `tenant_id`, `action`, `quote_id`, and `version`. Three fields are added, with defaults, so a Saturday constructor still builds:

| Field | Default |
| --- | --- |
| `actor` | `system` |
| `at` | `None` |
| `conversation_id` | `None` |

`AuditTimeline` returns the events stored for that `conversation_id`, in record order. An event with `conversation_id` `None` is absent.

The write path this note can see is three events, not four. Saturday stored no receive event on this quote.

| Order | Action | Actor |
| --- | --- | --- |
| 1 | `quote.issued` | `system` |
| 2 | `quote.change_requested` | `system` |
| 3 | `quote.approved` | `owner` |

The block A tests record these through the in-memory unit. They do not alter `audit_event`.
