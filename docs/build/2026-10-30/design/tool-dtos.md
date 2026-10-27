# Tool inputs and ports

Written 30 October 2026. Tests and `quotedesk/application/dto/` implement this note and nothing beyond it. The ports live in `quotedesk/application/ports/`.

The proposed shape in the Friday plan is confirmed.

Tools take identifiers and structured facts. The agent cannot pass a price, an outcome, a clause, or a discount.

## Modules

| Module | What it holds |
| --- | --- |
| `quotedesk.application.dto.tool_inputs` | `GetQuoteInput`, `FactInput` |
| `quotedesk.application.dto.tenant` | `TenantContext` |
| `quotedesk.application.errors` | `TenantRequired`, `CaseNotFound` |
| `quotedesk.application.ports.repositories` | Case file, published policy, quote, audit |
| `quotedesk.application.ports.runtime` | Clock, id generator, unit of work |

Application may import `quotedesk.domain`. It does not import `quotedesk.adapters` or `quotedesk.infrastructure`. Ports are protocols. Fakes live in the tests. No port imports an adapter.

Input models are frozen Pydantic models with extra fields forbidden.

## GetQuote input

`GetQuoteInput` has one field: `conversation_id: UUID`.

| Payload | Result |
| --- | --- |
| `conversation_id` only | Valid |
| No fields | `pydantic.ValidationError` |
| `unit_price` as well | `pydantic.ValidationError` |
| `outcome` as well | `pydantic.ValidationError` |
| `clause_text` as well | `pydantic.ValidationError` |
| `discount_percent` as well | `pydantic.ValidationError` |
| Any other unknown field | `pydantic.ValidationError` |

The failure is `pydantic.ValidationError`. It is not the domain `ValidationError`.

## Fact input

`FactInput` fields: `key: str`, `value: str`, `source: str`, `event_id: UUID`. All four are required.

`source` is one of `customer_text`, `voice_transcript`, `photo_extraction`, `video_extraction`, `owner`.

| Payload | Result |
| --- | --- |
| All four fields, with a legal source | Valid |
| No fields | `pydantic.ValidationError` |
| `source` omitted | `pydantic.ValidationError` |
| An unknown field | `pydantic.ValidationError` |

This model is the shape a later `UpdateCase` will take. Friday does not implement that use case.

## Tenant

```text
TenantContext
    tenant_id: UUID
```

```text
execute(context: TenantContext | None, data: GetQuoteInput) -> GetQuoteResult
```

`context` of `None` raises `TenantRequired` before any port is called.

| Attribute | Value |
| --- | --- |
| Type | `TenantRequired` |
| Module | `quotedesk.application.errors` |
| `code` | `tenant.required` |
| Sentence | `A use case needs a tenant.` |

`TenantRequired` subclasses `Exception`. It does not subclass `PolicyViolation` or `DomainError`.

A call with a context records that context's `tenant_id` on the fake case-file repository. The test reads the recorded id and compares it with the context.

## Ports

| Port | Method | Returns |
| --- | --- | --- |
| `CaseFileRepository` | `get(tenant_id, conversation_id)` | `CaseFile` or `None` |
| `PolicyRepository` | `published(tenant_id)` | the published bundle, or `None` |
| `QuoteRepository` | `get(tenant_id, conversation_id)` | `Quote` or `None` |
| `AuditLog` | `record(event)` | `None` |
| `Clock` | `now()` | an aware `datetime` |
| `IdGenerator` | `next_quote_id()` | `QuoteId` |
| `UnitOfWork` | `save_quote`, `record_audit`, `commit`, `rollback` | the quote and the audit event commit together, or not at all |

`published` returns the published bundle only. It has no method that returns a draft.

The unit of work owns the quote repository and the audit log for one `execute`. `save_quote` and `record_audit` stage the write. `commit` keeps both. `rollback` drops both. A caller that has not committed sees no new quote row and no new audit event.
