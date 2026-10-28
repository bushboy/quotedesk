# FrameWorks decide

Written 1 November 2026. Tests, `tests/unit/domain/fabricator_policy.py`, and the new predicates in `quotedesk/domain/services/decide.py` implement this note and nothing beyond it.

The same `decide` prices a fabricator from a second policy. Water predicates stay as Wednesday left them. `tests/unit/domain/test_aquasure_decide.py` is not edited. A water F01 case still returns WATER-F01.

`Outcome` stays `fixed_offer`, `indicative_range`, `site_assessment`, `escalation`. `Decision` still has no amount and no schedule status. `GetQuote` still does not call `schedule`. FAB-B01 does not set one.

## Signature

Unchanged:

```text
decide(case_facts, extraction_facts, segmentation_facts, policy) -> Decision
```

An unknown rule id is still skipped. A policy that matches nothing still raises `PolicyViolation`, code `policy.violation`, sentence `The policy matched no rule.`

Predicates stay Python functions named by rule id. Escalation rules have priority 0. The rest have priority 1. First match wins: priority ascending, then the order on the policy.

`_PREDICATES` gains the ten FAB ids. WATER-E01's function is also registered as FAB-E01. The water function's body is not edited.

## Facts

Water fields stay. New fields have defaults, so a water `CaseFacts(...)` and a water `ExtractionFacts(...)` still construct. Water predicates do not read the new fields.

`CaseFacts` gains:

| Field | Default | Used by |
| --- | --- | --- |
| `width_m` | `None` | FAB-R01, FAB-F01 |
| `length_m` | `None` | FAB-R01, FAB-F01 |
| `finish` | `None` | `None` means the finish is not chosen |
| `opening` | `None` | `existing`, `new`, or `widened` |
| `above_ground_floor` | `False` | FAB-S02 |
| `multi_unit` | `False` | FAB-S02 |
| `standard_band` | `False` | FAB-F01 |
| `budget` | `None` | A `Decimal` amount, or absent |
| `job_type` | `None` | `carport`, `window`, `door`, or `shutter` |

`JobKind` does not gain a value.

`ExtractionFacts` gains:

| Field | Default |
| --- | --- |
| `lintel_cracked` | `False` |
| `glass_broken` | `False` |
| `hairline_mark` | `False` |
| `possible_asbestos` | `False` |

`size_source` is the field Wednesday already has. Fabricator dimensions use `width_m` and `length_m`. They do not use `size_litres`.

`Policy` gains `range_minimum: Decimal | None = None`. Water policies leave it `None`. The fabricator fixture sets `Decimal("850.00")`.

## Fixture policy

`tests/unit/domain/fabricator_policy.py`. The function is `fabricator_policy()`.

| Field | Value |
| --- | --- |
| `version` | `fab-policy-v1.0` |
| `sam_score_threshold` | `Decimal("0.80")` |
| `rate_card_codes` | `SHEET-ECO`, `SHEET-POLY` |
| `range_minimum` | `Decimal("850.00")` |

`SHEET-ECO` is the nearest affordable option. It is `rate_card_codes[0]`.

| Rule | Priority | Outcome | Customer template | Reason |
| --- | --- | --- | --- | --- |
| FAB-E01 | 0 | escalation | I can't use that message to change the quote. Please phone the business and we'll take it from there. | Flagged as an injection for the owner: the message instructs the assistant or claims an approval. |
| FAB-E02 | 0 | escalation | We can't price this while the opening looks unsafe. Please leave that glass and the lintel alone until we've checked them. | The lintel is cracked, or glass is broken in place. |
| FAB-E03 | 0 | escalation | We can't price this until someone has checked the old sheeting. Please don't cut or scrape it. | Old carport sheeting may contain asbestos. |
| FAB-S01 | 1 | site assessment | A new or widened opening needs a site measure. If you go ahead, the visit fee is credited against the work. | The opening is new or widened. |
| FAB-S02 | 1 | site assessment | This one needs a site measure before we can give you a price. | The job is above the ground floor, or it is more than one opening. |
| FAB-F01 | 1 | fixed offer | We can send a fixed quote for this replacement. | Replacement in the existing opening, standard size and finish. |
| FAB-R01 | 1 | indicative range | We can send a price range for this carport. It depends on the roof covering. | 6 m by 7 m with the finish not chosen. |
| FAB-B01 | 1 | indicative range | We can send a price range, and the nearest option we fit to a smaller budget. | The nearest affordable option is SHEET-ECO. |
| FAB-L01 | 1 | site assessment | We need a tape measure in the frame before we can price this. A site measure is the sure way. | Confidence is low and no earlier rule matched. |
| FAB-L02 | 1 | site assessment | We don't have a standard price for this job. A site measure is the next step. | No priced rule matches at this confidence. |

No template contains a rand amount. FAB-E01's template does not say that an injection was detected. The reason does, because that line is for the owner.

## Predicates

Texts for FAB-E01 are `customer_text`, `voice_transcript`, and `image_text`. A flag from `classify_injection_claims` on any of them matches. `""` and `None` do not. The phrases are the ones Wednesday already listed. `the owner said` is a claimed approval.

Confidence is `derive_confidence(case.checks)`. These predicates do not recompute the five booleans.

| Rule | Matches when |
| --- | --- |
| FAB-E01 | Any of those three texts has `instruction` or `claimed_approval` |
| FAB-E02 | `lintel_cracked` or `glass_broken`. `hairline_mark` alone does not match |
| FAB-E03 | `possible_asbestos` is true. A carport with that flag false does not match, including `job_type` `carport` with `opening` `existing` |
| FAB-S01 | `opening` is `new` or `widened`. `existing` does not match. `None` does not match |
| FAB-S02 | `above_ground_floor` or `multi_unit`. Both false does not match |
| FAB-F01 | Confidence is `high`, `opening` is `existing`, `width_m` and `length_m` are present, `size_source` is `customer_stated` or `reference_object`, `standard_band` is true, and `finish` is a non-empty string. Medium confidence does not match. `photo_inferred` does not match |
| FAB-R01 | `width_m` is `Decimal("6.0")`, `length_m` is `Decimal("7.0")`, `finish` is `None`, and confidence is `medium` or `high`. Low confidence does not match |
| FAB-B01 | `budget` is present, `policy.range_minimum` is present, and `budget` is below that minimum. The outcome is `indicative_range`. The reason is the rule's reason, which contains `SHEET-ECO` |
| FAB-L01 | Confidence is `low` |
| FAB-L02 | Confidence is `medium` or `high` |

FAB-L01 and FAB-L02 are last on the fixture, so they mean no earlier rule matched.

A case that satisfies FAB-F01 and also contains `the owner said` returns FAB-E01 only. Priority 0 runs first.

A 6 m by 7 m case with `finish` `None` does not match FAB-F01, at medium or at high, because the finish is absent. It matches FAB-R01. The same dimensions at low confidence match FAB-L01, not FAB-R01.

FAB-B01's decision has no amount attribute populated. It has no schedule status. The budget alone is not a site visit.

## What this note does not change

`classify_injection_claims`, `derive_confidence`, `price`, `select_clauses`, and the WATER predicate bodies stay. `Decision` does not gain a field.
