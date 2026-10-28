# WhatsApp simulator handoff

Written for a second team joining the simulator. The pipe is already built. This note says where it lives, what the page already does, and what is still yours.

Read [whatsapp-simulator-learnings.md](whatsapp-simulator-learnings.md) before changing the page. That note is the paint rule. [harness.md](harness.md) and [click-path.md](click-path.md) are the designs the current code follows. This file adds no test and ticks no box.

The demo does not connect a WhatsApp Business number. Replies stay in the outbox.

## What you are building

One conversation that looks like a customer thread. The page and the harness share one pipe:

```text
page or harness
  POST /whatsapp/webhook     Cloud API JSON, one event
  GET  /whatsapp/outbox      rows in append order

webhook
  ReceiveInboundEvent
  200, empty body
  a gate sentence, when there is one, is an outbox row

worker
  RunAgentTurn after the webhook returns
  the checked reply is a later outbox row
```

The page paints the customer's own bubble at send time. It does not draw the webhook response. Agent bubbles come only from the outbox.

## Where it is built

| Piece | Path | What it does |
| --- | --- | --- |
| Cloud API fixture | `tests/fixtures/whatsapp/text_message.json` | The only inbound shape. One text message, `wa_id` `15550002222`, body `The tank in the yard is leaking.` |
| Fixture check | `tests/adapters/test_whatsapp_fixture.py` | Asserts that file. Do not change the shape. |
| Outbox | `quotedesk/adapters/outbound/channels/outbox.py` | In-process list. `append` assigns `id` starting at 1 and stores `wa_id`, `body`, `status` `pending`. `pending()` does not delete rows. Nothing here calls the network. |
| Webhook and outbox HTTP | `quotedesk/adapters/inbound/http/whatsapp.py` | `POST /whatsapp/webhook` parses one Cloud API message, calls `ReceiveInboundEvent`, schedules `run_turn`, returns 200 with an empty body. `GET /whatsapp/outbox` returns pending rows. Optional `wa_id` and `after` filter that list. `after` is the last `id` the caller has drawn. |
| Harness | `harness/runner.py` | Reads a scenario YAML, copies the fixture, posts one payload per event, then reads the outbox twice and fails if the second read differs. |
| Scenarios | `harness/scenarios/` | `text.yaml`, `s08.yaml`, `aquasure_5000l.yaml`, and `s01.yaml` through `s12.yaml`. |
| Harness tests | `tests/adapters/test_harness.py` | Text post, S08 duplicate and order, 5000 L reply contains `R 4 250` and no other amount. |
| Demo wiring | `quotedesk/infrastructure/demo.py` `install` | Builds the in-memory outbox, the receive use case, and the turn. One tenant, one conversation. |
| App | `quotedesk/infrastructure/container.py` | Serves `/health`, the quote card, the webhook, and `/chat`. The model is `QuoteScript`. |
| Page | `quotedesk/adapters/inbound/http/chat.py` and `templates/chat.html` | `GET /chat`. This is the shell you extend. |
| Card | `quotedesk/adapters/inbound/http/chat.py` `GET /card/{quote_id}` | Opens only with code `1042` on `QD-1042`. |
| Media | `seeds/media/` | `5000l-voice.wav`, `tank-on-base.png`, `tank-mask.png`, served at `GET /media/{name}`. |

`quotedesk/application/use_cases/conversation/receive_inbound.py` stores the event or writes a gate sentence to the outbox. `run_agent_turn.py` writes the checked reply. The commitment checker does not write the outbox. Leave those modules alone.

## How to run it

From the repository root, with `.env` loaded:

