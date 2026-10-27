# Confidence

Written 28 October 2026. Tests and `quotedesk/domain/services/confidence.py` implement this note and nothing beyond it.

D3 and D4 are confirmed as written in the week plan. They are not overturned.

The band is derived from five checks. A model's self-score is not an input. `derive_confidence` takes the five booleans and returns the band. Five named functions turn facts into those booleans. Tests for SAM, blank fields, photo-only size, disagreement, and unusable media call those functions. They do not hide the facts inside the band function.

## Module

`quotedesk.domain.services.confidence`

Imports allowed: the standard library and Pydantic. The module does not read the clock, the environment, or the network. It does not import another QuoteDesk layer.

Value types in this module are frozen Pydantic models with extra fields forbidden.

## Band

`derive_confidence(checks: ConfidenceChecks) -> ConfidenceBand`

| Field on `ConfidenceChecks` | Check |
| --- | --- |
| `required_fields` | Required fields complete |
| `agreement` | Cross-model agreement |
| `measurement` | Measurement source |
| `media_usable` | Media usable |
| `rate_card` | Rate-card match |

`ConfidenceBand` values are `high`, `medium`, and `low`.

| Checks | Band |
| --- | --- |
| All five true | `high` |
| Exactly one false, and it is not `rate_card` | `medium` |
| `rate_card` false, whatever the other four are | `low` |
| Two or more false | `low` |
| All five false | `low` |

All five failing returns `low`. It does not raise.

## Required fields

`required_fields_complete(values, required) -> bool`

`values` is a mapping. `required` is the keys the job needs. A key that is not listed is optional.

| Fact | Result |
| --- | --- |
| A required key is missing | incomplete |
| A required value is `None` | incomplete |
| A required value is `""` or a string of only spaces, including `" "` | incomplete |
| A required value is any other object, including `False` and `0` | present |
| An optional key is missing, and every required key is present | complete |

A string is blank when `strip()` is empty. The check does not treat a value as missing because it is falsy.

## Cross-model agreement

`cross_model_agreement(*, has_image, has_video, spark_objects, sam_error, masks, threshold) -> bool`

This reads recorded facts. It does not call SAM. `masks` are `RecordedMask` values with `label: str` and `score: Decimal`. `threshold` is a `Decimal`. The AquaSure fixture uses `Decimal("0.80")`. A mask counts when `score >= threshold`. A score under the threshold does not count. Labels match exactly, case-sensitive.

| Facts | Result |
| --- | --- |
| `has_image` is false and `has_video` is false | pass, including when `spark_objects` is empty. SAM flags are not read |
| Image or video, and `sam_error` is true | fail. This is the recorded "SAM raises" case |
| Image or video, `sam_error` is false, and `masks` is empty | fail. This is the no-mask case |
| Image or video, and a Spark object has no counting mask with the same label | fail |
| Image or video, no error, at least one mask, and every Spark object has a counting mask | pass |

D3. No image and no video passes. Media plus a recorded SAM error, no mask, or a miss of a Spark object at the policy threshold fails.

## Measurement source

`measurement_acceptable(sizes) -> bool`

Each `SizeFact` has `litres: int` and `source`. Sources are `photo_inferred`, `customer_stated`, and `reference_object`.

| Facts | Result |
| --- | --- |
| No size | pass. Presence is a different check |
| Only `photo_inferred` | fail |
| Only `customer_stated` | pass |
| Only `reference_object` | pass |
| Two facts with different `litres` | fail. The litres are not averaged |
| `customer_stated` 5000 L and `photo_inferred` 2500 L | fail |

D4. A photo-inferred size fails. A customer-stated size or a reference-object measurement passes. Stated and inferred sizes that disagree fail.

## Media usability

`media_is_usable(media: MediaUsability) -> bool`

| Field | Meaning |
| --- | --- |
| `has_media` | Some image, video, or audio was offered |
| `blur` | Spark flagged blur |
| `darkness` | Spark flagged darkness |
| `unintelligible_audio` | Voice Transcribe flagged unintelligible audio |
| `wrong_subject` | Spark flagged the wrong subject |

| Facts | Result |
| --- | --- |
| `has_media` false | pass. Defect flags are not read |
| `has_media` true and every defect flag false | pass. A clean photo |
| `has_media` true and any one defect flag true | fail |

Blur, darkness, unintelligible audio, and the wrong subject each fail the check on their own.

## Rate-card match

`rate_card_match(item_codes, rate_card_codes) -> bool`

Every proposed item code is in the rate card. An unknown code fails. An empty proposal passes, because there is no code to miss. `derive_confidence` still receives the boolean this function returns. A false rate-card check is `low` even when the other four checks are true.
