# GetQuoteStatus

Written 31 October 2026. Tests and `quotedesk/application/use_cases/tools/get_quote_status.py` implement this note and nothing beyond it.

The proposed shape in the Saturday plan is confirmed. The card can be opened only with the verification code. A wrong code reveals nothing.

This use case does not mint a code. It does not call `schedule`. It does not change the quote. `GetQuote` remains the path that does not call `schedule`, and this read does not call it either.

## Module

`quotedesk.application.use_cases.tools.get_quote_status`

```text
GetQuoteStatus.execute(context, data) -> QuoteStatusResult
```

| Piece | Module |
| --- | --- |
| `GetQuoteStatusInput`, `QuoteStatusResult` | `quotedesk.application.dto.tool_outputs` for the result, `tool_inputs` for the input |
| `VerificationCodes` | `quotedesk.application.ports.repositories` |

The port that mints a code is `VerificationCodes.issue(tenant_id, quote_id) -> str`. `GetQuote` does not call it. `GetQuoteStatus` does not call it. The test fake counts `issue` calls and expects 0. The read calls only `VerificationCodes.matches(tenant_id, quote_id, code) -> bool`.

`context` of `None` raises `TenantRequired` before the quote is loaded.

## Input

Frozen. `extra` is forbid.

```text
GetQuoteStatusInput
    quote_id: QuoteId
    verification_code: str | None = None
```

A missing code is `None` or `""`. Both take the empty path.

## Empty result

Wrong code, missing code, and a code that belongs to a different quote return one value. The three results compare equal.

| Field | Empty value |
| --- | --- |
| `found` | `False` |
| `state` | `None` |
| `expiry` | `None` |
| `version` | `None` |
| `schedule_status` | `None` |

There is no field that says whether the quote id exists. A quote that is not on the tenant is the same empty result as a wrong code.

The fixture quote is `QD-1042`. Its code is `1042`. Quote `QD-1043` has code `1043`.

| Code sent with `QD-1042` | Result |
| --- | --- |
| `0000` | empty |
| `None` | empty |
| `""` | empty |
| `1043` | empty |
| `1042` | the opened card below |

`matches` is an exact string compare. The use case does not trim a code and does not accept a code from another quote id.

## Opened card

The right code on the issued fixture.

| Field | Value |
| --- | --- |
| `found` | `True` |
| `state` | `ISSUED` |
| `expiry` | `2026-11-07` |
| `version` | `1` |
| `schedule_status` | `none` |

`schedule_status` is `none` because this use case does not call `schedule` and the quote has no stored commitment. The quote row is the same after the call as before it.

## Expired

The right code `1042` on a quote whose current state is `EXPIRED`. The result's `state` is `EXPIRED`. `found` is true. `expiry`, `version`, and `schedule_status` are still returned, so the customer can see that it lapsed. The use case does not transition the quote while reading. The fixture is already `EXPIRED` before the call. That transition is `Quote.transition` in the test, not in this use case.
