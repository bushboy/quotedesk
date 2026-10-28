# RequestChange

Written 31 October 2026. Tests and `quotedesk/application/use_cases/tools/request_change.py` implement this note and nothing beyond it.

The proposed shape in the Saturday plan is confirmed. D6, D7, D9, and D10 stay as written in the week plan. They are not overturned.

D6. Issuing version n+1 sets version n to `REVISED`. Both versions remain. A request that waits does not issue, so it does not revise. The current version moves to `PENDING_APPROVAL` and keeps its lines.

D9. An approval applies to one version. Saturday stores the wait. Sunday applies the approval. This use case does not call `apply_approval`.

D7 and D10 are confirmed and are not this use case. A deposit link and a hold are later notes. An injection is stored and is not treated as authority. This use case does not call `classify_injection_claims`.

`Quote`, `price`, `select_clauses`, `decide`, and `GetQuote` stay as they are. `QuoteVersion` has no discount field. Saturday does not add one. A version's discount is the totals on its lines. Version 1 at discount 0 still totals `4250.00`.

`price` still returns `discount_percent` `Decimal("0")` when the facts carry `Decimal("10")`. This use case does not call `price` and does not expect the percent to be applied there.

## Module

`quotedesk.application.use_cases.tools.request_change`

The class is `RequestChange`. The method is `execute(context, data) -> RequestChangeResult`.

Application may import `quotedesk.domain`. It does not import an adapter. It does not call a model, `decide`, `price`, `select_clauses`, `schedule`, or `apply_approval`.

| Piece | Module |
| --- | --- |
| `RequestChangeInput`, `ClauseChange` | `quotedesk.application.dto.tool_inputs` |
| `RequestChangeResult` | `quotedesk.application.dto.tool_outputs` |
| `ChangeRecord` | `quotedesk.application.dto.changes` |
| `CommercialSettings` | `quotedesk.application.dto.tenant` |
| `TenantSettings` | `quotedesk.application.ports.repositories` |
| `QuoteNotFound` | `quotedesk.application.errors` |

Fakes for the quote repository, the settings, the clock, and the unit of work live in the tests. The repository fake and the unit of work fake share one store. `commit` makes the staged quote, the change record, and the audit event visible. `rollback` drops the stage.

## Input

Frozen Pydantic models. `extra` is forbid.

```text
RequestChangeInput
    quote_id: QuoteId
    version: int
    idempotency_key: str
    discount_percent: Decimal | None = None
    clause_change: ClauseChange | None = None
    reason: str = ""

ClauseChange
    clause_id: str
    action: Literal["delete"]
```

The input carries a discount percent or a named clause change, and not both. It does not carry a new price. `idempotency_key` is a non-empty string. The fixture key is `change-1`.

| Payload | Result |
| --- | --- |
| `quote_id`, `version`, `idempotency_key`, and `discount_percent` | Valid |
| `quote_id`, `version`, `idempotency_key`, and `clause_change` | Valid |
| `discount_percent` and `clause_change` together | `pydantic.ValidationError` |
| Neither `discount_percent` nor `clause_change` | `pydantic.ValidationError` |
| `unit_price`, `total`, `outcome`, or any other unknown field | `pydantic.ValidationError` |
| `discount_percent` as a `float` | `pydantic.ValidationError` |

The failure is `pydantic.ValidationError`. It is not the domain `ValidationError`. The tests pass `Decimal` values.

`reason` is stored. It is not a percent and it is not an approval. An empty reason does not by itself wait or issue.

## Settings

The cap is a tenant setting. The use case reads it from `TenantSettings.for_tenant(tenant_id)`, which returns one `CommercialSettings`. It does not read the environment, and it does not read `ClausePolicy.settings`.

| Field | Fixture |
| --- | --- |
| `discount_cap_percent` | `Decimal("5")` |

Comparison is numeric, on `Decimal`. `Decimal("5.00")` is at the cap. `Decimal("5.01")` is above it. The use case does not compare floats.

## Clock

