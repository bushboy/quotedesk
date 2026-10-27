# Printable 5000 L quote

Written 29 October 2026. `tests/fixtures/quotes/aquasure_5000l.json` is this document, copied into the tree. The domain test loads that file. It does not add a field.

The file is pretty-printed JSON with a two-space indent and a trailing newline. A reviewer can read the 5000 L line without running code.

## Identity

Issued like-for-like replacement. One version.

| Field | Value |
| --- | --- |
| `quote_id` | `QD-1042` |
| `version` | `1` |
| `state` | `ISSUED` |
| `expiry` | `2026-11-07` |
| Rule | `WATER-F01` |
| Policy | `water-policy-v1.0` |

The card shows the expiry as `7 November 2026`. That display string is not a field in this file.

## Decision

The `decision` object has Wednesday's fields and no amount.

| Field | Value |
| --- | --- |
| `outcome` | `fixed_offer` |
| `rule_id` | `WATER-F01` |
| `policy_version` | `water-policy-v1.0` |
| `reasons` | one string: `Like-for-like replacement on a level base with a stated size.` |
| `confidence_band` | `high` |
| `customer_template` | `We can send a fixed quote for this replacement.` |

## The line

One element in `line_items`.

| Field | JSON |
| --- | --- |
| `item_code` | `"TANK-5000"` |
| `description` | `"5000 L tank"` |
| `quantity` | `"1"` |
| `unit_price` | `"4250.00"` |
| `total` | `"4250.00"` |

`unit_price` and `total` are decimal strings. They are not JSON numbers. `quantity` is a string. The only JSON number in the file is `version`. No value contains a decimal point inside a JSON number. There is no second price: no range, no fee, no discount, and no deposit field.

The test reads `total` as `Money` of `4250.00`, the item as `TANK-5000`, and the state as `ISSUED`.

## Clauses

`clauses` is the water table in [clauses.md](clauses.md), placeholders already filled, in that order.

| `clause_id` | `clause_version` | `kind` | `text` | `if_not_true` |
| --- | --- | --- | --- | --- |
| WATER-A1 | `1` | assumption | Size is 5 000 L, as stated. | We quote again for the actual size. |
| GEN-V1 | `1` | validity | This price is valid for 14 days. | After expiry, re-quote at the current rate card |
| GEN-S1 | `1` | schedule | No installation date is reserved until the 30% deposit is paid. | See scheduling rules |

`variation_item_code` is `null` on each of these three.

## File

```json
{
  "quote_id": "QD-1042",
  "version": 1,
  "state": "ISSUED",
  "expiry": "2026-11-07",
  "decision": {
    "outcome": "fixed_offer",
    "rule_id": "WATER-F01",
    "policy_version": "water-policy-v1.0",
    "reasons": [
      "Like-for-like replacement on a level base with a stated size."
    ],
    "confidence_band": "high",
    "customer_template": "We can send a fixed quote for this replacement."
  },
  "line_items": [
    {
      "item_code": "TANK-5000",
      "description": "5000 L tank",
      "quantity": "1",
      "unit_price": "4250.00",
      "total": "4250.00"
    }
  ],
  "clauses": [
    {
      "clause_id": "WATER-A1",
      "clause_version": "1",
      "kind": "assumption",
      "text": "Size is 5 000 L, as stated.",
      "if_not_true": "We quote again for the actual size.",
      "variation_item_code": null
    },
    {
      "clause_id": "GEN-V1",
      "clause_version": "1",
      "kind": "validity",
      "text": "This price is valid for 14 days.",
      "if_not_true": "After expiry, re-quote at the current rate card",
      "variation_item_code": null
    },
    {
      "clause_id": "GEN-S1",
      "clause_version": "1",
      "kind": "schedule",
      "text": "No installation date is reserved until the 30% deposit is paid.",
      "if_not_true": "See scheduling rules",
      "variation_item_code": null
    }
  ]
}
```
