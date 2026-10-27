# Quote

Written 29 October 2026. Tests and `quotedesk/domain/quotes/quote.py` implement this note and nothing beyond it.

D6 and D9 are confirmed as written in the week plan. They are not overturned. The proposed shape in the Thursday plan is confirmed.

One quote, many versions. An issued version is not edited in place. A change is a new version.

`Outcome` stays Wednesday's four values: `fixed_offer`, `indicative_range`, `site_assessment`, `escalation`. The letter-code names are not used. `Decision` still has no amount.

## Module

`quotedesk.domain.quotes.quote`

Imports allowed: the standard library, Pydantic, and `quotedesk.domain`. The aggregate does not read the clock, the environment, or the network. It does not call `datetime.now` or `date.today`. It does not mint an id.

Value types are frozen Pydantic models with extra fields forbidden. Methods return a new `Quote` or raise. The receiver is unchanged.

## Open

```text
Quote.open(quote_id: QuoteId, expiry: date) -> Quote
```

Version 1, state `DRAFT`, empty lines, empty clauses, empty approvals. `quote_id` is stored as passed.

| Call | Result |
| --- | --- |
| `QuoteId("QD-1042")` | Stored. `quote_id.value` is `QD-1042`. |
| `QuoteId("QD-1")` | `ValidationError`, code `quote_id.invalid`, sentence `A quote id looks like QD-0001.` |

`expiry` must be a `datetime.date` and must not be a `datetime`. `datetime` is a subclass of `date`, so the check is the type, not `isinstance`. A `datetime` raises `ValidationError` before it can be stored.

| Code | Sentence |
| --- | --- |
| `quote.expiry_not_a_date` | A quote expiry is a calendar date. |

There is no `next_id` and no generator inside the aggregate.

## States

`QuoteState` values:

`DRAFT`, `PENDING_APPROVAL`, `ISSUED`, `SITE_ASSESSMENT_OFFERED`, `ESCALATED`, `WAITING_FOR_DEPOSIT`, `DEPOSIT_PAID`, `BOOKING_CONFIRMED`, `EXPIRED`, `REJECTED`, `REVISED`.

## Legal pairs

Twenty-two. `transition` performs one pair and does not append a version.

| From | To |
| --- | --- |
| `DRAFT` | `ISSUED`, `SITE_ASSESSMENT_OFFERED`, `ESCALATED`, `PENDING_APPROVAL` |
| `PENDING_APPROVAL` | `ISSUED`, `SITE_ASSESSMENT_OFFERED`, `ESCALATED`, `REJECTED` |
| `ISSUED` | `WAITING_FOR_DEPOSIT`, `EXPIRED`, `REVISED`, `PENDING_APPROVAL` |
| `WAITING_FOR_DEPOSIT` | `DEPOSIT_PAID`, `EXPIRED`, `REVISED` |
| `DEPOSIT_PAID` | `BOOKING_CONFIRMED`, `EXPIRED` |
| `SITE_ASSESSMENT_OFFERED` | `EXPIRED`, `REVISED`, `PENDING_APPROVAL` |
| `ESCALATED` | `PENDING_APPROVAL`, `EXPIRED` |

`BOOKING_CONFIRMED`, `REJECTED`, `EXPIRED`, and `REVISED` have no outbound pair.

These four pairs are illegal. Each raises `InvalidTransition` with code `quote.invalid_transition` and sentence `That state change is not allowed.`

| From | To |
| --- | --- |
| `ISSUED` | `DRAFT` |
| `EXPIRED` | `BOOKING_CONFIRMED` |
| `REJECTED` | `ISSUED` |
| `ESCALATED` | `ISSUED` |

A move to `WAITING_FOR_DEPOSIT` stores no deposit amount and creates no deposit link.

## Versions

`quote.current` is the version with the highest number. `quote.version(n)` returns that version, including one that is no longer current.

`QuoteVersion` fields: `number`, `state`, `expiry`, `lines`, `clauses`, `approvals`, `at`.

`at` is `None` on the version `open` creates. A successful `issue`, `transition`, `revise`, or `apply_approval` records the caller's `at` on the version it writes. `open` has no `at` argument.

