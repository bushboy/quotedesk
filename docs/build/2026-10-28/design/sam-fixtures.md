# Recorded SAM fixtures

Written 28 October 2026. Tests and `quotedesk/adapters/outbound/models/baseten/sam_parser.py` implement this note and nothing beyond it.

The parser reads a recorded JSON object. It does not call Baseten, and it does not open a network connection. Wednesday's domain tests do not import this module. They build agreement facts themselves.

## Module

`quotedesk.adapters.outbound.models.baseten.sam_parser`

`parse_sam_response(payload) -> SamSuccess | SamFailure`

The result is typed mask facts or a typed failure. It has no confidence band.

| Type | Fields |
| --- | --- |
| `SamMask` | `label: str`, `score: Decimal`, `caption: str` |
| `SamSuccess` | `masks: tuple[SamMask, ...]` |
| `SamFailure` | `code: str`, `sentence: str` |

Models are frozen and forbid extra fields. A score is taken from the JSON string with `Decimal`, not through `float`.

A payload with an `error` object returns `SamFailure`. Otherwise the `masks` array returns `SamSuccess`.

## Fixtures

Files live in `tests/fixtures/sam/`. The policy threshold these facts are compared with is `Decimal("0.80")`. The parser does not apply the threshold. The test does.

### `tank_success.json`

One mask, label `tank`, score `0.91`, caption `A tank on a level base.`

`0.91` is at or above `0.80`.

### `no_mask.json`

`masks` is an empty array. The result is `SamSuccess` with no masks.

### `error.json`

```json
{ "error": { "code": "sam.unavailable", "sentence": "The segmenter did not return a result." } }
```

The result is `SamFailure` with that code and sentence.
