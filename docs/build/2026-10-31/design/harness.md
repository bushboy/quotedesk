# Harness

Written 31 October 2026. Tests and `harness/runner.py` implement this note and nothing beyond it.

The proposed shape in the Saturday plan is confirmed. One runner posts a scenario to the webhook and reads the reply from the outbox. It does not send to WhatsApp. It does not call a model. It does not open a network connection to WhatsApp. The turn uses the scripted model from [run-agent-turn.md](run-agent-turn.md).

The Wonder judge is not this runner. Code checks the outbox and the case. S12 with `afrikaans_voice` on stays out.

Thursday's text fixture and the outbox shell stay. This note adds the runner, the scenario files, `id`, and `wa_id`.

## Module

`harness/runner.py`

Scenarios live in `harness/scenarios/`. A scenario is YAML.

```text
run(app, scenario_path) -> RunReport
```

`RunReport` has `outbox: tuple` and `case`. `outbox` is the body of `GET /whatsapp/outbox` after the posts. The runner does not import `quotedesk.domain.services`.

## One event, one payload

Each scenario event becomes one Cloud API payload in the same shape as `tests/fixtures/whatsapp/text_message.json`. The runner posts that JSON to `POST /whatsapp/webhook`. The response status is 200. The response body has no customer text.

A text event:

```yaml
- id: wamid.TEXT1
  at: 0
  from: "15550002222"
  text: The tank in the yard is leaking.
```

lands as `messages[0].type` `text`, `messages[0].id` `wamid.TEXT1`, `messages[0].from` `15550002222`, `messages[0].text.body` that sentence, and `messages[0].timestamp` the unix seconds of `at`. `at` is seconds from `datetime(2026, 10, 24, 0, 0, tzinfo=timezone.utc)`.

`object`, `entry[0].id`, `metadata`, and `contacts[0].wa_id` stay the fixture's values, except `wa_id` and `from`, which are the event's `from`.

## Outbox read

`GET /whatsapp/outbox` with no query returns every pending row, in append order. The read does not delete rows. A second GET returns the same rows.

`OutboxMessage` gains two fields. `body` and `status` stay.

| Field | Rule |
| --- | --- |
| `id` | An int. The first append is `1`. Each append adds 1 |
| `wa_id` | The customer the row was sent to |
| `body` | The sentence the use case wrote. The sender does not decorate it |
| `status` | `pending` |

`pending()` still returns the full append-ordered tuple. Nothing in the outbox calls the network.

The webhook calls `ReceiveInboundEvent` and returns. It does not call `RunAgentTurn` inside the request. The test app runs the turn after the post returns, with the scripted model, before the runner reads the outbox. That is how a gate sentence, a video acknowledgement, and a checked reply are rows the GET can see.

## S08

File: `harness/scenarios/s08.yaml`.

Two posts of one payload with id `wamid.S08A` store one event. Then two messages are posted out of arrival order: `wamid.S08C` with `at` 20 is posted before `wamid.S08B` with `at` 10. The conversation reads `wamid.S08B` then `wamid.S08C`. Provider timestamp order, not arrival order.

This scenario can pass once `ReceiveInboundEvent` stores events. It does not need a quote.

## 5000 L text

File: `harness/scenarios/aquasure_5000l.yaml`.

One text event asking to replace a 5000 L tank on a level base. The scripted model calls `GetQuote`. The outbox body contains `R 4 250` and no other rand amount.

This scenario can pass once `RunAgentTurn` can call `GetQuote`. The amount is the tool's `4250.00`, written the way the card writes it.

## What else is named

These files are listed so the runner's shape is fixed. Block B's pytest proof is S08, the 5000 L text, and one posted text payload. The other files wait on the use case each row names.

| File | Proves | Waits on |
| --- | --- | --- |
| `s01.yaml` through `s06.yaml` | The block B conversation proof: one job, the 2500 to 5000 correction, two jobs, one burst, a later answer, one contradiction | `UpdateCase`, `RunAgentTurn`, and the quiet window |
| `s07.yaml` | A message during a turn is on the next turn | The lock test in `design/run-agent-turn.md` |
| `s09.yaml` | An expired quote reads `EXPIRED` | `GetQuoteStatus` |
| `s10.yaml` | Insult, explicit image, identity document, hidden instruction. Each fixed sentence. Explicit and identity bytes absent | The gate |
| `s11.yaml` | `Can I speak to a person?` hands over the case and does not issue a quote | `HandoverToHuman` |
| `s12.yaml` | Afrikaans voice with `afrikaans_voice` off. The fixed sentence. No fact | The gate. The flag-on half is not in this file |

S01 through S06 are the block B proof once those use cases are green. They are not a Wonder score.
