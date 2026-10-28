# WhatsApp simulator learnings

Written 27 October 2026. This note is input for Saturday's [harness](harness.md), [run-agent-turn](run-agent-turn.md), [inbound-gate](inbound-gate.md), and [click-path](click-path.md). It adds no test and it ticks no box. Those files are still written only when their boxes are being ticked.

Sources, read and left in place:

- `C:\Users\tseli\source\python\procure.agents` — the engine. `procure_flow/whatsapp/services/messaging.py`, `procure_flow/whatsapp/router.py`, and the supplier-search workflow that finishes on a background thread.
- `C:\Users\tseli\source\python\procure.agents.whatsapp` — the page. `tester/server.py`, `tester/index.html`, and `tester/src/`.

QuoteDesk already chose the same split the spec names: Cloud API payloads in, outbox out, one engine for the harness and the judge chat. Thursday's outbox is `quotedesk/adapters/outbound/channels/outbox.py`. It stores `body` and `status` in the process, in append order, and it does not drain. This note says how the other project made that split look like a conversation, and which of its choices would make Saturday's click-path feel like a test tool.

## The rule that made their chat look real

Every sentence the customer could see was queued for the page, including sentences produced after the webhook had already returned.

`send_whatsapp_message` is the only send. With `TEST_MODE` it appends `{body, media_url?}` to an in-memory list keyed by phone. Without it, the same function calls Twilio. The page never paints the webhook HTTP body. It polls `GET /whatsapp/messages?from=<phone>` and appends one bubble per queued item.

That second part is what the long jobs needed. Supplier search returns `"File received. I'm reading it now"` on the webhook, starts a thread, and later calls `send_whatsapp_message` with the summary or the Excel. The page is already polling, so the later sentence appears in the thread as a new bubble. The webhook response is not the conversation.

QuoteDesk's turn loop is the same shape. `ReceiveInboundEvent` returns before `RunAgentTurn`. The video acknowledgement is one outbox row. The quote is a later row. The page has to be listening before the first row exists, and it has to draw each row as its own bubble.

## What their page got wrong

These are the reasons that tester feels like a harness with bubbles. Saturday's chat leaves each one behind.

| What they did | What the judge would see | Saturday rule |
| --- | --- | --- |
| Poll every 2000 ms | A reply sits finished on the server for up to two seconds, then pops in | The page reads the outbox on load and again every 300 ms while the tab is visible. A hidden tab pauses. |
| `drain_messages` deletes the queue on read | A dropped response, a second tab, or the harness and the page together lose the reply | Reads are not destructive. Thursday's `pending()` stays. The page passes `after`. |
| Composer `disabled` for the whole webhook POST | The customer cannot send the next photo while the first is in flight | The composer stays enabled. The week plan already requires this while a video is being read. |
| Typing dots tied to that POST | The dots vanish when the webhook returns, which is before the real answer exists | Dots start in the same paint as the user bubble and stay until an outbox row for that turn arrives. |
| Both UIs render `body` and drop `media_url` | The Excel was queued and never shown | A URL in the body that is this app's quote card becomes a control. A `media_url` that arrives is rendered in that bubble. |
| WhatsApp glyph, "Listening for agent messages", HTTP status on the bubble, raw-payload drawer | Tester chrome in the thread | The thread shows the business name, the bubbles, and the card. No WhatsApp logo and no Meta logo. HTTP detail stays out of the thread. |
| Twilio form fields (`From`, `Body`, `MediaUrl0`) | A second inbound dialect beside the real webhook | The page posts the same Cloud API JSON as `tests/fixtures/whatsapp/text_message.json`. The harness and the page share one parser. |
| In-memory queue, one dict per process | A second worker has an empty queue, so the page polls forever | The demo runs one worker. The outbox lives in that process. A second worker is a blank chat. |
| `*reset*` appended to every outbound body | A footer on every bubble | Customer copy is the sentence the use case wrote. The sender does not decorate it. |

## One pipe

```text
page or harness
  POST /whatsapp/webhook     Cloud API JSON, one event
  GET  /whatsapp/outbox      rows in append order

webhook
  ReceiveInboundEvent
  200, empty body
  gate sentence, when there is one, is an outbox row

worker
  quiet window, then RunAgentTurn
  ChannelSender writes the outbox after the commitment check
  "Got your video, having a look." is its own row, written before the final answer
```

The page paints the customer's own bubble locally, at the moment of send. It does not wait for the server to echo it, and it does not paint anything from the POST body. Agent bubbles come only from the outbox. That is how a gate refusal, a video acknowledgement, and a quote reply stay one visual language, and how a poisoned draft that never reaches the outbox never reaches the screen.