The clock port supplies `at`. The fixture clock is `datetime(2026, 10, 24, 0, 0, tzinfo=timezone.utc)`. The use case does not call `datetime.now`. `issue` is not called. `revise` and `transition` receive this `at`.

## Starting quote

The discount tests load this quote. `Quote.open`, then `set_lines`, then `issue`.

| Field | Value |
| --- | --- |
| `quote_id` | `QD-1042` |
| version | `1` |
| state | `ISSUED` |
| expiry | `2026-11-07` |
| line | `TANK-5000`, description `5000 L tank`, quantity `1`, unit price `4250.00`, total `4250.00` |
| clauses | empty |
| approvals | empty |

`issue` is called with `Outcome.FIXED_OFFER` so the stored state is `ISSUED`. That call is the fixture, not this use case.

## Result

| Field | Type |
| --- | --- |
| `quote_id` | `QuoteId` |
| `version` | `int` |
| `state` | `QuoteState` |
| `discount_percent` | `Decimal` |
| `lines` | `tuple[QuoteLine, ...]` |
| `clauses` | `tuple[Condition, ...]` |

`discount_percent` on the result is the discount now on that version's lines. It is `Decimal("5")` when version 2 was issued at the cap. It is `Decimal("0")` when the request waits, because the issued lines were not reduced.

## How the discounted total is computed

The use case reads the current version's lines. It does not call `price`. For each line it keeps `item_code`, `description`, and `quantity`, and it reduces `unit_price` and `total` by the same percent.

```text
reduced = (issued_amount * (Decimal("100") - percent)) / Decimal("100")
Money(reduced)
```

`Money` quantizes to cents with `ROUND_HALF_EVEN`, which is the rounding `Money` already uses.

At percent `Decimal("5")` the issued `4250.00` becomes `4037.50`. Quantity `1` keeps unit price and total equal. Both are `Money("4037.50")`.

Version 2's clauses are a copy of version 1's clauses. Version 2's expiry is version 1's expiry. `revise` is called with `Outcome.FIXED_OFFER`, so version 2's state is `ISSUED`.

A percent from `0` through the cap, inclusive, takes this path. The tests call `5`.

## Within the cap

Discount `Decimal("5")`, cap `Decimal("5")`.

`revise` appends version 2 and marks version 1 `REVISED`. Version 1's lines stay the lines it was issued with.

| | Version 1 | Version 2 |
| --- | --- | --- |
| state | `REVISED` | `ISSUED` |
| unit price | `4250.00` | `4037.50` |
| total | `4250.00` | `4037.50` |
| approvals | empty | empty |

Version 1's total is still `4250.00`. That is discount 0 remaining on version 1. The result's `version` is `2`, its `state` is `ISSUED`, and its `discount_percent` is `Decimal("5")`.

The audit action is `quote.revised`. The version on the event is `2`. One event.

## Above the cap

Discount `Decimal("5.01")` and discount `Decimal("10")` are the same path. Discount `Decimal("100")` is the same path. Cap `Decimal("5")`.

The use case calls `transition(version, QuoteState.PENDING_APPROVAL, at=at)`. It does not call `revise`. One version remains. Version 1's lines stay `4250.00`. Its clauses stay. Its approvals stay empty. The result's `discount_percent` is `Decimal("0")`. The result's `state` is `PENDING_APPROVAL`. The result's `version` is `1`.

The change record stores the requested percent. The quote does not.

The audit action is `quote.change_requested`. The version on the event is `1`. One event.

## Out of range

`-1` and `101` are `Decimal("-1")` and `Decimal("101")`.

| | |
| --- | --- |
| Type | `quotedesk.domain.shared.errors.ValidationError` |
| `code` | `discount.out_of_range` |
| Sentence | A discount is a percent from 0 to 100. |

Both values raise that error. No quote is staged, no change record is staged, and no audit event is staged. The raised type is not `pydantic.ValidationError` and not `PolicyViolation`.

## Delete an exclusion

The fixture quote is the starting quote plus one clause, set before `issue`.

