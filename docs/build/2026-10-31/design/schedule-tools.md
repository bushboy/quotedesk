# CheckAvailability and HoldSlot

Written 31 October 2026. Tests and the two modules below implement this note and nothing beyond it.

The proposed shape in the Saturday plan is confirmed. The conversation can read a window. It can hold one only after payment. D7 stays as confirmed. A hold exists only after the deposit is paid.

Both use cases call `schedule`. Neither one edits `quotedesk.domain.services.schedule` or `quotedesk.domain.quotes.schedule`. The capacity object passed into `schedule` is left unchanged by `schedule`. A use case saves a returned capacity only when a hold succeeds.

`GetQuote` still does not call `schedule`.

## Modules

| Use case | Module |
| --- | --- |
| `CheckAvailability` | `quotedesk.application.use_cases.tools.check_availability` |
| `HoldSlot` | `quotedesk.application.use_cases.tools.hold_slot` |

```text
CheckAvailability.execute(context, data) -> AvailabilityResult
HoldSlot.execute(context, data) -> HoldResult
```

`context` of `None` raises `TenantRequired` before `schedule` is called.

## Inputs

Frozen. `extra` is forbid.

```text
CheckAvailabilityInput
    job_type: str
    requested_date: date | None = None

HoldSlotInput
    quote_id: QuoteId
    requested_date: date
    idempotency_key: str
```

`HoldSlot` does not take a price. A field `unit_price` fails `pydantic.ValidationError`.

## What the read calls

`requested_date` omitted: `ScheduleRequest.kind` is `earliest`. `requested_date` set: `kind` is `requested_date`. `kind` is never `hold` on this path.

The fixture is the earliest-window row in [schedule.md](../../2026-10-30/design/schedule.md). `today` is Wednesday 28 October 2026. `at` is `datetime(2026, 10, 28, 8, 0, tzinfo=timezone.utc)`. `job_type` is `replacement`. `quote_issued` is true. Friday 30 October 2026 has one place and no holds.

`schedule` returns status `indicative` and `earliest_window` `date(2026, 10, 30)`. The use case returns that window and that status. It does not save the capacity. `remaining` for 30 October is the same before the call and after the call.

```text
AvailabilityResult
    status: str
    earliest_window: date | None
    sentence: str
```

## What the hold calls

`ScheduleRequest.kind` is `hold`. `requested_date` is the input date. `DepositState.paid` comes from `Deposits.paid(tenant_id, quote_id)`. The test sets that flag. This use case does not decide that a quote was paid.

The capacity store is read, passed into `schedule`, and written back only when `schedule` returns.

## One hold

The same `idempotency_key` twice. The fixture key is `hold-1`. The first call finds `paid` true, calls `schedule`, and saves the returned capacity. One `SlotHold` is on that day. The second call returns the stored `HoldResult` and does not call `schedule`. The hold count stays 1.

```text
HoldResult
    status: str
    held_window_start: date
    hold_expires_at: datetime
```

The first result's `status` is `held`. `hold_expires_at` is the instant `schedule` computed, `at` plus 48 hours for the fixture settings.

## Unpaid

`paid` is false. The use case still calls `schedule`. `schedule` raises `PolicyViolation` with code `policy.violation` and sentence `A window is held only after the deposit is paid.` This use case does not catch it. It does not save. The stored capacity is the capacity from before the call. `remaining` is unchanged. No `HoldResult` is returned.
