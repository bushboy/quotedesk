# Commitment checker

Written 31 October 2026. Tests and `quotedesk/domain/services/commitments.py` implement this note and nothing beyond it.

The proposed shape in the Saturday plan is confirmed. The function is pure. It takes the draft reply and the amounts, civil dates, clause sentences, and schedule status that this turn's tools returned. It does not call a model, read the clock, or send a message.

`RunAgentTurn` is the caller. It is block B. This function does not write the outbox, and it does not choose the customer sentence for a refusal.

## Module

`quotedesk.domain.services.commitments`

```text
check_reply(reply: str, facts: TurnFacts) -> CheckResult
```

The module imports the standard library, Pydantic, and `quotedesk.domain`. It does not import `quotedesk.application`, `quotedesk.adapters`, or `quotedesk.infrastructure`. It does not call `datetime.now` or `date.today`.

`TurnFacts` and `CheckResult` live in this module. They are frozen Pydantic models with extra fields forbidden. The function does not take `GetQuoteResult`. Block B copies tool fields into `TurnFacts`.

## TurnFacts

| Field | Type | Default |
| --- | --- | --- |
| `amounts` | `tuple[Money, ...]` | empty |
| `civil_dates` | `tuple[date, ...]` | empty |
| `clauses` | `tuple[Condition, ...]` | empty |
| `schedule_status` | `none`, `indicative`, `held`, `confirmed`, or `escalated` | `none` |
| `price_kind` | `fixed`, `range`, or `none` | `fixed` |
| `card_link` | `str` or `None` | `None` |

`Condition` is the domain type from `quotedesk.domain.policy.clauses`. The checker reads `clause_id`, `kind`, and `text`.

## CheckResult

| Field | Type |
| --- | --- |
| `ok` | `bool` |
| `code` | `str` or `None` |

`ok` True has `code` `None`. `ok` False has one code. The first failing check wins, in this order: amount, date, inclusion, guarantee, range, link.

| Code | Check |
| --- | --- |
| `commitment.amount` | A rand amount in the reply is not in `amounts` |
| `commitment.date` | A date claim is not a civil date in `civil_dates` |
| `commitment.inclusion` | An "includes" claim is not a non-exclusion clause |
| `commitment.guarantee` | The reply says guaranteed and the status is `escalated` |
| `commitment.range` | `price_kind` is `range` and the reply does not say range |
| `commitment.link` | `card_link` is set and the reply does not contain it |

A reply that states nothing the checks look for, with `card_link` left `None` and `price_kind` left `fixed`, is `ok` True. The tests do not use that reply.

## Amounts

An amount in the reply is a number marked as rand. A leading `R`, or a trailing `rand`, marks it. A bare integer is not an amount. `5000 L` and `14 days` are not amounts.

These four spellings are the same amount, `Decimal("4250.00")`:

| Spelling |
| --- |
| `R 4 250` |
| `R4250` |
| `R 4,250` |
| `4250 rand` |

`R 4 250.00` is the same amount. Spaces or commas group thousands. Cents are optional. The parsed value is quantized to cents with `ROUND_HALF_EVEN` and compared with `Money.amount`.

Every marked amount in the reply must equal one value in `facts.amounts`. One marked amount that equals none fails with `commitment.amount`.

The tool amount in these cases is `Money("4250.00")`. `card_link` stays `None`. `price_kind` stays `fixed`.

| Reply | `amounts` | Result |
| --- | --- | --- |
| `The total is R 4 250.` | `Money("4250.00")` | `ok` True |
| `The total is R4250.` | `Money("4250.00")` | `ok` True |
| `The total is R 4,250.` | `Money("4250.00")` | `ok` True |
| `The total is 4250 rand.` | `Money("4250.00")` | `ok` True |
| `The total is R 4 250.` | empty | `ok` False, `commitment.amount` |
| `R 4 250 or R 3 000` | `Money("4250.00")` | `ok` False, `commitment.amount` |

The last row is a second price. `R 3 000` is not in the tool result. The check fails before any later check.

## Dates

A civil date in the reply is a day and a full English month name, with an optional year: `7 November`, or `7 November 2026`. The day and the month must match a date in `civil_dates`. A year in the reply must match that date's year. A missing year matches on day and month.

The checker does not read the clock, so it does not turn a weekday into a date. These phrases are date claims, and each fails with `commitment.date`:

- `this` or `next` followed by a weekday name. The fixture is `this Saturday`.
- `today`
- `tomorrow`
- `next week`

The match is case insensitive, on a word boundary.

| Reply | `civil_dates` | Result |
| --- | --- | --- |
| `We can do 7 November.` | `date(2026, 11, 7)` | `ok` True |
| `We can do this Saturday.` | empty | `ok` False, `commitment.date` |

`7 November` passes because the tool date is 7 November 2026. `this Saturday` fails because the phrase is not that civil date. The checker does not treat the two as the same day.

## Inclusions

A claim is the word `includes` followed by the rest of that sentence, case insensitive. The claim passes when a clause whose `kind` is not `exclusion` has `text` that contains the claim phrase, case insensitive. Otherwise the code is `commitment.inclusion`.

One alias is fixed in this module. It is not a model call.

| Claim phrase | Fails when an exclusion's `text` contains |
| --- | --- |
| `council plans` | `municipal building plan` |

The alias is checked against clauses whose `kind` is `exclusion`. A hit fails even when the exclusion text does not contain the words `council plans`.

Passing clause:

| Field | Value |
| --- | --- |
| `clause_id` | `GEN-I1` |
| `clause_version` | `1` |
| `kind` | `assumption` |
| `text` | Includes installation. |
| `if_not_true` | Re-quote. |

Reply `This includes installation.` with that clause is `ok` True. The phrase `installation` is in the clause text, and the kind is not `exclusion`.

Failing clause, CARPORT-X1:

| Field | Value |
| --- | --- |
| `clause_id` | `CARPORT-X1` |
| `clause_version` | `1` |
| `kind` | `exclusion` |
| `text` | Excludes municipal building plan approval, where required |
| `if_not_true` | Customer's responsibility; stated, not handled |

Reply `This includes council plans.` with that clause is `ok` False, `commitment.inclusion`. The exclusion text contains `municipal building plan`, which is the alias for `council plans`.

## Guarantee

`schedule_status` `escalated` and the reply containing `guaranteed`, case insensitive, on a word boundary, fails with `commitment.guarantee`.

| Reply | `schedule_status` | Result |
| --- | --- | --- |
| `Your installation date is guaranteed.` | `escalated` | `ok` False, `commitment.guarantee` |

`amounts` is empty, so the amount check does not fail first. The other statuses do not fail this word in this note.

## Range and link

When `price_kind` is `range`, the reply must contain the word `range`, case insensitive. If it does not, the code is `commitment.range`.

When `card_link` is not `None`, the reply must contain that string. If it does not, the code is `commitment.link`. When `card_link` is `None`, the link check does not run. The amount tests leave it `None`.

The passing reply uses both tool ends, the word range, and the link. `schedule_status` stays `none`.

| Field | Value |
| --- | --- |
| `amounts` | `Money("8500.00")`, `Money("12400.00")` |
| `price_kind` | `range` |
| `card_link` | `https://card.example/QD-1042` |
| reply | `The range is R 8 500 to R 12 400. Your card: https://card.example/QD-1042` |

That reply is `ok` True. Both marked amounts are tool amounts, the reply names a range, and the reply contains the card link.