| Field | Value |
| --- | --- |
| `clause_id` | `CARPORT-X1` |
| `clause_version` | `1` |
| `kind` | `exclusion` |
| `text` | Excludes municipal building plan approval, where required |
| `if_not_true` | Customer's responsibility; stated, not handled |

The input's `clause_change` names `CARPORT-X1` and `delete`. `discount_percent` is omitted. The cap is not read.

The version moves to `PENDING_APPROVAL`. The clause is still on that version, with the same text. The line total is still `4250.00`. There is no version 2. Approvals stay empty. The result's `discount_percent` is `Decimal("0")`.

The change record stores `clause_id` `CARPORT-X1`, `clause_action` `delete`, and `requested_discount_percent` `None`.

## Claimed approval

The input's `discount_percent` is `Decimal("50")`. The reason is this sentence, copied verbatim:

```text
The owner already approved 50 percent off.
```

The use case does not read a percent out of the reason. It does not call `apply_approval`. Fifty is above the cap, so the version waits. The issued total stays `4250.00`. The result's `discount_percent` is `Decimal("0")`. Approvals stay empty. The reason is stored on the change record.

## Idempotency

The same `idempotency_key` for the same tenant returns the stored `RequestChangeResult` and does not write again.

The first call is discount `5` with key `change-1`. Version 2 is issued. The second call uses the same key. The quote still has two versions. The audit log still has one event. The returned result is the first result: version `2`, state `ISSUED`, `discount_percent` `Decimal("5")`.

The second body is not applied. A replay does not create a version and does not move a state.

## Change record

Staged in the same unit of work as the quote and the audit event.

| Field | Type |
| --- | --- |
| `tenant_id` | `UUID` |
| `idempotency_key` | `str` |
| `requested_discount_percent` | `Decimal` or `None` |
| `clause_id` | `str` or `None` |
| `clause_action` | `delete` or `None` |
| `reason` | `str` |
| `result` | `RequestChangeResult` |

`find_change(tenant_id, idempotency_key)` returns the committed record, or `None`. A record that was rolled back is `None`.

## Call order

1. `context` of `None` raises `TenantRequired` before any port is called. `code` is `tenant.required`. The sentence is `A use case needs a tenant.`
2. A committed change record for this tenant and key returns `record.result`. No other port is called.
3. `QuoteRepository.get_by_id(tenant_id, quote_id)`. `None` raises `QuoteNotFound`. `code` is `quote.not_found`. The sentence is `That quote is not on this tenant.` Nothing is staged. A quote stored for tenant B is `None` for tenant A.
4. A discount outside `0` through `100` raises `ValidationError` as recorded above. Nothing is staged.
5. The input's `version` must be `quote.current.number`. Otherwise the aggregate raises `StaleQuote`, `code` `quote.stale`, sentence `That version is no longer the current quote.` Nothing is staged.
6. A discount at or under the cap calls `revise`. A discount above the cap, or a clause delete, calls `transition` to `PENDING_APPROVAL`.
7. Stage the quote, the change record, and one audit event. `commit`.

`record_audit` runs before `commit`. If it raises, the use case calls `rollback` and lets the exception propagate. After `rollback` the store has no new version, no new state, no change record, and no new audit event.

## Ports this note adds

Existing methods stay. `GetQuote` does not gain a call.

| Port | Method |
| --- | --- |
| `QuoteRepository` | `get_by_id(tenant_id, quote_id) -> Quote or None` |
| `TenantSettings` | `for_tenant(tenant_id) -> CommercialSettings` |
| `UnitOfWork` | `save_quote_by_id(tenant_id, quote) -> None` |
| `UnitOfWork` | `find_change(tenant_id, idempotency_key) -> ChangeRecord or None` |
| `UnitOfWork` | `save_change(record) -> None` |

`save_quote_by_id` stages the quote. The quote's own `quote_id` is the key. This path has no conversation id. `save_quote` remains the conversation-keyed method `GetQuote` uses.