```powershell
python -m uvicorn quotedesk.infrastructure.main:create_app --factory --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000/chat. The business name is AquaSure. Type the 5000 L transcript and send it. The reply's only amount is `R 4 250`. The link is `/card/QD-1042?code=1042`.

The running app uses `QuoteScript` in `demo.py`. Every turn calls `update_case` and `get_quote` with the 5000 L replacement facts and sends:

```text
The total is R 4 250. Your card: /card/QD-1042?code=1042
```

Typed text does not change that script. Live Spark stays parked.

The harness does not need the server:

```powershell
pytest tests/adapters/test_harness.py tests/adapters/test_whatsapp_fixture.py -q
```

## What the page already does

`chat.html` already follows the parts of the paint rule that the click-path required:

- Business name AquaSure, empty line "Send a message to AquaSure." No WhatsApp logo and no Meta logo.
- Composer stays enabled. Enter sends. Shift+Enter inserts a line.
- The customer bubble is painted before the POST, including a photo from a chosen file.
- The POST body is Cloud API JSON in the fixture's shape. The response body is not drawn.
- Agent bubbles come from `GET /whatsapp/outbox?wa_id=15550002222&after=<id>` every 300 ms. Reads do not delete rows.
- A `/card/QD-…?code=…` URL in a reply becomes a link labelled "Fixed quote".
- The column is at most 720 px wide.

The pinned customer is `wa_id` `15550002222`. A second conversation is a different `wa_id` on the outbox query. The webhook still stores every event on the one conversation id held in `app.state`.

## What is still yours

These are the paint rules in the learnings note that `chat.html` does not do yet. They belong on the page. They do not need a new route.

- Pause the poll while the tab is hidden. Resume it when the tab is visible, and catch up from `after`.
- A typing row of fixed height, in the same paint as the customer bubble, until an outbox row for that send arrives. After a video acknowledgement the dots return, because the quote is a later row.
- Several rows in one poll draw as separate bubbles, 140 ms apart, in append order.
- Follow the bottom only when the reader is already within 80 px of it. Otherwise leave them and offer a way back down. Opening the card must not move the transcript.
- The composer grows to four lines and accepts a pasted image. It stays enabled.
- A failed POST marks that bubble "Not sent" and retries the same provider message id. A success has no status badge.
- Timestamps on bubbles are Johannesburg local, the same rule as the card.
- An image reserves its box before it loads. A voice file is a row in the thread with its duration. The voice file on disk is `seeds/media/5000l-voice.wav`. The page currently pins an `<audio>` control above the thread.
- The card control's label is the headline the tool returned. The shell hardcodes "Fixed quote".

Two behaviours in the current shell are wrong for a photo send, and they are yours to fix in the page:

- Every send paints a photo. With no file chosen it uses `/media/tank-on-base.png`.
- The webhook payload is always `type` `text`. The chosen file never becomes `messages[0].type` `image`.

The parser in `whatsapp.py` reads `type` as `text`, `image`, `audio`, or `video`, and reads `text.body` only for text. It does not read a media id, a MIME type, or a size. `InboundMessage` can carry `mime`, `size_bytes`, `duration_seconds`, `transcript`, and `image_text`. The demo gate limit is `max_bytes` 100, so a real photo size posted through that parser is refused with "That file is too large or of a type I can't read." Do not raise that limit to make a photo fit. The Saturday path sends the photo as a local preview and the transcript as text.

The outbox row has `id`, `wa_id`, `body`, and `status`. It has no `media_url`. Do not add one unless the harness tests still pass with the fields they already read.

## What you may edit

- `quotedesk/adapters/inbound/http/templates/chat.html`
- `quotedesk/adapters/inbound/http/chat.py`, for serving the page and the media files

Leave the pipe where it is:

- `quotedesk/domain/`
- `quotedesk/application/ports/`
- `quotedesk/application/dto/`
- `quotedesk/application/use_cases/`
- `seeds/`
- `tests/unit/`
- `tests/use_cases/`
- `tests/fixtures/whatsapp/text_message.json`
- `harness/runner.py` and `harness/scenarios/`

`POST /whatsapp/webhook` and `GET /whatsapp/outbox` stay. A new inbound dialect, a drained queue, a two-second poll, a disabled composer, a WhatsApp glyph, a Meta logo, an HTTP status on a bubble, or a raw-payload drawer puts the thread back to the tester this note was written to leave behind.

## Done when

A person can open `/chat`, send the 5000 L transcript, see their bubble immediately, see the reply arrive from the outbox as its own bubble, and open the card from that bubble. `pytest tests/adapters/test_harness.py tests/adapters/test_whatsapp_fixture.py -q` still passes. The outbox still does not send to WhatsApp.
