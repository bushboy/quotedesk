# Swap and new installation

Written 31 October 2026. Increment 1 of [the checklist](../swap-vs-new.md). The domain can price a swap and a new installation from one material row plus infrastructure rows. The console, the question, and the rules are later increments. This note does not add a price to a seed or a demo card.

One material price. A tank and a sheet stay one row each. Infrastructure rows are selected by `applies_to`. A range adds those shared rows to both ends.

## Modules

`quotedesk/domain/services/price.py`

`RateCardItem` gains `applies_to`: `both`, `swap`, or `new`. The default is `both`. A row that exists today is `both`.

`PriceFacts` gains `work`: `swap`, `new`, or empty. Empty means the caller has not chosen. Increment 1 leaves `get_quote` on empty. Choosing from the case is increment 3.

`quotedesk/domain/policy/draft.py`

`DraftRateRow` gains `applies_to`, the same three values, default `both`.

`quotedesk/application/use_cases/editor/publish_policy.py`

Publish copies `applies_to` onto the published `RateCardItem`. A row that omits it publishes as `both`.

`quotedesk/application/use_cases/tools/get_quote.py` does not set `work` in this increment.

`quotedesk/domain/services/validate_policy.py` rejects a duplicated infrastructure price. `price()` does not show that sentence.

## Composer

`_composed` still starts from the requested item codes. Those are the material. It still skips role `product`. For each other role on `PriceFacts.roles`, it adds a card row of that role when the code is not already requested and the row applies:

| `applies_to` | `work` empty | `work` `swap` | `work` `new` |
| --- | --- | --- | --- |
| `both` | added | added | added |
| `swap` | left out | added | left out |
| `new` | left out | left out | added |

A role the facts do not list adds nothing. A listed role with no matching row adds nothing. No stand amount is invented.

The pivot-door fixture stays. Its rows omit `applies_to`, so they are `both`, and a fixed offer that lists those roles still composes door, frame, handle, installation, and delivery.

## Range and fixed

An indicative range prices each requested product, then adds the extended price of the composed infrastructure rows to both ends. `lines` stays empty.

A sheet at R 180 per m² and a sheet at R 260 per m², 5 m by 7 m, plus a frame at R 50 per m² marked `new`, with `work` `new`, has `range_min` `8050.00` and `range_max` `10850.00`. The frame area is R 1 750.00 on both ends. The span is the two sheets.

A fixed offer still has one line per composed item, and the line total is the sum. `price()` still returns `deposit` `None`. The deposit percent is applied by `get_quote`, to that sum for a fixed offer and to `range_min` for a range. This increment does not change that.

The 29 October fixture is unchanged when no infrastructure row is requested. `TANK-5000` at quantity 1 is `4250.00`. A range over `ROOF-SHADE` and `ROOF-SHEET` is `8500.00` to `12400.00`.

## One price per role and kind of work

`validate_policy` appends one error when two non-product rows share a role and an `applies_to`.

| Code | Sentence |
| --- | --- |
| `policy.duplicate_role` | A role has one price for each kind of work. |

Two installation rows both marked `new` are that error. One `swap` installation row and one `new` installation row are valid. Two product rows are valid. `price()` does not raise this sentence.
