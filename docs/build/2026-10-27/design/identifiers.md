# Identifiers

Written 27 October 2026. Tests and `quotedesk/domain/shared/ids.py` implement this note and nothing beyond it.

`QuoteId`, `PolicyVersionId`, and `RuleId` are frozen Pydantic value objects. Each wraps one string field, `value`. Construction is `QuoteId("QD-0001")` or `QuoteId(value="QD-0001")`, and the same for the other two types.

A value that fails its pattern raises `quotedesk.domain.shared.errors.ValidationError`. It does not raise `ValueError` or Pydantic's `ValidationError`.

The module imports only the standard library and Pydantic.

## QuoteId

Pattern: `^QD-\d{4,8}$`

| Accepted | Rejected |
| --- | --- |
| `QD-0001` | `QD-123` (3 digits) |
| `QD-12345678` | `QD-123456789` (9 digits) |
|  | `qd-0001` |
|  | `QD-` |
|  | `QD-0001 ` (trailing space) |

Code: `quote_id.invalid`

Sentence: `A quote id looks like QD-0001.`

## PolicyVersionId

Pattern: `^[a-z][a-z0-9]*(?:-[a-z0-9]+)*-policy-v\d+\.\d+$`

The tenant slug is lowercase. The marker is `-policy-v`. The version has a major and a minor number.

| Accepted | Rejected |
| --- | --- |
| `water-policy-v1.2` | `water-policy-1.2` |
| `fab-policy-v1.1` | `v1.2` |
|  | `""` |
|  | `Water-policy-v1.2` |

Code: `policy_version_id.invalid`

Sentence: `A policy version id looks like water-policy-v1.2.`

## RuleId

Pattern: `^(WATER|FAB)-[A-Z]\d{2}$`

The prefixes for this build are `WATER` and `FAB`. The rule code is one uppercase letter and two digits, as in `F01` and `L02`.

| Accepted | Rejected |
| --- | --- |
| `WATER-F01` | `F01` |
| `FAB-L02` | `water-f01` |
| `WATER-E03` | `WATER-F1` |
| `FAB-B01` | `WATER-F001` |

Code: `rule_id.invalid`

Sentence: `A rule id looks like WATER-F01.`
