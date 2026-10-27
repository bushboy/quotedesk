# Schedule

Written 30 October 2026. Tests and `quotedesk/domain/services/schedule.py` implement this note and nothing beyond it. The commitment types live in `quotedesk/domain/quotes/schedule.py`.

D8, D4, and D7 are confirmed as written in the week plan. They are not overturned. The proposed shape in the Friday plan is confirmed. SCHED-07 sets schedule status `escalated` and does not move a quote.

One function creates a date commitment. The sentence comes from a template in settings. The function does not parse a customer sentence, mint an id, or change a quote.

## Modules

`quotedesk.domain.services.schedule` holds `civil_date` and `schedule`.

`quotedesk.domain.quotes.schedule` holds the value types.

Imports allowed: the standard library, Pydantic, and `quotedesk.domain`. Neither module calls `datetime.now` or `date.today`. Neither reads the environment or the network.

Value types are frozen Pydantic models with extra fields forbidden. `schedule` returns a new result. The capacity object passed in is unchanged.

## Civil date

```text
civil_date(at: datetime, zone: ZoneInfo) -> date
```

`at` is aware. A naive `datetime` raises `ValidationError` with code `schedule.instant_naive` and sentence `A schedule instant needs a timezone.` The function converts `at` into `zone` and returns that civil date. It does not read the clock.

D8. This is the only conversion.

| Call | Result |
| --- | --- |
| 30 October 2026 22:30 UTC, zone `Africa/Johannesburg` | Saturday 31 October 2026 |

The instant is `datetime(2026, 10, 30, 22, 30, tzinfo=timezone.utc)`. The zone is `ZoneInfo("Africa/Johannesburg")`. Johannesburg is two hours ahead of UTC, so the civil date is `date(2026, 10, 31)`.

## Signature

```text
schedule(request, capacity, settings, deposit_state, *, today, at) -> ScheduleResult
```

`today` must be a `datetime.date` and must not be a `datetime`. The check is `type(today) is date`. A `datetime` raises `ValidationError` with code `schedule.not_a_date` and sentence `A schedule date is a calendar date.` That check runs before any status is chosen.

`at` follows the same aware-instant rule as `civil_date`, with the same code and sentence.

## Request

`ScheduleRequest` fields:

| Field | Type |
| --- | --- |
| `kind` | `lead_time`, `earliest`, `requested_date`, `hold`, `confirm`, or `guarantee` |
| `quote_issued` | `bool` |
| `job_type` | `str` |
| `requested_date` | `date` or `None` |
| `site_measure_signed_off` | `bool` |
| `materials_confirmed` | `bool` |

There is no override field. A payload that includes `override` fails validation because extra fields are forbidden.

`requested_date`, when set, is a civil date. A `datetime` is rejected with `schedule.not_a_date`.

"Now now" is not a sentence the function reads. It is a `requested_date` equal to `today`.

A guarantee is `kind` `guarantee`. It is not a match on the words in a message.

## Capacity

A `Capacity` is a tuple of `CapacitySlot`.

| Field on `CapacitySlot` | Type |
| --- | --- |
| `day` | `date` |
| `places` | `int` |
| `holds` | `tuple[SlotHold, ...]` |

`SlotHold` has `hold_expires_at: datetime`.

`capacity.remaining(day, at) -> int` is `places` minus the holds on that day whose `hold_expires_at` is greater than or equal to `at`. A hold with `hold_expires_at < at` does not consume a place. An instant equal to `hold_expires_at` is still held.

A day with no slot has remaining `0`.

## Settings

| Field | Fixture |
| --- | --- |
| `lead_time_working_days` | `replacement` → `5` |
| `minimum_notice_working_days` | `2` |
| `hold_period_hours` | `48` |
| `working_days` | Monday to Friday. Monday is `0` and Sunday is `6` |
| `blocked_dates` | `date(2026, 11, 2)` |
| `sentences` | the templates below |

Working days are those weekdays, excluding `blocked_dates`. Saturday and Sunday are not working days. 2 November 2026 is a Monday and it is blocked.

