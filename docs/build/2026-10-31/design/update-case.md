# UpdateCase

Written 31 October 2026. Tests and `quotedesk/application/use_cases/tools/update_case.py` implement this note and nothing beyond it.

The proposed shape in the Saturday plan is confirmed. Facts land on the job the tool names. `CaseFile` is not changed. `detect_contradiction` is not changed. This use case calls `add_job` and `record_fact`. It does not reimplement them.

It does not call a model, `decide`, `price`, or `GetQuote`.

## Module

`quotedesk.application.use_cases.tools.update_case`

The class is `UpdateCase`. The method is `execute(context, data) -> UpdateCaseResult`.

| Piece | Module |
| --- | --- |
| `UpdateCaseInput` | `quotedesk.application.dto.tool_inputs` |
| `UpdateCaseResult` | `quotedesk.application.dto.tool_outputs` |
| `JobCatalog` | `quotedesk.application.ports.repositories` |

`CaseFileRepository` gains `save(tenant_id, case)`. `get` stays. `IdGenerator` gains `next_fact_id() -> UUID`. The existing `next_quote_id` stays.

`context` of `None` raises `TenantRequired` before any port is called. A missing case raises `CaseNotFound`. Nothing is saved.

## Input

Frozen. `extra` is forbid. Facts are `FactInput`: `key`, `value`, `source`, `event_id`. `source` is one of the five `CaseFile` already accepts.

```text
UpdateCaseInput
    conversation_id: UUID
    job_id: str
    job_type: str | None = None
    facts: tuple[FactInput, ...]
```

`job_type` is required when the job is not already on the case. A new job with `job_type` omitted raises `ValidationError`, code `job.type_required`, sentence `A new job names its type.` Nothing is saved.

| Payload | Result |
| --- | --- |
| `job_id`, `job_type`, and one fact with key, value, source, and event id | Valid |
| The same on a job that already exists | Valid. `job_type` may be omitted |
| `unit_price` as a field on the input | `pydantic.ValidationError` |
| A fact whose `key` is `unit_price` | `pydantic.ValidationError` |
| A fact whose `key` is `outcome` | `pydantic.ValidationError` |
| A fact whose `key` is `clause_text` | `pydantic.ValidationError` |
| Any other unknown field | `pydantic.ValidationError` |

The failure is `pydantic.ValidationError`. It is not the domain `ValidationError`. No port is called.

## Catalog

`JobCatalog.required(job_type) -> tuple[str, ...]`. The fixture returns `("size_litres", "existing_level_base")` for `replacement`. Any other key is an extra. An extra is stored. It is not one of those two names, so it does not remove a name from the missing list.

The use case does not hard-code the tuple inside `CaseFile`.

## Result

| Field | Type |
| --- | --- |
| `job_id` | `str` |
| `created` | `bool` |
| `current` | the active key-to-value pairs for that job |
| `missing_required` | `tuple[str, ...]` |
| `contradiction_count` | `int` |

`current` omits a key whose facts are contested. `missing_required` is the catalog names that have no active fact. Order is the catalog order.

## New job and existing job

Tenant and conversation are the `GetQuote` fixtures. The case starts empty.

First call: `job_id` `tank`, `job_type` `replacement`, one fact `colour` `blue`, source `customer_text`. The case gains one job. `created` is true. `record_fact` stores `colour`. `current` contains `colour` = `blue`. `missing_required` is `("size_litres", "existing_level_base")`. `colour` is not in that tuple.

Second call: the same `job_id`, no new `job_type`, one fact `size_litres` `5000 L`. `add_job` is not called again. The case still has one job. `created` is false. `current` contains `size_litres` = `5000 L` and `colour` = `blue`. `missing_required` is `("existing_level_base",)`.

## Correction

Two calls, same job `tank`, same key `size_litres`, source `customer_text` both times.

| Call | Value |
| --- | --- |
| First | `2500 L` |
| Second | `5000 L` |

`current` for `size_litres` is `5000 L`. The `2500 L` fact remains on `facts("tank")`. Its `superseded_by` is the second fact's id. The use case takes those ids from `next_fact_id`, one per stored fact. `contradiction_count` is 0. This is the correction `CaseFile` already performs when the source is the same.

## Contradiction

One job `tank`. Two facts, key `position`.

| Source | Value |
| --- | --- |
| `customer_text` | `roof` |
| `photo_extraction` | `ground level` |

`contradiction_count` is 1. Both facts remain. Neither `superseded_by` is set. Both `contested` flags are true. `current` has no `position`. The use case does not pick a winner. `detect_contradiction` does that work inside `record_fact`, and this note does not change it.
