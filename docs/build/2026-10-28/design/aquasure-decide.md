# AquaSure decide

Written 28 October 2026. Tests, `quotedesk/domain/policy/rules.py`, `quotedesk/domain/case/facts.py`, and `quotedesk/domain/services/decide.py` implement this note and nothing beyond it.

D1, D2, and D10 are confirmed as written in the week plan. They are not overturned. FrameWorks is not implemented today.

## Signature

```text
decide(case_facts, extraction_facts, segmentation_facts, policy) -> Decision
```

Modules:

| Piece | Module |
| --- | --- |
| `decide` | `quotedesk.domain.services.decide` |
| `Decision`, `Outcome`, `Policy`, `PolicyRule` | `quotedesk.domain.policy.rules` |
| `CaseFacts`, `ExtractionFacts`, `SegmentationFacts`, `JobKind` | `quotedesk.domain.case.facts` |

The fixture policy is Python in `tests/unit/domain/water_policy.py`. Nothing reads `seeds/aquasure.yaml`. That file waits until Saturday.

Predicates are Python functions named by rule id. The policy does not carry an expression language. `decide` orders rules by `priority` ascending, then by the order they appear on the policy. Escalation rules have priority 0 and run first. First match wins. One `Decision` is returned.

If the policy matches no rule, `decide` raises `PolicyViolation` with code `policy.violation` and sentence `The policy matched no rule.` The AquaSure fixture includes WATER-L01 and WATER-L02, so the tests do not hit that raise.

`segmentation_facts` is part of the signature. Wednesday's AquaSure predicates do not read masks. Stand condition, elevation, wiring, and flooding come from `extraction_facts`. Injection text in a photo comes from `extraction_facts.image_text`.

Confidence is the `checks` value on the case. `decide` calls `derive_confidence`. It does not recompute the five booleans and it does not read a model self-score.

## Decision

Frozen Pydantic model. Extra fields are forbidden. There is no amount, price, or money field.

| Field | Type |
| --- | --- |
| `outcome` | `Outcome` |
| `rule_id` | `RuleId` |
| `policy_version` | `PolicyVersionId` |
| `reasons` | non-empty `tuple[str, ...]` |
| `confidence_band` | `ConfidenceBand` |
| `customer_template` | `str` |

`customer_template` and the single reason are copied from the matched rule. No model field is concatenated, and there is no second advice field.

Outcomes: `escalation`, `site_assessment`, `fixed_offer`, `indicative_range`.

## Policy fixture

| Field | Value |
| --- | --- |
| `version` | `water-policy-v1.0` |
| `sam_score_threshold` | `Decimal("0.80")` |
| `rate_card_codes` | `TANK-5000`, `PUMP-STD` |

Rule order:

| Rule | Priority | Outcome | Customer template | Reason |
| --- | --- | --- | --- | --- |
| WATER-E01 | 0 | escalation | I can't use that message to change the quote. Please phone the business and we'll take it from there. | Flagged as an injection for the owner: the message instructs the assistant or claims an approval. |
| WATER-E02 | 0 | escalation | We can't price this while the stand looks unsafe. Please leave the tank unused until we've checked it. | The stand is unsafe, or an elevated structure is damaged. |
| WATER-E03 | 0 | escalation | Please isolate the power near the water, and stay clear of it until we've checked the site. | Exposed wiring or active flooding was recorded. |
| WATER-S01 | 1 | site assessment | A borehole needs a site visit. If you go ahead, the visit fee is credited against the work. | The job is a borehole. |
| WATER-S02 | 1 | site assessment | This install needs a site visit before we can give you a price. | The ground, the stand, or the pipe run needs a visit. |
| WATER-F01 | 1 | fixed offer | We can send a fixed quote for this replacement. | Like-for-like replacement on a level base with a stated size. |
| WATER-R01 | 1 | indicative range | We can send a price range for a new tank and pump. It assumes the base still has to be confirmed. | New tank and pump with the base unconfirmed. |
| WATER-L01 | 1 | site assessment | We need a clearer picture before we can price this. A site visit is the sure way to do that. | Confidence is low and no earlier rule matched. |
| WATER-L02 | 1 | site assessment | We don't have a standard price for this job. A site visit is the next step. | No priced rule matches at this confidence. |

WATER-E01's customer template does not say that an injection was detected. The reason does, because that line is for the owner. WATER-E03's template tells the customer to isolate power. No template contains a rand amount.

## Facts the predicates read

`CaseFacts`: `checks`, `job` (`replacement`, `new_system`, `borehole`, `unknown`), `customer_text`, `voice_transcript`, `size_litres`, `size_source`, `existing_level_base`, `base_unconfirmed`, `new_tank_and_pump`, `sloped_ground`, `pipe_run_unknown`, `item_codes`.

`ExtractionFacts`: `stand_condition` (`sound`, `leaning`, `cracked`, `sagging`, or absent), `elevated`, `structure_damage`, `exposed_wiring`, `active_flooding`, `image_text`.

`SegmentationFacts`: `masks`, `sam_error`. Accepted, not read by these predicates.

## Predicates

Texts for WATER-E01 are `customer_text`, `voice_transcript`, and `image_text`. A flag from `classify_injection_claims` on any of them matches. `""` and `None` do not.

| Rule | Matches when |
| --- | --- |
| WATER-E01 | Any of those three texts has `instruction` or `claimed_approval` |
| WATER-E02 | `stand_condition` is `leaning`, `cracked`, or `sagging`; or `elevated` and `structure_damage` are both true; or `customer_text` or `voice_transcript` contains `leaning`, `cracked`, or `sagging` |
| WATER-E03 | `exposed_wiring` or `active_flooding`. Customer text is not read. "It flooded last year" does not set `active_flooding` |
| WATER-S01 | `job` is `borehole`. Confidence is not consulted |
| WATER-S02 | `elevated` is true and `structure_damage` is false; or `sloped_ground`; or `pipe_run_unknown`. A level existing base with none of those does not match |
| WATER-F01 | Confidence is `high`, `job` is `replacement`, `size_litres` is present, `size_source` is `customer_stated`, `existing_level_base` is true, and `item_codes` is non-empty and `rate_card_match` is true. A missing size, a `photo_inferred` size, and a `reference_object` size do not match. Medium confidence does not match |
| WATER-R01 | Confidence is `medium` or `high`, `new_tank_and_pump` is true, and `base_unconfirmed` is true. Low confidence does not match. An unknown pipe run is WATER-S02 because that rule is earlier |
| WATER-L01 | Confidence is `low` |
| WATER-L02 | Confidence is `medium` or `high` |

WATER-L01 and WATER-L02 are last, so they mean "no earlier rule matched". D2: unmatched low confidence is WATER-L01. Unmatched medium or high is WATER-L02. Both are site assessment and carry no price. WATER-L02 is not in the spec table. It exists because of D2.

A sound elevated stand is WATER-S02, not WATER-E02. `elevated` and `structure_damage` together are WATER-E02.

The first-match fixture sets both WATER-F01's facts and WATER-R01's facts on one case: a stated-size replacement on a level base, on the rate card, at high confidence, and also `new_tank_and_pump` with `base_unconfirmed`. That combination is contradictory on purpose. The full policy returns WATER-F01 only. The same case with WATER-F01 removed returns WATER-R01.

A like-for-like case at medium confidence, a like-for-like case with no stated size, and an unknown job at medium confidence are WATER-L02. An ordinary replacement with two failed checks and no hazard is WATER-L01. WATER-E02 still matches when those two checks have already made the band `low`.
