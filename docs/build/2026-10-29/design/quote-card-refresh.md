# Quote card refresh

Written 29 October 2026. Agents update four fixtures from the printable quote and the price examples. They do not add an eleventh state. The route, the ten fixture names, and the template rules stay as written on Tuesday in [quote-card-states.md](../../../2026-10-27/design/quote-card-states.md).

Files they may change:

- `tests/fixtures/quote_card/fixed_offer.json`
- `tests/fixtures/quote_card/range.json`
- `tests/fixtures/quote_card/site_visit.json`
- `tests/fixtures/quote_card/hazard.json`

`quotedesk/adapters/inbound/http/templates/quote_card.html` and `base.html` stay free of a hard-coded amount, fee, or date. Display strings live in the fixtures.

Display rules, unchanged:

- Money uses a space as the thousands separator and two cents digits.
- Dates read `7 November 2026`.
- No WhatsApp logo and no Meta logo.

Business name stays `AquaSure Gauteng`. Quote id stays `QD-1042`. A field that does not apply stays `null`. `next_step` stays `null` on these four.

## Fixed offer

`state` stays `fixed_offer`.

| Field | Value |
| --- | --- |
| `headline` | `Fixed quote` |
| `rule_id` | `WATER-F01` |
| `body` | `We can send a fixed quote for this replacement.` |
| `amount_display` | `R 4 250.00` |
| `expiry_display` | `7 November 2026` |
| `range_min_display` | `null` |
| `range_max_display` | `null` |
| `fee_display` | `null` |

`clauses` is copied from [quote-fixture.md](quote-fixture.md). Each card clause has `text` and `if_not_true` only, in that order:

| `text` | `if_not_true` |
| --- | --- |
| Size is 5 000 L, as stated. | We quote again for the actual size. |
| This price is valid for 14 days. | After expiry, re-quote at the current rate card |
| No installation date is reserved until the 30% deposit is paid. | See scheduling rules |

## Range

`state` stays `range`. Headline stays `Price range`. Rule stays `FAB-R01`. Body stays `Here is a price range. It depends on the assumptions below.`

| Field | Value |
| --- | --- |
| `amount_display` | `null` |
| `range_min_display` | `R 8 500.00` |
| `range_max_display` | `R 12 400.00` |
| `fee_display` | `null` |
| `expiry_display` | `7 November 2026` |

`clauses` copies `text` and `if_not_true` from the eleven rendered carport rows in [clauses.md](clauses.md), in that order. There is no single total.

## Site visit

`state` stays `site_visit`. Headline stays `Site visit needed`. Rule stays `WATER-S02`. Body stays `This one needs a visit before we can give a fixed price. The visit fee is R 750.00, and it comes off the job if you go ahead.`

| Field | Value |
| --- | --- |
| `amount_display` | `null` |
| `range_min_display` | `null` |
| `range_max_display` | `null` |
| `fee_display` | `R 750.00` |
| `expiry_display` | `null` |

`clauses` stays an empty list. The fee is the visit fee. The fixture has no deposit amount.

## Hazard

`state` stays `hazard`. Headline stays `We can't price this yet`. Rule stays `WATER-E03`.

| Field | Value |
| --- | --- |
| `body` | `Please isolate the power near the water, and stay clear of it until we've checked the site.` |
| `amount_display` | `null` |
| `range_min_display` | `null` |
| `range_max_display` | `null` |
| `fee_display` | `null` |
| `expiry_display` | `null` |

`clauses` stays an empty list. The body is WATER-E03's customer template. There is no amount and no fee.
