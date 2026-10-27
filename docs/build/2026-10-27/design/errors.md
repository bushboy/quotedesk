# Domain errors

Written 27 October 2026. Tests and `quotedesk/domain/shared/errors.py` implement this note and nothing beyond it.

These are the only failures the domain raises for a broken value or a broken commercial rule. Later slices raise them. They do not raise a bare `Exception` or `ValueError` for these cases.

## Module

`quotedesk.domain.shared.errors`

The module imports nothing from Pydantic and nothing from the other layers. The types are plain exceptions. `ValidationError` here is the domain type. It is not `pydantic.ValidationError`.

## Types

Each type subclasses `DomainError`, which subclasses `Exception` and does not subclass `ValueError`.

| Type | When a later slice uses it |
| --- | --- |
| `ValidationError` | The input is not a legal value. |
| `PolicyViolation` | The value is well formed and the commercial rule refuses it. |
| `InvalidTransition` | A quote state move is not in the legal table. |
| `StaleQuote` | A write names a version that is no longer current. |

Construction stores the arguments unchanged:

```text
ValidationError(code="money.float", sentence="A price must be a decimal amount, not a floating-point number.")
```

| Attribute | Rule |
| --- | --- |
| `code` | A stable string. Callers branch on it. |
| `sentence` | A non-empty human sentence. `__str__` returns it. |

Tuesday's constructors in `Money`, the identifier types, and `DateWindow` raise `ValidationError` only. `PolicyViolation`, `InvalidTransition`, and `StaleQuote` are constructed in tests today and raised by later slices.

## Codes used today

| Code | Raised by | Sentence |
| --- | --- | --- |
| `money.float` | `Money` | A price must be a decimal amount, not a floating-point number. |
| `money.negative` | `Money` | A price cannot be negative. |
| `money.blank` | `Money` | A price is required. |
| `money.currency` | `Money` | Prices are in ZAR. |
| `money.invalid` | `Money` | That amount cannot be used as a price. |
| `quote_id.invalid` | `QuoteId` | A quote id looks like QD-0001. |
| `policy_version_id.invalid` | `PolicyVersionId` | A policy version id looks like water-policy-v1.2. |
| `rule_id.invalid` | `RuleId` | A rule id looks like WATER-F01. |
| `date_window.unordered` | `DateWindow` | A window's end is on or after its start. |
| `date_window.not_a_date` | `DateWindow` | A window is made of calendar dates. |

## Codes reserved for later slices

These are not raised today. The names are fixed so Thursday and Friday do not invent a second spelling.

| Code | Type |
| --- | --- |
| `policy.violation` | `PolicyViolation` |
| `quote.invalid_transition` | `InvalidTransition` |
| `quote.stale` | `StaleQuote` |