| Template key | Text |
| --- | --- |
| `lead_time` | `A {job_type} is usually about {lead_time_working_days} working days after the deposit.` |
| `earliest` | `The earliest window is {window}, and it is not reserved.` |
| `requested_open` | `That date is open. We can hold it when the deposit is paid.` |
| `requested_closed` | `That date is full. The next open days are {first} and {second}.` |
| `too_soon` | `That date is too soon. The earliest window is {window}.` |
| `next_working_day` | `The next working day is {window}.` |
| `held` | `That window is held until the deposit hold expires.` |
| `confirmed` | `That date is confirmed.` |
| `escalated` | `We can't guarantee a date here.` |

A `{window}`, `{first}`, or `{second}` value is the civil date as `YYYY-MM-DD`. The function does not format `3 November 2026`. A template that is missing, or a placeholder the settings cannot fill, raises `PolicyViolation` with code `policy.violation` and sentence `A schedule sentence has no template.`

The function does not hard-code a date or a rand amount. Those strings live on the settings object the test builds.

## Result

`ScheduleResult` has `commitment: ScheduleCommitment` and `capacity: Capacity`.

| Field on `ScheduleCommitment` | Type |
| --- | --- |
| `status` | `none`, `indicative`, `held`, `confirmed`, or `escalated` |
| `sentence` | `str` |
| `earliest_window` | `date` or `None` |
| `requested_date` | `date` or `None` |
| `held_window_start` | `date` or `None` |
| `held_window_end` | `date` or `None` |
| `hold_expires_at` | `datetime` or `None` |
| `window_id` | `str` or `None` |
| `offered_dates` | `tuple[date, ...]` |
| `depends_on` | `tuple[str, ...]` |

`window_id` is `None` on every result. The function does not mint one.

Hold fields empty means `held_window_start`, `held_window_end`, and `hold_expires_at` are all `None`.

A returned window is one civil day: `held_window_start` and `held_window_end` are that same date. `offered_dates` lists the dates named to the customer, in order.

The commitment has no quote state. `schedule` does not receive a `Quote` and does not return one.

## Order

The function walks this list and stops at the first match. A later row does not run.

1. `kind` is `guarantee`. Status `escalated`. Sentence is the `escalated` template. `offered_dates` is empty. Hold fields are empty. `depends_on` is empty. Capacity is the input capacity, value for value.
2. `quote_issued` is false. Status `none`. Sentence is the `lead_time` template filled from `job_type`. For `replacement` the sentence contains `5`. `window_id` is `None`. `earliest_window` is `None`. Capacity is unchanged.
3. `kind` is `hold` and `deposit_state.paid` is false. Raise `PolicyViolation` with code `policy.violation` and sentence `A window is held only after the deposit is paid.` There is no result. Capacity is unchanged. D7.
4. `kind` is `hold` and `remaining(requested_date, at)` is `0`. Raise `PolicyViolation` with code `policy.violation` and sentence `That window has no place left.` Capacity is unchanged.
5. `kind` is `hold` and the deposit is paid and a place remains. Status `held`. `hold_expires_at` is `at` plus 48 hours. `held_window_start` and `held_window_end` are `requested_date`. The returned capacity is the input plus one `SlotHold` on that day. `remaining` for that day is one lower. The input capacity is unchanged.
6. `kind` is `confirm` and the deposit is unpaid. The same refusal as row 3.
7. `kind` is `confirm` and either dependency is false. Status `held`. Sentence is the `held` template. Capacity is unchanged. `depends_on` lists each missing name, `site_measure_signed_off` before `materials_confirmed`.
8. `kind` is `confirm` and both dependencies are true. Status `confirmed`. Sentence is the `confirmed` template. `depends_on` is empty. Capacity is unchanged. The held window is `requested_date`.
9. `requested_date` is set, that day is not a working day, and the snapshot has no slot on it. Status `indicative`. Sentence is the `next_working_day` template. `earliest_window` is the first working day strictly after `requested_date` that is not blocked and has a place left. Minimum notice is not added on top of this search. Hold fields are empty. The sentence does not contain `held`. Capacity is unchanged.
10. `requested_date` is set and it is before the earliest legal working day. Status `indicative`. Sentence is the `too_soon` template. `earliest_window` is that legal day. Hold fields are empty. Capacity is unchanged.
11. `requested_date` is set and `remaining` on that day is `0`. Status `indicative`. Sentence is the `requested_closed` template. `offered_dates` is the next two working days, strictly after `requested_date`, that are not blocked and have a place left. The sentence does not contain `held`. Hold fields are empty. Capacity is unchanged.
12. `requested_date` is set and `remaining` on that day is greater than `0`. Status `indicative`. Sentence is the `requested_open` template. `earliest_window` is that date. Hold fields are empty. Capacity is unchanged.
13. `kind` is `earliest`. Status `indicative`. Sentence is the `earliest` template. `earliest_window` is the earliest legal working day that has a place left. Hold fields are empty. Capacity is unchanged.

