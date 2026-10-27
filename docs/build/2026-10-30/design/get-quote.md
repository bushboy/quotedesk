# GetQuote

Written 30 October 2026. Tests and `quotedesk/application/use_cases/tools/get_quote.py` implement this note and nothing beyond it.

The proposed shape in the Friday plan is confirmed. The low-confidence reading is confirmed: no line total, no range, and no deposit. `price` still returns the visit fee. This note does not change `price`.

One use case turns the current case into one quote version. It calls `decide`, `price`, and `select_clauses`. It does not call `schedule`, a model, or a database.

`quotedesk.domain.quotes.quote` stays as Thursday wrote it. This note does not add a schedule field, a decision, or a policy version to the aggregate. The schedule status and the policy version travel on the result DTO.

## Module

`quotedesk.application.use_cases.tools.get_quote`

The result type is `GetQuoteResult` in `quotedesk.application.dto.tool_outputs`.

Application may import `quotedesk.domain`. It does not import an adapter. Fakes for the case file, the published policy, the quote repository, the audit log, the clock, and the id generator live in the tests.

## Result

| Field | Type |
| --- | --- |
| `quote_id` | `QuoteId` |
| `version` | `int` |
| `state` | `QuoteState` |
| `policy_version` | `PolicyVersionId` |
| `rule_id` | `RuleId` |
| `outcome` | `Outcome` |
| `customer_template` | `str` |
| `lines` | `tuple[QuoteLine, ...]` |
| `clauses` | `tuple[Condition, ...]` |
| `price_type` | `fixed`, `range`, or `none` |
| `total` | `Money` or `None` |
| `range_min` | `Money` or `None` |
| `range_max` | `Money` or `None` |
| `site_visit_fee` | `Money` or `None` |
| `deposit` | `Money` or `None` |
| `schedule_status` | `none` |
| `expiry` | `date` |

`schedule_status` is the string `none` on every result this use case returns. The use case does not import `quotedesk.domain.services.schedule`.

`policy_version` and `rule_id` are copied from the `Decision`. `customer_template` is the decision's template. `deposit` is copied from `PricedQuote`, which is `None`.

`total` is the single line's total when `lines` has one line, and `None` when `lines` is empty.

## Published bundle

`published(tenant_id)` returns one bundle:

| Part | Fixture |
| --- | --- |
| `policy` | `aquasure_policy()` from `tests/unit/domain/water_policy.py` |
| `rate_card` | Thursday's card. `TANK-5000` is `4250.00`, description `5000 L tank`. `site_visit_fee` is `750.00`. `vat_inclusive` is true |
| `clause_policy` | `settings` `deposit_percent` 30 and `validity_days` 14. `templates` may be empty |

A draft the fake also holds is not returned by `published`. Its policy version is `water-policy-v1.1`. Its `TANK-5000` unit price is `4999.00`. The use case has no call that reads it. A quote that used it would total `4999.00`. The tests expect `4250.00` and `water-policy-v1.0`.

## Facts the use case reads

`CaseFile.current` supplies these keys. Values are strings.

| Key | Becomes |
| --- | --- |
| `job` | `JobKind` |
| `size_litres` | `int`. The value is digits, such as `5000` |
| `size_source` | `SizeSource` |
| `existing_level_base` | `true` or `false` |
| `item_codes` | one code, or several separated by a comma |
| `required_fields`, `agreement`, `measurement`, `media_usable`, `rate_card` | `true` or `false` on `ConfidenceChecks` |
| `stand_condition` | `ExtractionFacts.stand_condition`, when the key is present |
| `customer_text` | `CaseFacts.customer_text`, when the key is present |

A missing optional key uses the field's default on `CaseFacts`, `ExtractionFacts`, or `SegmentationFacts`. `SegmentationFacts` is empty for every test in this note. `ClauseFacts` is the default, with width, length, and roof covering all `None`.

`select_clauses` is called with `job_type` equal to the `job` fact. For `replacement` Thursday's function returns an empty condition tuple and the decision's customer template. `GetQuote` stores that tuple. It does not add the water sentences from the printable quote, and it does not change `select_clauses`.

## Clock, id, and expiry

The clock port supplies `at`. The civil date is `civil_date(at, ZoneInfo("Africa/Johannesburg"))`. Expiry is that date plus `validity_days` from the clause settings, as a `date`. The use case does not hard-code 7 November 2026 and does not call `datetime.now`.

