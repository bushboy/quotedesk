# Quote card states

Written 27 October 2026. The daytime UI kit implements this note. The card displays a fixture. It does not price a job.

## Route

`GET /dev/quote-card/{state}`

| URL state | Fixture |
| --- | --- |
| `waiting` | `tests/fixtures/quote_card/waiting.json` |
| `fixed-offer` | `tests/fixtures/quote_card/fixed_offer.json` |
| `range` | `tests/fixtures/quote_card/range.json` |
| `site-visit` | `tests/fixtures/quote_card/site_visit.json` |
| `hazard` | `tests/fixtures/quote_card/hazard.json` |
| `pending-approval` | `tests/fixtures/quote_card/pending_approval.json` |
| `expired` | `tests/fixtures/quote_card/expired.json` |
| `deposit-waiting` | `tests/fixtures/quote_card/deposit_waiting.json` |
| `slot-held` | `tests/fixtures/quote_card/slot_held.json` |
| `error` | `tests/fixtures/quote_card/error.json` |

An unknown state returns 404 and the sentence `That preview does not exist.` It does not render the error card.

The route lives in `quotedesk/adapters/inbound/http/quote_card.py`. `infrastructure/container.py` mounts it. `infrastructure/main.py` does not import the adapter.

Templates:

- `quotedesk/adapters/inbound/http/templates/base.html`
- `quotedesk/adapters/inbound/http/templates/quote_card.html`

Styles live in `base.html`. There is no frontend build.

## Fixture shape

Every fixture uses this object. A field that does not apply is `null`. The template prints strings as given and skips null fields. It does not format numbers and it does not switch on `state` to invent a headline.

```json
{
  "state": "fixed_offer",
  "headline": "Fixed quote",
  "business_name": "AquaSure Gauteng",
  "quote_id": "QD-1042",
  "rule_id": "WATER-F01",
  "body": "Here is your quote.",
  "amount_display": "R 4 250.00",
  "range_min_display": null,
  "range_max_display": null,
  "fee_display": null,
  "expiry_display": "7 November 2026",
  "window_display": null,
  "hold_until_display": null,
  "clauses": [
    {
      "text": "Size is 5 000 litres, as stated.",
      "if_not_true": "We quote again for the actual size."
    }
  ],
  "next_step": null
}
```

Display rules for the strings inside the fixtures:

- Money uses a space as the thousands separator and two cents digits: `R 4 250.00`.
- Dates read `7 November 2026`.
- The headline is the largest text. The rule id is smaller and sits under the headline, labelled `Rule`.
- No WhatsApp logo and no Meta logo.
- No price, fee, or date is hard-coded in the template.

## The ten states

Sample copy below is what the fixture contains so the layout can be reviewed. It is not a policy rule.

| State | Headline | What the customer sees |
| --- | --- | --- |
| Waiting | Preparing your quote | `We're putting this together. You can keep sending details in the chat.` No amount and no rule id. |
| Fixed offer | Fixed quote | `Here is your quote.` Amount `R 4 250.00`. Expiry `7 November 2026`. Rule `WATER-F01`. One clause. |
| Range | Price range | `Here is a price range. It depends on the assumptions below.` Minimum `R 8 500.00` and maximum `R 12 400.00`. No single total. |
| Site visit | Site visit needed | `This one needs a visit before we can give a fixed price. The visit fee is R 750.00, and it comes off the job if you go ahead.` Fee `R 750.00`. No job total. |
| Hazard | We can't price this yet | `Please switch off the power near the pump and stay clear until someone from the business has checked it.` Rule `WATER-E03`. No amount and no fee. |
| Pending approval | Waiting for the owner | `This change needs the owner to confirm it. The price you already have stays as it is until then.` Current amount `R 4 250.00` shown as the current quote. |
| Expired | This quote has expired | `This price has lapsed. Ask in the chat for a new quote.` Expiry `7 November 2026`. No payment action. |
| Deposit waiting | Deposit needed to hold the date | `The date is not held yet. It is held once the deposit is paid.` Deposit `R 1 275.00`. Window `Saturday 7 November 2026`. |
| Slot held | Date held | `This date is held until 9 November 2026.` Window `Saturday 7 November 2026`. Hold end `9 November 2026`. |
| Error | Something went wrong | `We couldn't finish loading this quote.` Next step `Refresh the page, or send us another message in the chat.` No traceback and no exception name. |

`clauses` is an empty list when a state has none. `next_step` is set on the error fixture and null on the others.

## Layout

- One column. The headline is the first text in the card.
- At 375px the page has 16px of padding and the card uses the full width.
- At 1280px the card's maximum width is 40rem and the card is centered.
- A print of the page shows the card and hides the preview chrome.
- The typeface is the system UI stack. The page does not fetch a font.
- Business name is `AquaSure Gauteng` on every fixture. Quote id is `QD-1042` where the state has a quote. Waiting omits the quote id.
