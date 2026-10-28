# Policy publish

Written 1 November 2026. Tests, `quotedesk/domain/services/validate_policy.py`, `quotedesk/application/use_cases/editor/publish_policy.py`, and `quotedesk/application/use_cases/editor/rollback_policy.py` implement this note and nothing beyond it.

A draft is editable. Publish is a new version. An issued quote keeps the clauses it was given. `GetQuote` still reads the published bundle only. `test_get_quote_uses_the_published_policy_only` stays as Friday wrote it and is not weakened.

`price`, `select_clauses`, and the water predicates stay. This note does not add a clause word processor.

## validate_policy

```text
validate_policy(draft) -> tuple[PolicyError, ...]
```

Module: `quotedesk.domain.services.validate_policy`. The draft types live in `quotedesk.domain.policy.draft`.

The function is pure. It does not call a model, read the clock, publish, or import an adapter. An empty tuple means the draft is valid. A problem is a `PolicyError`. The function does not raise for a bad draft.

```text
PolicyError
    code: str
    sentence: str
    clause_id: str | None = None

PolicyDraft
    deposit_percent: int
    discount_cap_percent: int
    validity_days: int
    vat_inclusive: bool
    rate_rows: tuple[DraftRateRow, ...]
    clauses: tuple[DraftClause, ...]
    required_facts: tuple[RequiredFact, ...]
    rules: tuple[DraftRule, ...]
    settings: tuple[str, ...]

DraftRateRow
    item_code: str
    unit_price: Decimal
    vat_inclusive: bool

DraftClause
    clause_id: str
    text: str
    variation_item_code: str | None = None

RequiredFact
    key: str
    question: str | None = None

DraftRule
    rule_id: str
    enabled: bool
```

`unit_price` is a `Decimal` so that `0` and a negative can be checked. `Money` is not the field, because `Money` already refuses a negative.

`settings` is the set of placeholder names the tenant has values for. The fixture set is `deposit_percent` and `validity_days`.

### Errors

Each row is one error. The sentence is fixed.

| Case | Code | Sentence | `clause_id` |
| --- | --- | --- | --- |
| `variation_item_code` not in the rate-row item codes | `policy.unknown_variation` | Clause {clause_id} names a rate-card item that is not on the card. | That clause id |
| `question` is `None` | `policy.missing_question` | A required fact needs a question. | `None` |
| `question` is `""` or whitespace | `policy.missing_question` | A required fact needs a question. | `None` |
| `unit_price` is `0` or negative | `policy.price` | A rate-card price must be greater than zero. | `None` |
| `deposit_percent` below `0` or above `99` | `policy.deposit_percent` | A deposit percent is a whole number from 0 to 99. | `None` |
| `discount_cap_percent` below `0` or above `100` | `policy.discount_cap` | A discount cap is a percent from 0 to 100. | `None` |
| `validity_days` below `1` | `policy.validity_days` | Validity is at least one day. | `None` |
| A `{token}` in clause text whose name is not in `settings` | `policy.placeholder` | A clause placeholder has no setting. | That clause id |
| Two rate rows disagree on `vat_inclusive` | `policy.vat_basis` | A rate card uses one VAT basis. | `None` |
| WATER-E01, WATER-E02, WATER-E03, FAB-E01, FAB-E02, or FAB-E03 has `enabled` false | `policy.locked_rule` | A safety rule cannot be turned off. | `None` |

`deposit_percent` `0` and `99` are valid. `discount_cap_percent` `0` and `100` are valid. A positive price is valid. Every rate row on the draft's `vat_inclusive` value is valid, whether that value is true or false. A clause whose tokens are all in `settings` is valid. `variation_item_code` `None` is not checked. A locked rule with `enabled` true is valid.

`{deposit_percent}` and `{validity_days}` pass when those names are in `settings`. `{unknown_token}` fails. The characters `{` and `}` mark a token. The name is the text between one pair.

## Publish and rollback

| Use case | Module |
| --- | --- |
| `PublishPolicy` | `quotedesk.application.use_cases.editor.publish_policy` |
| `RollbackPolicy` | `quotedesk.application.use_cases.editor.rollback_policy` |

```text
PublishPolicy.execute(context, data) -> PolicyVersionId
RollbackPolicy.execute(context, data) -> PolicyVersionId
```

```text
PublishInput
    reason: str
    idempotency_key: str

RollbackInput
    source_version: PolicyVersionId
    reason: str
    idempotency_key: str
```

Frozen. `extra` is forbid. Neither input carries a price.

The published id matches `[a-z][a-z0-9]*(?:-[a-z0-9]+)*-policy-v{major}.{minor}`. Publish and rollback increment `minor` by one integer. `water-policy-v1.0` becomes `water-policy-v1.1`. `water-policy-v1.1` becomes `water-policy-v1.2`. The major stays `1`.

A blank reason, or a reason of whitespace, raises `ValidationError`, code `publish.reason`, sentence `A publish needs a reason.` No version is stored. This applies to both use cases.

`PublishPolicy` loads the draft and calls `validate_policy`. Any error raises `PolicyViolation`, code `policy.violation`, sentence the first error's sentence. The published version is unchanged. A missing variation item and a locked rule both take this path. Disabling WATER-E01 leaves WATER-E01 on the published policy.

The same idempotency key returns the first `PolicyVersionId` and does not create a second version. The fixture publish key is `publish-1`. The fixture rollback key is `rollback-1`.

A missing tenant raises `TenantRequired`.

### What publish writes

The new published bundle is the draft's rules, rate rows, and settings, under the new version id. The previous published bundle stays readable by its old id. Nothing is deleted.

The fixture deposit change is `deposit_percent` from `30` to `40`. The clause is Thursday's GEN-S1:

`No installation date is reserved until the {deposit_percent}% deposit is paid.`

Rendered at 30: `No installation date is reserved until the 30% deposit is paid.`

Rendered at 40: `No installation date is reserved until the 40% deposit is paid.`

A quote issued under `water-policy-v1.0` keeps the conditions already stored on that version, including the 30 percent sentence. Publish does not load the quote and does not rewrite a clause. A later `GetQuote` uses `water-policy-v1.1` and the 40 percent sentence.

Changing the deposit on a draft, without publishing, leaves `GetQuote` on the published percent. The draft is not the bundle `published()` returns.

### Rollback

Rollback of `water-policy-v1.0` while `water-policy-v1.1` is published creates `water-policy-v1.2`. v1.2's rules, rate rows, and settings are v1.0's content. v1.0 and v1.1 remain readable. v1.2 is the bundle `published()` returns. A blank reason raises before v1.2 exists.

## Seed

`seeds/frameworks.yaml` uses the same keys as `seeds/aquasure.yaml`. The loader is `quotedesk.adapters.outbound.parsers.aquasure.load_policy`. There is no second parser. `decide` is not changed to make the comparison pass.

`tests/adapters/test_frameworks_seed.py` loads that file and compares it with `fabricator_policy()` from [frameworks-decide.md](frameworks-decide.md). Version, `sam_score_threshold`, `rate_card_codes`, rule ids, outcomes, and customer templates match. `range_minimum` matches `Decimal("850.00")`.