`QuoteLine` fields: `item_code: str`, `description: str`, `quantity: Decimal`, `unit_price: Money`, `total: Money`.

A stored clause is a `Condition` from `quotedesk.domain.policy.clauses`.

## Issue

```text
issue(outcome: Outcome, *, version: int, at: datetime) -> Quote
```

The outcome picks the state:

| Outcome | State |
| --- | --- |
| `fixed_offer` | `ISSUED` |
| `indicative_range` | `ISSUED` |
| `site_assessment` | `SITE_ASSESSMENT_OFFERED` |
| `escalation` | `ESCALATED` |

`issue` then takes that single step. Lines, clauses, and expiry stay as they were. A pair that is not in the table raises `InvalidTransition` and returns no new quote.

## Content writes

```text
set_lines(version, lines) -> Quote
set_clauses(version, clauses) -> Quote
set_expiry(version, expiry) -> Quote
```

A content write is allowed only while that version's state is `DRAFT`. On any other state, including `ISSUED`, it raises `PolicyViolation` with code `policy.violation` and sentence `An issued version cannot be changed.` The lines, clauses, and expiry already stored stay as they were.

`set_expiry` rejects a `datetime` with `quote.expiry_not_a_date` before it considers the state.

## Revise

```text
revise(outcome, *, line_items, clauses, expiry, at) -> Quote
```

Allowed only when the current version has a legal pair to `REVISED`. Otherwise `InvalidTransition`, and no version is appended.

On success, D6:

| Version | What is true |
| --- | --- |
| n | State `REVISED`. Its line items, clauses, and expiry are the ones it already had. |
| n+1 | Appended. It is current. Its state is the state `issue` would pick for `outcome`. Its lines, clauses, and expiry are the arguments. |

`transition` of `ISSUED` to `REVISED` does not append a version. `revise` does. The 22-pair test uses `transition`. The version test uses `revise`.

## Stale version

A write names a version number: `issue`, `transition`, `set_lines`, `set_clauses`, `set_expiry`, and `apply_approval`.

When that number is not `current.number`, the write raises `StaleQuote` with code `quote.stale` and sentence `That version is no longer the current quote.` The stale check comes before the transition check and before the content check.

After `revise` has created version 2:

| Write | Result |
| --- | --- |
| `transition(1, EXPIRED, at=...)` | `StaleQuote` |
| `transition(2, WAITING_FOR_DEPOSIT, at=...)` on an `ISSUED` version 2 | The new current state is `WAITING_FOR_DEPOSIT`. |

## Approval

```text
apply_approval(version: int, approval: Approval, *, at: datetime) -> Quote
```

`Approval` has `applies_to_version: int` and `expires_at: datetime`. It has no amount. `expires_at` is the caller's instant. It is not the version's civil `expiry`, and the aggregate does not convert one into the other.

The stale check runs first. Then:

| Case | Result |
| --- | --- |
| `approval.applies_to_version` is not `version` | `PolicyViolation`, code `policy.violation`, sentence `An approval applies to one version.` Nothing is stored. |
| `at` is after `approval.expires_at` | `PolicyViolation`, code `policy.violation`, sentence `An approval after expiry does not apply.` Nothing is stored. |
| `at` is equal to `approval.expires_at` | The approval is stored on that version. |
| `at` is before `approval.expires_at` | The approval is stored on that version. |

D9. An approval for version 1, applied by a write of version 2, raises. An instant equal to `expires_at` is kept. An instant after `expires_at` raises. The comparison is `at > expires_at`.

## Sentences

| Code | Type | Sentence |
| --- | --- | --- |
| `policy.violation` | `PolicyViolation` | `An issued version cannot be changed.` |
| `policy.violation` | `PolicyViolation` | `An approval applies to one version.` |
| `policy.violation` | `PolicyViolation` | `An approval after expiry does not apply.` |
| `quote.invalid_transition` | `InvalidTransition` | `That state change is not allowed.` |
| `quote.stale` | `StaleQuote` | `That version is no longer the current quote.` |
| `quote.expiry_not_a_date` | `ValidationError` | `A quote expiry is a calendar date.` |
| `quote_id.invalid` | `ValidationError` | `A quote id looks like QD-0001.` |
