# Rate-card import

Written 1 November 2026. Tests and `quotedesk/application/use_cases/imports/import_rate_card.py` implement this note and nothing beyond it.

This file is the block C design. Block B's gate is green, and the tests and `ImportRateCard` follow this note. PDF, Word, PowerPoint, and photo are not this file.

An Excel card becomes draft rows. Publish stays [policy-publish.md](policy-publish.md). The number in a cell is the number stored. A model may only label a column. The Sunday tests inject a fake labeller. They do not call a live model.

## Module

`quotedesk.application.use_cases.imports.import_rate_card`

```text
ImportRateCard.execute(context, data) -> ImportResult
```

The use case does not import a model SDK. It does not call `PublishPolicy`. It does not call the network.

`.xlsx` is read with `openpyxl`, data only. `.csv` is read with the standard library. The macro check is Wednesday's `reject_macros_before_parse` in `quotedesk.adapters.outbound.parsers.macros`. It runs before either reader. A rejected file does not reach `openpyxl` or the csv reader.

## Input

Frozen. `extra` is forbid.

```text
ImportRateCardInput
    filename: str
    body: bytes
    expected_unit: str
    labeller: ColumnLabeller
```

`ColumnLabeller.label(headers) -> Mapping[str, str]` maps a field name to a header. The test's fake maps `unit_price` to `item_code`. That map is not used to choose the price cell.

The price is the cell in the column whose header text is `unit_price`. The item code is the cell under `item_code`. The unit is the cell under `unit`. Header comparison strips spaces and is case-insensitive.

## Fixture sheet

Two items. The same rows are the `.xlsx` and the `.csv`.

| Cell | item_code | unit_price | unit |
| --- | --- | --- | --- |
| Row 2 | `TANK-5000` | `4250.50` | `each` |
| Row 3 | `PUMP-STD` | `1800.00` | `each` |

`4250.50` is stored as `Decimal("4250.50")`. `1800.00` is stored as `Decimal("1800.00")`. The fake labeller that points `unit_price` at `item_code` does not move either number.

Each ready row records its price cell. `TANK-5000` is `B2` on the xlsx. `PUMP-STD` is `B3`.

## Result

```text
ImportResult
    rows: tuple[ImportedRow, ...]
    unmapped_text: tuple[str, ...]

ImportedRow
    item_code: str
    unit_price: Decimal | None
    unit: str
    flags: tuple[str, ...]
    status: Literal["ready", "needs_review"]
    cell: str
```

A row with no flags has status `ready`. Any flag sets `needs_review`. The row is kept.

| Condition | Flag |
| --- | --- |
| Price cell empty | `missing_price`. `unit_price` is `None` |
| Unit cell empty | `blank_unit` |
| Unit is `each` and `expected_unit` is `m2` | `unit_mismatch` |
| The same `item_code` appears twice | `conflict` on both rows |

Conflict fixture: item `WIN-STD` at `850` and again at `900`. Both rows are returned. Both are `needs_review`. No row stores `875` or any other merged price.

A paragraph that is not a header and not an item row is appended to `unmapped_text` unchanged. The fixture sentence is `Call us about unusual shapes.` It is not a row.

## What is refused

Wednesday's macro error is unchanged.

| Suffix | Result |
| --- | --- |
| `.xlsm`, `.docm`, `.pptm` | `MacroRejected`, code `import.macro`, sentence `Macro-enabled files aren't accepted. Save a copy without macros and send that.` The reader is not called |
| `.pdf`, `.docx`, `.pptx`, `.png`, `.jpg` | `ValidationError`, code `import.unsupported`, sentence `That file type isn't imported yet.` The reader is not called |

| Body | Code | Sentence |
| --- | --- | --- |
| `b""` | `import.empty` | That file is empty. |
| Length greater than `2_000_000` | `import.oversize` | That file is too large. |

Both are `ValidationError`. A file of length `2_000_000` is inside the limit. Length `2_000_001` is not. Neither error returns rows. The draft is not given a partial list.

## Draft, not published

The rows replace the draft's rate rows for that tenant. The published bundle is the object `published()` returned before the call. Its version id and its item prices are unchanged. `PublishPolicy` is the only way those rows become the live card.
