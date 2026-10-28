# Click-path

Written 31 October 2026. The AquaSure chat page and `seeds/aquasure.yaml` implement this note and nothing beyond it.

The simulator note is the paint rule. The page posts the Cloud API fixture and reads the outbox. It does not paint the webhook body. Live Spark, live SAM, and live Voice Transcribe stay parked. `decide` is not changed.

## Seed

`seeds/aquasure.yaml` loads to the same policy version, the same rule ids, and the same templates as `tests/unit/domain/water_policy.py`. The loader is `quotedesk.adapters.outbound.parsers.aquasure.load_policy`. Running the Wednesday cases through the loaded policy returns those rule ids.

## Page

`GET /chat` is the AquaSure thread. The business name is AquaSure. The empty line is "Send a message to AquaSure." There is no WhatsApp logo and no Meta logo. The composer is never disabled. Enter sends. Shift+Enter inserts a line.

The page paints the customer bubble, including the tank photo, in the same turn as Send. It then posts one Cloud API payload to `POST /whatsapp/webhook`. The response body is not drawn. Agent bubbles come from `GET /whatsapp/outbox?wa_id=15550002222&after=<id>` every 300 ms. Reads do not delete rows.

The typed transcript is the path when live transcription is not wired. The voice file and the tank photo are on disk at `seeds/media/5000l-voice.wav` and `seeds/media/tank-on-base.png`. The photo in the bubble is that file.

## Reply and card

The scripted turn calls `UpdateCase` and `GetQuote`. The outbox sentence contains `R 4 250` and the card URL, and no second rand amount. The URL is `/card/QD-1042?code=1042`.

`GET /card/QD-1042` calls `GetQuoteStatus`. A missing or wrong code renders no card. The right code renders the existing quote-card template: "Fixed quote", the 5000 L line, the clauses, rule id WATER-F01, the mask image, and the expiry. Refresh loads the same version from `GetQuoteStatus`.

The mask is the file on disk. It is not a live segmentation.