`DepositState` has `paid: bool`. Rows other than 3, 5, and 6 do not read it.

The earliest legal working day is the working day reached by counting `minimum_notice_working_days` working days strictly after `today`, skipping blocked dates. With `today` of Wednesday 28 October 2026, Thursday 29 October is 1 and Friday 30 October is 2. The earliest legal day is `date(2026, 10, 30)`, provided that day has a place left.

A date equal to `today` is before that day. It takes row 9. That is the "now now" request.

## Fixtures the tests build

`today` is Wednesday 28 October 2026 unless a row below says otherwise. `at` is `datetime(2026, 10, 28, 8, 0, tzinfo=timezone.utc)` unless a row says otherwise. `job_type` is `replacement`. `quote_issued` is true except for the lead-time row.

| Test | What is different | Result |
| --- | --- | --- |
| Lead time before a quote | `quote_issued` false, `kind` `lead_time` | Status `none`. Sentence contains `5`. `window_id` is `None`. |
| Earliest window | `kind` `earliest`. Friday 30 October has a place | Status `indicative`. `earliest_window` is `2026-10-30`. Remaining capacity is unchanged. |
| Saturday open | `kind` `requested_date`, `requested_date` `2026-10-31`, that slot has `places` 1 and no holds | Status `indicative`. Hold fields empty. Sentence is the `requested_open` template. |
| Saturday full | Same Saturday, `places` 0 | Status `indicative`. `offered_dates` is `2026-11-03` then `2026-11-04`. Sentence does not contain `held`. |
| Inside minimum notice | `requested_date` `2026-10-29` | Status `indicative`. `earliest_window` is `2026-10-30`. |
| Now now | `requested_date` equals `today` | Same result as the row above. |
| Hold after deposit | `kind` `hold`, `paid` true, Saturday `places` 1 | Status `held`. `hold_expires_at` is `2026-10-30 08:00 UTC`. Returned remaining is `0`. Input remaining stays `1`. |
| Hold without deposit | `kind` `hold`, `paid` false, Saturday `places` 1 | `PolicyViolation`. Input remaining stays `1`. |
| Confirmed | `kind` `confirm`, `paid` true, both flags true, `requested_date` `2026-10-30` | Status `confirmed`. `depends_on` is empty. |
| One dependency missing | The same, with `site_measure_signed_off` false | Status `held`. `depends_on` is `("site_measure_signed_off",)`. Capacity is unchanged. |
| Guarantee | `kind` `guarantee` | Status `escalated`. `offered_dates` empty. Hold fields empty. |
| Skip the weekend | `today` `2026-10-31`, `requested_date` `2026-10-31`, no Saturday slot | Status `indicative`. `earliest_window` is `2026-11-03`. |
| Second hold | `places` 1. First hold succeeds. The second call receives the returned capacity | The second call raises `That window has no place left.` The snapshot still has one hold. |
| Expired hold | `places` 1, one hold expiring `2026-10-28 07:59 UTC`, `at` is `08:00 UTC` | That hold does not consume the place. A new hold succeeds. |

An instant equal to `hold_expires_at` still consumes the place. The expired-hold test uses an instant that is strictly earlier.
