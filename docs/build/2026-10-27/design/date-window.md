# DateWindow

Written 27 October 2026. Tests and `quotedesk/domain/shared/windows.py` implement this note and nothing beyond it.

A `DateWindow` is two civil dates, `start` and `end`. Callers pass dates in Africa/Johannesburg. This type does not read the clock, does not read the environment, and does not convert time zones.

## Module

`quotedesk.domain.shared.windows`

Imports allowed: the standard library and Pydantic. The type is a frozen Pydantic model.

## Construction

`DateWindow(start=date(2026, 11, 7), end=date(2026, 11, 7))`

| Input | Result |
| --- | --- |
| `start` equal to `end` | Accepted. A one-day window. |
| `end` after `start` | Accepted. |
| `end` before `start` | `date_window.unordered` |
| A naive `datetime` in either field | `date_window.not_a_date` |
| A timezone-aware `datetime` in either field | `date_window.not_a_date` |

Pydantic must not coerce a `datetime` into a `date`. The validator rejects `datetime` before that coercion. Only `datetime.date` is stored.

Failures raise `quotedesk.domain.shared.errors.ValidationError` with the code above and a non-empty sentence.

| Code | Sentence |
| --- | --- |
| `date_window.unordered` | A window's end is on or after its start. |
| `date_window.not_a_date` | A window is made of calendar dates. |

## contains

`contains(day) -> bool`

The start date and the end date are inside the window. The day before the start and the day after the end are outside.

`day` must be a `datetime.date`. A `datetime` raises `date_window.not_a_date`.

## Examples

Window 7 November 2026 through 9 November 2026:

| Day | Inside |
| --- | --- |
| 6 November 2026 | No |
| 7 November 2026 | Yes |
| 9 November 2026 | Yes |
| 10 November 2026 | No |
