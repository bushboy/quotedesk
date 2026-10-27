# Clauses

Written 29 October 2026. Tests and `quotedesk/domain/services/select_clauses.py` implement this note and nothing beyond it. The value types live in `quotedesk/domain/policy/clauses.py`.

Clause text is data on the policy. `select_clauses` renders that data. It does not hard-code a rand amount, and it does not invent a sentence when the policy has no template.

## Signature

```text
select_clauses(decision, facts, job_type, policy) -> ClauseSelection
```

`decision` is Wednesday's `Decision`. The function reads `outcome` and `customer_template`. It does not read the clock, the environment, or the network.

`ClauseSelection` carries `conditions: tuple[Condition, ...]` and `customer_template: str`. `customer_template` is the decision's template, copied unchanged. The function does not append a second safety sentence.

Models are frozen and forbid extra fields.

## Condition

| Field | Type |
| --- | --- |
| `clause_id` | `str` |
| `clause_version` | `str` |
| `kind` | `assumption`, `exclusion`, `validity`, `payment`, or `schedule` |
| `text` | rendered `str` |
| `if_not_true` | `str` |
| `variation_item_code` | `str` or `None` |

`clause_version` is copied from the template that produced the condition.

## Policy

`ClausePolicy` has `templates: tuple[ClauseTemplate, ...]`, `settings: Mapping[str, int]`, and `rate_card_codes: tuple[str, ...]`.

`ClauseTemplate` has the same fields as `Condition`, and its `text` may still contain placeholders.

Fixture settings:

| Key | Value |
| --- | --- |
| `deposit_percent` | `30` |
| `validity_days` | `14` |

`ClauseFacts` has `width_m: Decimal | None`, `length_m: Decimal | None`, and `roof_covering: str | None`.

## Placeholders

| Token | Replaced with |
| --- | --- |
| `{width_m}` | The width, one digit after the point. `Decimal("6.0")` renders `6.0`. |
| `{length_m}` | The length, the same way. `Decimal("7.0")` renders `7.0`. |
| `{area_m2}` | `width_m * length_m`. A whole number of square metres renders with no decimal. `42`. |
| `{deposit_percent}` | The setting, as a decimal integer. `30`. |
| `{validity_days}` | The setting, as a decimal integer. `14`. |

A selected template whose token is absent from the settings mapping raises `PolicyViolation` with code `policy.violation` and sentence `A clause placeholder has no setting.` No `ClauseSelection` is returned. The characters `{deposit_percent}` are absent from every returned `text`.

`{width_m}`, `{length_m}`, and `{area_m2}` are filled from facts. The other two tokens are filled from settings.

## Carport, size only

`job_type` is `carport`, `roof_covering` is `None`, `width_m` is `Decimal("6.0")`, and `length_m` is `Decimal("7.0")`. The outcome is not `escalation`.

The condition ids, in this order, are CARPORT-A1, CARPORT-A2, CARPORT-A3, CARPORT-A4, CARPORT-A5, CARPORT-A6, CARPORT-X1, CARPORT-X2, GEN-V1, GEN-V2, GEN-S1.

A1's rendered text contains `6.0 m x 7.0 m`.

| Id | Kind | Template text | Rendered text | `if_not_true` | Variation |
| --- | --- | --- | --- | --- | --- |
| CARPORT-A1 | assumption | `Size {width_m} m x {length_m} m ({area_m2} m²) as stated` | `Size 6.0 m x 7.0 m (42 m²) as stated` | Re-quote at the rate-card price for the actual size | |
| CARPORT-A2 | assumption | `Clearance height up to the rate card's standard height` | same | Height surcharge from the rate card; above its maximum, site measure | `HEIGHT-EXTRA` |
| CARPORT-A3 | assumption | `Freestanding posts fixed to existing paving or concrete` | same | Footing variation from the rate card; soil or slope, site measure | |
| CARPORT-A4 | assumption | `Level site with vehicle access for installation` | same | Site measure | |
| CARPORT-A5 | assumption | `Roof covering is one of the options in the range` | same | Range narrows to the chosen covering | |
| CARPORT-A6 | assumption | `No existing structure to remove` | same | Removal priced separately | |
| CARPORT-X1 | exclusion | `Excludes municipal building plan approval, where required` | same | Customer's responsibility; stated, not handled | |
| CARPORT-X2 | exclusion | `Excludes electrical work and gate automation` | same | Separate quote | |
| GEN-V1 | validity | `This price is valid for {validity_days} days.` | `This price is valid for 14 days.` | After expiry, re-quote at the current rate card | |
| GEN-V2 | validity | `A range or default-based price becomes fixed only after site measure confirms the assumptions` | same | Final price follows the measured assumptions | |
| GEN-S1 | schedule | `No installation date is reserved until the {deposit_percent}% deposit is paid.` | `No installation date is reserved until the 30% deposit is paid.` | See scheduling rules | |

Each template's `clause_version` in this fixture is `"1"`. A selected condition records that version.

A policy that is missing one of these ids raises `PolicyViolation` with code `policy.violation` and sentence `The policy has no clause for that fact.` The function does not fill the gap with its own sentence.

## A stated roof covering

`roof_covering` is a non-empty string. CARPORT-A5 is absent. The other ten remain, in the same order.

## Variation item

CARPORT-A2's `variation_item_code` is `HEIGHT-EXTRA`. The fixture `rate_card_codes` include `HEIGHT-EXTRA`.

A selected template whose `variation_item_code` is absent from `rate_card_codes` raises `PolicyViolation` with code `policy.violation` and sentence `That variation item is not on the rate card.` No selection is returned. A template with `variation_item_code` `None` is not checked.

## Version pin

A condition stores the template's `clause_version` at the time of the call. A later call whose templates say `"2"` returns `"2"` on that new selection only. The first selection is frozen, and its conditions still say `"1"`.

## Escalation

When `decision.outcome` is `escalation`, the result has no conditions. `customer_template` is the decision's template.

WATER-E03's template is Wednesday's sentence, unchanged:

`Please isolate the power near the water, and stay clear of it until we've checked the site.`

No condition is attached. No assumption states a price. The function does not add a safety sentence of its own.

This check comes before the carport selection.

## Water sentences for the printable quote

These are the clauses on the issued 5000 L quote. The fixture copies the rendered text. Placeholders are already filled from the settings above.

| Id | Kind | `clause_version` | Rendered text | `if_not_true` |
| --- | --- | --- | --- | --- |
| WATER-A1 | assumption | `1` | Size is 5 000 L, as stated. | We quote again for the actual size. |
| GEN-V1 | validity | `1` | This price is valid for 14 days. | After expiry, re-quote at the current rate card |
| GEN-S1 | schedule | `1` | No installation date is reserved until the 30% deposit is paid. | See scheduling rules |

None of these sentences contains a rand amount.
