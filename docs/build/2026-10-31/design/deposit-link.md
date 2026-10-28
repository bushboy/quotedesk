# CreateDepositLink

Written 31 October 2026. Tests and `quotedesk/application/use_cases/tools/create_deposit_link.py` implement this note and nothing beyond it.

The proposed shape in the Saturday plan is confirmed. D7 stays as confirmed. A deposit link follows recorded acceptance, and only for an issued quote. A site assessment and an escalation never get one. This note does not hold a slot. A hold remains `HoldSlot`'s work, and only after payment.

The URL is a sandbox URL. This use case does not call PayFast. It does not open a network connection. There is no PayFast port.

## Module

`quotedesk.application.use_cases.tools.create_deposit_link`

```text
CreateDepositLink.execute(context, data) -> DepositLinkResult
```

| Piece | Module |
| --- | --- |
| `CreateDepositLinkInput` | `quotedesk.application.dto.tool_inputs` |
| `DepositLinkResult`, `DepositLinkRecord` | `quotedesk.application.dto.tool_outputs` and `quotedesk.application.dto.changes` |
| `Acceptances` | `quotedesk.application.ports.repositories` |

The quote is loaded with `QuoteRepository.get_by_id`. Acceptance is `Acceptances.has(tenant_id, quote_id, version) -> bool`. The test records one acceptance. This use case does not read a customer sentence and decide that it was acceptance.

`context` of `None` raises `TenantRequired` before the quote is loaded.

## Input

Frozen. `extra` is forbid.

```text
CreateDepositLinkInput
    quote_id: QuoteId
    idempotency_key: str
```

The fixture key is `deposit-1`. A field `unit_price` fails `pydantic.ValidationError`.

## Result

```text
DepositLinkResult
    url: str
```

The sandbox URL for `QD-1042` is:

```text
https://sandbox.payfast.example/deposit/QD-1042
```

The string `payfast.co.za` is absent. The host is `sandbox.payfast.example`.

## Issued and accepted

The quote's current state is `ISSUED`. `has` returns true for that quote and that version. The result is the URL above. One `DepositLinkRecord` is stored with the key, the quote id, and that URL.

## Refusals

No acceptance, an escalated quote, and a site-assessment quote raise the same error. No URL is stored.

| | |
| --- | --- |
| Type | `quotedesk.domain.shared.errors.PolicyViolation` |
| `code` | `policy.violation` |
| Sentence | A deposit link follows an accepted issued quote. |

| Quote | Acceptance | Result |
| --- | --- | --- |
| `ISSUED` | recorded | the sandbox URL |
| `ISSUED` | not recorded | the error above |
| `ESCALATED` | recorded | the error above |
| `SITE_ASSESSMENT_OFFERED` | recorded | the error above |

A recorded acceptance does not rescue an escalated quote or a site-assessment quote. The state is checked first.

## Idempotency

The same key for the same tenant returns the stored URL and does not build a second one. The stored record is one. A key that was refused is not stored, so a second call with that key raises again.