The fixture clock is `datetime(2026, 10, 24, 0, 0, tzinfo=timezone.utc)`. The civil date is 24 October 2026. Plus 14 days the expiry is `date(2026, 11, 7)`.

The id port supplies the `QuoteId` when the conversation has no stored quote. The fake's first id is `QD-1042`. The aggregate does not mint one. A second call, when a quote is already stored, does not call the id port again.

`issue` and `revise` receive this same `at`.

## First call

No stored quote:

1. Load the case for the context's tenant and the input's conversation. `None` raises `CaseNotFound`.
2. Load the published bundle.
3. Map the current facts. Call `decide`, then `price`, then `select_clauses`.
4. `Quote.open(quote_id, expiry)`, then `set_lines`, then `set_clauses`, then `issue(outcome, version=1, at=at)`.
5. Stage the quote and one audit event. `commit`.

`CaseNotFound` lives in `quotedesk.application.errors`. `code` is `case.not_found`. The sentence is `That case is not on this tenant.` It is not a `PolicyViolation`. No quote is staged and no audit event is staged.

The audit event records `tenant_id`, action `quote.issued`, `quote_id`, and `version` 1.

Lines are the `PricedLine` values copied into `QuoteLine`. Clauses are `selection.conditions`.

## Second call

A stored quote is revised. The use case does not compare totals and does not skip the version when the total matches.

`revise(outcome, line_items=..., clauses=..., expiry=..., at=at)` appends version 2 and marks version 1 `REVISED`. Version 1's lines stay readable. The audit action is `quote.revised` and the version on the event is 2. One event is recorded for that call.

## Rollback

`record_audit` runs before `commit`. If it raises, the use case calls `rollback` and lets the exception propagate. After `rollback` the quote repository has no new row and the audit log has no new event.

## Cases

The 5000 L replacement facts:

| Key | Value |
| --- | --- |
| `job` | `replacement` |
| `size_litres` | `5000` |
| `size_source` | `customer_stated` |
| `existing_level_base` | `true` |
| `item_codes` | `TANK-5000` |
| five checks | `true` |

| Field on the result | Value |
| --- | --- |
| `rule_id` | `WATER-F01` |
| `outcome` | `fixed_offer` |
| `state` | `ISSUED` |
| `policy_version` | `water-policy-v1.0` |
| `customer_template` | `We can send a fixed quote for this replacement.` |
| lines | one, `TANK-5000`, quantity `1`, unit price and total `4250.00`, description `5000 L tank` |
| `clauses` | empty |
| `price_type` | `fixed` |
| `total` | `4250.00` |
| `deposit` | `None` |
| `schedule_status` | `none` |
| `expiry` | `2026-11-07` |

The fake unit of work has one audit event, action `quote.issued`, for that save. The decision's `policy_version` is the same `water-policy-v1.0`.

Low confidence uses the same job facts with `required_fields` and `media_usable` set to `false`, and the other three checks `true`. No stand fact. The rule is `WATER-L01`. State is `SITE_ASSESSMENT_OFFERED`. `lines` is empty. `total`, `range_min`, `range_max`, and `deposit` are `None`. `site_visit_fee` is `750.00`. `price_type` is `none`.

A leaning stand adds `stand_condition` `leaning` to the 5000 L facts. The rule is `WATER-E02`. State is `ESCALATED`. `customer_template` is `We can't price this while the stand looks unsafe. Please leave the tank unused until we've checked it.` `site_visit_fee` and `deposit` are `None`. `lines` is empty.

The revision starts from the 5000 L facts with `size_litres` `2500`, still `item_codes` `TANK-5000`. That call is `WATER-F01` version 1. The test then supersedes `size_litres` to `5000` through the case file and calls `execute` again. Version 2 is current and `ISSUED`. Version 1 is `REVISED` and its line is still readable. Both totals are `4250.00`.

Tenant A does not receive a case that was stored for tenant B. The repository is called with tenant A's id. The result is `CaseNotFound`. The quote repository gains no row. The audit log gains no event.

The published-policy test is the 5000 L call while the fake also holds the v1.1 draft. The result still shows `water-policy-v1.0` and total `4250.00`.
