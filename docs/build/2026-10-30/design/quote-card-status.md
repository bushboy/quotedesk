# Quote card status line

Written 30 October 2026. Agents update the fixed-offer fixture and the card template. They do not add a state, a route, or a use case.

`GetQuoteStatus` is Saturday. This note is a fixture the existing preview can show.

## What changes

| File | Change |
| --- | --- |
| `tests/fixtures/quote_card/fixed_offer.json` | One new field, `status_line` |
| `quotedesk/adapters/inbound/http/templates/quote_card.html` | Render `card.status_line` when it is present |

The route stays `GET /dev/quote-card/{state}`. The ten fixture names stay as Tuesday wrote them. No eleventh state.

The other nine fixtures do not gain `status_line`. The template skips a missing field, as it already skips a null field.

## The line

`status_line` on the fixed-offer fixture is:

```text
ISSUED · version 1 · 7 November 2026 · none
```

That string is the fixture's. The template prints it. It does not assemble the state, the version, the date, or the schedule status itself.

`state` stays `fixed_offer`. `headline` stays `Fixed quote`. `amount_display` stays `R 4 250.00`. `expiry_display` stays `7 November 2026`. The clauses stay the three sentences already on that fixture.

Display rules stay Tuesday's. A space is the thousands separator. Dates read `7 November 2026`. No WhatsApp logo and no Meta logo. No amount, fee, or date is hard-coded in the template.
