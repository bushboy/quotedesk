# Price

Written 29 October 2026. Tests and `quotedesk/domain/services/price.py` implement this note and nothing beyond it.

D5 and D7 are confirmed as written in the week plan. They are not overturned.

`price` returns a `PricedQuote`. It does not write an amount onto a `Decision`.

## Signature

```text
price(decision, facts, rate_card) -> PricedQuote
```

Module: `quotedesk.domain.services.price`.

Amounts are `Money`. The function does not read the clock, the environment, or the network. It does not import an adapter.

`decision` is Wednesday's `Decision`. `facts` is a `PriceFacts`. `rate_card` is a `RateCard`. All three are frozen Pydantic models with extra fields forbidden, as is `PricedQuote`.

## Rate card

One VAT basis for the whole card, on `RateCard.vat_inclusive: bool`. Items have no VAT flag of their own.

| Field on `RateCardItem` | Type |
| --- | --- |
| `item_code` | `str` |
| `description` | `str` |
| `unit_price` | `Money` |

`RateCard.site_visit_fee` is `Money`. That is the settings fee for this function.

D5. `price` copies `unit_price`. It does not multiply or divide by `Decimal("1.15")`. A unit price of `4250.00` stays `4250.00`. It does not become `4887.50` and it does not become a VAT-stripped amount. Mixed inclusive and exclusive rows are Sunday's `validate_policy`.

The fixture card in the price tests:

| Item | Unit price | Description |
| --- | --- | --- |
| `TANK-5000` | `4250.00` | `5000 L tank` |
| `ROOF-SHADE` | `8500.00` | `Shade net covering` |
| `ROOF-SHEET` | `12400.00` | `Sheet covering` |
| `HEIGHT-EXTRA` | `600.00` | `Extra clearance height` |

`vat_inclusive` is `True`. `site_visit_fee` is `750.00`. Every amount is `Money`.

## Facts

`PriceFacts.items` is a tuple of `RequestedItem(item_code: str, quantity: Decimal)`.

`PriceFacts.discount_percent` is a `Decimal`. The fixture passes `Decimal("10")`. `price` ignores it.

## PricedQuote

| Field | Type |
| --- | --- |
| `price_type` | `fixed`, `range`, or `none` |
| `lines` | `tuple[PricedLine, ...]` |
| `range_min` | `Money` or `None` |
| `range_max` | `Money` or `None` |
| `site_visit_fee` | `Money` or `None` |
| `deposit` | `Money` or `None` |
| `discount_percent` | `Decimal` |

`PricedLine` fields: `item_code`, `description`, `quantity: Decimal`, `unit_price: Money`, `total: Money`. `description` and `unit_price` are copied from the card. `total` is `quantity * unit_price` in cents.

`deposit` is `None` on every result this function returns. `discount_percent` is `Decimal("0")` on every result.

## Outcomes

The low-confidence check comes first. `fixed_offer` with `confidence_band` `low` raises `PolicyViolation`. `price` does not change the outcome, the band, or any other field on the decision.

| Outcome | `price_type` | What is filled |
| --- | --- | --- |
| `fixed_offer`, band `high` or `medium` | `fixed` | One `PricedLine` per requested item. Range and fee are `None`. |
| `indicative_range` | `range` | `range_min` and `range_max` from the named items' unit prices. `lines` is empty. Fee is `None`. |
| `site_assessment` | `none` | `site_visit_fee` is the card's fee. `lines` is empty. Range is `None`. |
| `escalation` | `none` | `lines` is empty. Range, fee, and deposit are `None`. |

A fixed offer with quantity `Decimal("1")` of `TANK-5000` has unit price `4250.00` and total `4250.00`. Quantity `Decimal("2.5")` has unit price `4250.00` and total `10625.00`.

A range over `ROOF-SHADE` and `ROOF-SHEET` has `range_min` `8500.00` and `range_max` `12400.00`, whichever code is listed first. Both ends are those rate-card amounts. `min <= max`.

One named covering keeps `price_type` `range` and sets `range_min == range_max` to that item's unit price.

A site assessment uses fee `750.00`. The fee is not copied into `deposit`. D7.

An escalation has every money field empty. No fee and no deposit. Item codes on the facts are not read. D7.

## Refusals

Each refusal raises `PolicyViolation` with code `policy.violation`. The exception has no line list, no `lines` attribute, and no `PricedQuote`.

| Case | Sentence |
| --- | --- |
| `fixed_offer` and band `low` | A fixed quote needs a higher confidence band. |
| One item code absent from the card, on a fixed offer or a range | That item is not on the rate card. |
| One known code and one unknown code together | That item is not on the rate card. |
| A fixed-offer quantity of `0` | A quantity must be greater than zero. |
| A negative fixed-offer quantity | A quantity must be greater than zero. |

Unknown codes and illegal quantities are checked for `fixed_offer` and, for codes, for `indicative_range`. A site assessment and an escalation do not look up item codes and do not read quantities.