`GET /whatsapp/outbox` with no query returns every pending row, in append order. That is the harness read already named in the Saturday plan. The page calls the same path with `wa_id` and `after`. `after` is the last row id the page has drawn. Two tabs with two `wa_id` values do not mix. The harness test that posts one payload and reads the outbox keeps working without the query.

Thursday's `OutboxMessage` has `body` and `status`. The harness design is the place that adds a monotonic `id` and the `wa_id` the row was sent to. `pending()` still returns the full append-ordered tuple. Nothing in the outbox calls the network.

## Cloud host, local page

Their tester and their engine were different processes, and sometimes the engine was in Docker or on another host. Three details made that work.

1. The browser talked only to the page's origin. `tester/server.py` proxied `POST /whatsapp/webhook` and `GET /whatsapp/*` to `BACKEND_URL`. The page did not need CORS on the engine.
2. An upload was stored on the tester and the webhook carried a URL, not the bytes. Twilio works the same way. `PUBLIC_BASE_URL` replaced `localhost` when the engine could not fetch the tester's loopback. A Docker engine fetching `http://localhost:3000/uploads/...` fails.
3. Outbound files were the mirror. The engine stored bytes under a short-lived token and put that URL on the queued message. The page's origin could fetch it. Their UIs then ignored the URL. The queue was right and the bubble was incomplete.

QuoteDesk owns both sides, so the Saturday demo is one origin. The FastAPI app serves the page, accepts the upload into the media store, and accepts the Cloud API webhook whose media id points at that object. The page shows the photo from the local file immediately, then posts. The engine never has to fetch the browser's localhost.

Keep the proxy pattern for the day the engine is a cloud URL and the page is not on it. `BACKEND_URL` is the engine. Upload URLs use a host that engine can resolve. Bytes stay out of the webhook body. The payload shape stays the Cloud API fixture.

## How the page should feel

The click-path is the first time a person sees this. The shell built on Saturday is the shell Sunday's chat states sit on. Sunday adds the gate, handover, and slow-media presentations. It does not replace the thread.

Paint:

- The user bubble is on screen in the same turn as the keypress, including a photo taken from the local file. Upload and webhook run behind that paint.
- The typing row is a fixed height, so the thread does not jump when it appears. It shows for the quiet window and the turn. The video sentence, once it arrives, is a bubble. The dots return after it until the later reply, because that reply is a later turn.
- Several rows in one poll draw as separate bubbles, 140 ms apart, in append order. Rows that arrived together do not grow a fake pause between them beyond that.
- The thread follows the bottom when the reader is already within 80 px of it. Otherwise it leaves them where they are and offers a way back down. Opening the card link must not yank the transcript.
- Enter sends. Shift+Enter inserts a line. The composer keeps focus, grows to four lines, and accepts a pasted image. It is never disabled.
- A failed POST marks that bubble "Not sent" and retries the same provider message id. A success has no status badge. Provider timestamps are the inbound order the domain already stores. The page does not reorder a bubble it has already shown.
- A quote URL in the reply is a control labelled with the card headline the tool returned, and it opens the card. The commitment checker already requires the link in the text. The control is how the click-path's "open the card" step happens without a raw URL as the sentence.
- Images reserve their box before they load. A voice file is a row with its duration. The Saturday path may send the transcript as text when live transcription is unwired. The photo still goes up as a photo.
- Empty thread: the business name and one line, "Send a message to AquaSure." Waiting copy that the customer sees is a bubble or the dots, and a waiting bubble uses a sentence the week plan already fixed.
- 375 px is one column. 1280 px is that column centred, about 720 px wide. The card stays the printable page it already is.
- Timestamps are Johannesburg local, the same rule as the card. Money in a bubble is the tool's amount, displayed as the card displays it.

Identity for the demo is one customer, stable `wa_id`, pinned for AquaSure. A second conversation is a different `wa_id` on the outbox query. The judge path has no settings panel.

## What Saturday's design files take from this

**harness.md.** The runner and the page post one Cloud API payload per event and read `GET /whatsapp/outbox`. The webhook body is empty of customer text. The outbox gains `id` and `wa_id`. Reads do not delete rows.

**inbound-gate.md and run-agent-turn.md.** A gate sentence, the video acknowledgement, and the checked reply are outbox rows. The checker still does not write the outbox. `RunAgentTurn` does, after the check. A draft that fails the check is absent from the outbox and absent from the thread.

**click-path.md.** The page implements the paint rules above, on the same routes the harness uses. One worker. No logo, no tester chrome, composer enabled, card control in the bubble.

## Left where it is

Menus, workflow steps, TwiML, Twilio form posts, the reset footer, the WhatsApp glyph, the two-second poll, and the destructive queue stay in the other repos. QuoteDesk's conversation has no menu and no step field. This note does not change `decide`, `price`, the commitment checker cases, or the fixed customer sentences.
