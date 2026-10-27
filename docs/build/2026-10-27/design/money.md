# Money

Written 27 October 2026. Tests and `quotedesk/domain/shared/money.py` implement this note and nothing beyond it.

`Money` is an amount of South African rand held as `Decimal`. The quote card formats amounts. This type does not.

## Module

`quotedesk.domain.shared.money`

Imports allowed: the standard library and Pydantic. `Decimal` comes from `decimal`. The type is a frozen Pydantic model.

## Value

| Field | Type | Rule |
| --- | --- | --- |
| `amount` | `Decimal` | Quantized to cents (`Decimal("0.01")`) with `ROUND_HALF_EVEN`. Zero is legal. |
| `currency` | `Literal["ZAR"]` | The only legal currency. |

Two values with the same cents and currency are equal. The value is immutable.

## Construction

`Money(value)` and `Money.parse(value)` accept the same inputs. `currency` defaults to `"ZAR"` and may be passed as a keyword.

Accepted:

| Input | Result |
| --- | --- |
| `Decimal("12.50")` | 12.50 |
| `"12.50"` | 12.50 |
| `12` | 12.00 |
| `"0"`, `"0.00"`, `0`, `Decimal("0")` | 0.00 |

An `int` is a whole number of rand, not a number of cents. `12` and `"12.50"` are different amounts.

A string is accepted only when it matches `^\d+(\.\d+)?$`. Spaces, a leading plus, thousands separators, currency symbols, and exponent notation are rejected.

Rejected before any conversion, because `Decimal(0.1)` is not a decimal amount:

| Input | Code |
| --- | --- |
| A `float`, including `0.1`, `1.0`, and `12.50` | `money.float` |
| A `bool` | `money.invalid` |
| Negative `int`, negative `Decimal`, or a string of a negative amount | `money.negative` |
| `None`, `""`, or a string of only spaces | `money.blank` |
| Any currency other than `ZAR` | `money.currency` |
| `Decimal("NaN")`, `Decimal("Infinity")`, or an unusable string | `money.invalid` |

Every rejection raises `quotedesk.domain.shared.errors.ValidationError` with that code and a non-empty sentence. It does not raise `ValueError`, Pydantic's `ValidationError`, or a bare `Exception`.

## Quantizing

| Input | Cents |
| --- | --- |
| `"1.004"` | 1.00 |
| `"1.005"` | 1.00 |
| `"1.006"` | 1.01 |
| `"1.015"` | 1.02 |

## Arithmetic

Operations return a new `Money`. They do not mutate the receiver.

| Operation | Rule |
| --- | --- |
| `Money + Money` | Same currency. Cents are summed. `Money("0.10") + Money("0.20")` is `0.30`. |
| `Money * int` and `int * Money` | The int is a quantity. `Money("0.10") * 3` is `0.30`. |
| `Money * Decimal` and `Decimal * Money` | The decimal is a quantity. `Money("0.10") * Decimal("2.5")` is `0.25`. |
| A float quantity | `money.float` |
| A negative quantity | `money.negative` |
| `Money + int`, `Money * Money` | `money.invalid` |

`Money * 0` is `0.00`. A later pricing rule rejects a zero quantity. This type does not.

There is no division, comparison, or display method today. `__str__` is not a quote-card format.

## Sentences

| Code | Sentence |
| --- | --- |
| `money.float` | A price must be a decimal amount, not a floating-point number. |
| `money.negative` | A price cannot be negative. |
| `money.blank` | A price is required. |
| `money.currency` | Prices are in ZAR. |
| `money.invalid` | That amount cannot be used as a price. |
