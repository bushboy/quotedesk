# Case file

Written 30 October 2026. Tests and `quotedesk/domain/case/case_file.py` implement this note and nothing beyond it. `detect_contradiction` lives in `quotedesk/domain/case/contradictions.py`.

D4 is confirmed as written in the week plan. It is not overturned. The proposed shape in the Friday plan is confirmed.

One current value per key, and the history kept beside it. A correction supersedes. A disagreement is stored and not resolved.

`quotedesk.domain.case.facts.CaseFacts` stays the input `decide` already uses. This note does not change that module.

## Module

`quotedesk.domain.case.case_file`

Imports allowed: the standard library, Pydantic, and `quotedesk.domain`. The type does not read the clock, the environment, or the network. It does not mint an id. The caller passes `conversation_id`, `tenant_id`, every `job_id`, every `fact_id`, and every `event_id`.

Value types are frozen Pydantic models with extra fields forbidden. Methods return a new `CaseFile` or raise. The receiver is unchanged.

## Open

```text
CaseFile.open(conversation_id: UUID, tenant_id: UUID) -> CaseFile
```

No jobs, no facts, no contradictions.

```text
add_job(job_id: str, job_type: str | None) -> CaseFile
```

The new job has status `gathering`. Status values are `gathering`, `quoted`, `held`, and `closed`.

## Fact

| Field | Type |
| --- | --- |
| `fact_id` | `UUID` |
| `job_id` | `str` |
| `key` | `str` |
| `value` | `str` |
| `source` | one of the five sources below |
| `event_id` | `UUID` |
| `superseded_by` | `UUID` or `None` |
| `contested` | `bool` |

Sources: `customer_text`, `voice_transcript`, `photo_extraction`, `video_extraction`, `owner`.

A fact is active when `superseded_by` is `None` and `contested` is false. A key on a job has at most one active fact.

```text
record_fact(job_id, fact_id, key, value, source, event_id) -> CaseFile
```

`event_id` may be passed as `None`. `None` raises `ValidationError` with code `fact.event_required` and sentence `A fact names the event it came from.` Nothing is stored.

Each of the five sources is accepted and stored on the fact.

## Correction

When the key already has an active fact, `record_fact` asks `detect_contradiction`. If that returns `None`, the old fact's `superseded_by` becomes the new `fact_id`. The new fact is active. `current(job_id, key)` returns the new value. `facts(job_id)` still yields the old fact.

The correction the test writes:

| Order | `fact_id` | Value | Source |
| --- | --- | --- | --- |
| First | the caller's first UUID | `2500 L` | `customer_text` |
| Second | the caller's second UUID | `5000 L` | `customer_text` |

`current` returns `2500 L` after the first write and `5000 L` after the second. The first fact remains, with `superseded_by` set to the second `fact_id`.

## One current value

`CaseFile` can be constructed with `jobs` already filled. That is how the invariant is tested. `open` still starts empty. A case whose facts include two active facts for the same job and key raises `PolicyViolation` with code `policy.violation` and sentence `A fact key has one current value.`

`record_fact` does not do that. The legal second write is the correction above, which supersedes, or the contradiction below, which contests both.

## Contradiction

```text
detect_contradiction(existing: CaseFact, new: CaseFact) -> Contradiction | None
```

`Contradiction` has `job_id`, `key`, `fact_id`, and `other_fact_id`. `fact_id` is the existing fact. `other_fact_id` is the new one.

| Existing and new | Result |
| --- | --- |
| Same key, different source, different value | One `Contradiction` |
| Same key, same value, sources differ | `None` |
| Same key, same source, different value | `None`. This is a correction |

The disagreeing pair the test writes, on job `tank` and key `position`:

| Source | Value |
| --- | --- |
| `customer_text` | `roof` |
| `photo_extraction` | `ground level` |

`record_fact` stores both. Neither `superseded_by` is set. Both `contested` flags are true. The case file's contradictions has length 1. Neither fact is removed from `facts(job_id)`. D4. The function does not pick a winner and does not average the values.

The agreeing pair uses value `5000 L` on both facts, one `customer_text` and one `photo_extraction`. `detect_contradiction` returns `None`. No contradiction is stored. The second fact supersedes the first. `current` returns `5000 L`.

## Jobs

A tank job and a pump job each keep their own facts. `current("tank", key)` does not see a fact whose `job_id` is `pump`.

```text
start_over(job_id) -> CaseFile
```

That job's status becomes `closed`. Its facts stay readable through `facts(job_id)`. The job stays on the case. Nothing is deleted.

## Reader

```text
current(job_id, key) -> str
facts(job_id) -> tuple[CaseFact, ...]
```

`current` returns the active fact's value. A key whose facts are contested, and which has no active fact, raises `PolicyViolation` with code `policy.violation` and sentence `That fact is contradicted.` `facts` returns every fact on that job, including superseded and contested ones, in the order they were recorded.
