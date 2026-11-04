# QuoteDesk

QuoteDesk is a conversational quoting agent for South African trade businesses. A customer writes, speaks, or sends a photo. Domain code decides whether the business may promise a fixed price, a range, a site visit, or no price. The model does not set a price, grant a discount, or change a quote's state.

The running app is a web chat for one business at a time, AquaSure or FrameWorks. It speaks WhatsApp Cloud API payloads and keeps replies in an in-memory outbox. It does not connect a WhatsApp Business number. `MODEL`, below, chooses whether a turn calls a live model.

Product scope, the two tenants, and the policy rules are in [docs/design/QuoteDesk_Hackathon_Build_Spec.md](docs/design/QuoteDesk_Hackathon_Build_Spec.md). Layer rules are in [docs/design/QuoteDesk_Clean_Architecture.md](docs/design/QuoteDesk_Clean_Architecture.md). The day-by-day build is in [docs/build/QuoteDesk_Build_Plan.md](docs/build/QuoteDesk_Build_Plan.md).

## Run the chat

Python 3.12 or newer. From the repository root:

```powershell
python -m pip install -e ".[dev]"
$env:DATABASE_URL = "postgresql+psycopg://quotedesk:quotedesk@127.0.0.1:5432/quotedesk"
python -m uvicorn quotedesk.infrastructure.main:create_app --factory --host 127.0.0.1 --port 8000
```

Bash:

```bash
python -m pip install -e ".[dev]"
export DATABASE_URL="postgresql+psycopg://quotedesk:quotedesk@127.0.0.1:5432/quotedesk"
python -m uvicorn quotedesk.infrastructure.main:create_app --factory --host 127.0.0.1 --port 8000
```

`DATABASE_URL` has to be set or the process refuses to start. `STORE` is `postgres` or `memory`. It defaults to `postgres`. Postgres stores the conversation, the case, and the quotes. Startup reads the `tenant` table. A missing row uses the built-in AquaSure or FrameWorks profile. A closed database leaves the store down: `/chat`, `/console`, and the webhook return 503, and `/health` returns `{"status":"unavailable","store":"down"}`. `STORE=memory` keeps that state in the process. `/health` then returns `{"status":"ok","store":"memory"}`. With Postgres up it returns `{"status":"ok","store":"postgres"}`. `TENANT` is `aquasure` or `frameworks`. It defaults to `aquasure`. One process is one business. `.env.example` lists every setting. Copying that file does not load it for a shell. The shell that starts uvicorn has to export the variables. `.env` stays uncommitted. Docker Compose does load `.env` into the app container. The compose file still sets `DATABASE_URL`, so the container does not use the `127.0.0.1` address from that file.

Open http://127.0.0.1:8000/chat. `/` redirects there.

With `MODEL=spark`, each turn asks the host in `AGENT_PROVIDER`. The reply is that model's, after the tools run. A price, a date, an inclusion, or a guarantee still has to come from a tool. The first quote number is `QD-1042`. The card opens with the four-digit code issued for that quote. Refresh loads the same version. **Reset session** in the menu calls `POST /sim/reset-number` and clears every session for that number. Other numbers stay.

## Model settings

Three keys decide who answers. `MODEL` chooses whether a live model runs. The other two choose the host for each live call, and they apply only when `MODEL` is `spark`.

`MODEL` is `script` or `spark`. It defaults to `spark`.

- `spark` runs a live model for the WhatsApp reply and for a photo.
- `script` uses a fixed reply and a recorded photo. `AGENT_PROVIDER` and `IMAGE_PROVIDER` are ignored, and the process does not need a Meta or Baseten key.

`AGENT_PROVIDER` is `meta` or `baseten`. It defaults to `meta`. It chooses the host for the WhatsApp reply: the model that reads the conversation and calls tools.

- `meta` uses `SPARK_MODEL_ID` at `META_BASE_URL`. That needs `META_API_KEY`. `META_BASE_URL` defaults to `https://api.meta.ai/v1`. `.env.example` sets `SPARK_MODEL_ID` to `muse-spark-1.3`.
- `baseten` uses `BASETEN_MODEL_ID` at `BASETEN_BASE_URL`. That needs `BASETEN_API_KEY`. `BASETEN_BASE_URL` defaults to `https://inference.baseten.co/v1`.

`IMAGE_PROVIDER` is `meta` or `baseten`. It defaults to `meta`. It chooses the host for a photo.

- `meta` reads the photo with `SPARK_MODEL_ID` and needs `META_API_KEY`.
- `baseten` reads the photo with `BASETEN_IMAGE_MODEL_ID`. When that value is empty, the photo uses `BASETEN_MODEL_ID`.

The two providers are independent. The reply can come from Baseten while the photo description still goes to Meta. A side left on `meta` still needs `SPARK_MODEL_ID`. `MODEL=spark` always needs `META_API_KEY`, because segmentation runs on SAM.

A photo is read once, on `IMAGE_PROVIDER`. Each object name from that read is then one concept prompt to Segment Anything Model 3.1 (`sam-3.1`) on the Meta API, with the same image bytes. That call uses `META_API_KEY` and `META_BASE_URL`, including when the description uses Baseten. `SAM_MODEL_ID` overrides the model id and defaults to `sam-3.1`. The score on each mask is what caps agreement.

Voice notes are transcribed when `MUSE_BASE_URL` is set. The model id is `MUSE_MODEL_ID`, which defaults to `muse-voice`, and the call uses `MUSE_API_KEY`. Audio is posted to `{MUSE_BASE_URL}/audio/transcriptions`. An empty `MUSE_BASE_URL` leaves the transcript that arrived with the message. A failed or empty transcript asks the customer to type.

`CARPORT_PICTURE` is `on` or `off`. It defaults to `off`. `on` builds a Muse Image client for FrameWorks when `META_API_KEY` is set. The model id is `PICTURE_MODEL_ID`, which defaults to `muse-image-1.0`.

Startup logs the live choice, for example `Model agent provider=meta id=muse-spark-1.3 image provider=baseten id=... sam=sam-3.1`. `MODEL=script` logs `Model script`.

The page posts Cloud API JSON to `POST /whatsapp/webhook` and paints agent bubbles from `GET /whatsapp/outbox`. The webhook body is not drawn. Uploads go to `POST /sim/media`. The webhook carries a media id, not the file bytes. Reads of the outbox do not delete rows.

`GET /dev/quote-card/{state}` renders the checked-in card fixtures. The owner console is `/console`.

## Where to change things

```text
quotedesk/domain/            commercial rules. Standard library and Pydantic only.
quotedesk/application/       one use case per action, plus the ports and DTOs it needs.
quotedesk/adapters/          HTTP, the chat page, parsers, persistence.
quotedesk/infrastructure/    settings, the app factory, and container.py, the composition root.
seeds/                       aquasure.yaml and frameworks.yaml, one built-in policy per business.
harness/                     scenario files and the runner.
tests/unit/                  domain.
tests/use_cases/             use cases with in-memory fakes.
tests/adapters/              HTTP, the harness, and the database.
docs/design/                 product spec and architecture.
docs/build/                  the working plan and the design note for each slice.
```

`application` does not import `adapters` or `infrastructure`. Only `quotedesk/infrastructure/container.py` wires concrete adapters. `lint-imports` checks that.

The chat page is `quotedesk/adapters/inbound/http/templates/chat.html` and `quotedesk/adapters/inbound/http/chat.py`. It posts to the webhook. It does not call a use case.

A design for a slice lives under `docs/build/` next to that day's plan. Tests for that slice follow the design. The architecture note describes the intended packages. The tree above is what is checked in.

## Tests

Domain and use-case tests use fakes. They do not call a model and they do not need PostgreSQL.

```bash
pytest tests/unit tests/use_cases tests/adapters --ignore=tests/adapters/test_quote_tables.py --ignore=tests/adapters/test_rls.py
lint-imports
```

`tests/adapters/test_quote_tables.py` and `tests/adapters/test_rls.py` open PostgreSQL. Run them after the database section below. They fail if that database is down. The rest of the suite does not.

The harness checks are in-process. They do not need the server running, and they do not send to WhatsApp.

```bash
pytest tests/adapters/test_harness.py tests/adapters/test_whatsapp_fixture.py -q
```

## Run with Docker

`docker compose up --build` starts the app and uses the PostgreSQL already installed on this machine. The container reaches it at `host.docker.internal` on port 5432. That server needs database `quotedesk`, user `quotedesk`, and password `quotedesk`, which is the URL in `.env.example`. The app container also receives `MODEL`, `AGENT_PROVIDER`, `IMAGE_PROVIDER`, `SAM_MODEL_ID`, the keys those providers need, and `TENANT` from `.env`.

```bash
docker compose up --build
```

Open http://127.0.0.1:8000/chat.

`docker compose -f docker-compose.postgres.yml up --build` starts the app and pulls a PostgreSQL 16 container. Use that file when this machine has no Postgres of its own. It publishes port 5432, so stop a local server that already owns that port before starting it.

Apply the schema from the app container. For the local database:

```bash
docker compose run --rm app alembic upgrade head
```

For the Postgres container:

```bash
docker compose -f docker-compose.postgres.yml run --rm app alembic upgrade head
```

## Database

PostgreSQL 16 is for the migrations and for `tests/adapters/test_quote_tables.py` and `tests/adapters/test_rls.py`. From the host, with the local server or the Postgres container listening on port 5432:

```bash
alembic upgrade head
```

`alembic.ini` uses the same local URL as `.env.example`. Those two tests apply the migrations themselves when the database is up. They need `quotedesk` to be an ordinary role: a superuser skips row-level security.

The published rate card lives in the `rate_card` and `rate_card_item` tables. `rate_card_item.applies_to` is `both`, `swap`, or `new`, and it defaults to `both`. The migration seeds the AquaSure and FrameWorks prices. Startup reads them, and a publish from the Policy section of `/console` writes the row, including `applies_to`. A closed database makes `/chat` and `/console` return 503, so a publish does not run. `STORE=memory` uses the built-in prices, and a publish lasts until restart. `tests/adapters/test_rate_card_tables.py` skips itself when nothing listens on port 5432.

## What this build simulates

The customer channel is the web chat. The webhook can check Meta's verification handshake and `X-Hub-Signature-256`, but `get_settings` does not read `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_APP_SECRET`, or `CHANNEL`. A shell export of those names does not change the process. Outbound delivery stays the in-process outbox.

`TENANT=frameworks` loads `seeds/frameworks.yaml`. `TENANT=aquasure` loads `seeds/aquasure.yaml`. With `MODEL=spark`, the chat uses `AGENT_PROVIDER` and a photo uses `IMAGE_PROVIDER`, as in [Model settings](#model-settings). With `MODEL=script`, both stay on the fixed reply and the recorded photo. Voice notes follow that same section. The Policy page on `/console` imports a CSV or Excel price list into the draft. Approval, publish, and rate card edits are on `/console`. The Policy draft shows the unit, the role, and whether the row applies to a swap, a new installation, or both. A swap quotes the material. A new installation adds the published frame and installation rows. The built-in cards have none of those rows, so a new installation on a fresh database is the material price until the owner publishes them. Word, PowerPoint, and PDF import are not in this build. A customer photo is the chat upload. Deposit links, where a use case returns one, are sandbox URLs.

`python -m eval.run_gate` runs the release set: 27 scripted conversations for AquaSure and 27 for FrameWorks. The customer is a scripted voice behind the model port. The wording changes with the seed. The expected outcome does not, except where this build retargeted a conversation: `frame-new-opening` now expects a quote under `FAB-F02`. `aqua-new-system-sized` and `aqua-range-10000` stay quotes and now expect `WATER-F02`. A widened opening still expects `FAB-S01`. A sized replacement still expects `WATER-F01`. The command does not call a live model, so it does not replace `eval/results/latency.json`.

Recorded run, 1 November 2026, seed 0, in `eval/results/gate.json`:

| Business | Conversations | Outcome accuracy | Questions before the outcome | No reply | Unfounded commitments | Re-asked facts | Brief completeness | Median | Slowest 10% | Cost |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| AquaSure | 27 | 1.0 | 0.3 | 0 | 0 | 0 | 1.0 | 0.002s | 0.005s | 0 |
| FrameWorks | 27 | 1.0 | 0.37 | 0 | 0 | 0 | 1.0 | 0.002s | 0.005s | 0 |

That is one passing run. A live WhatsApp number needs three passing runs in a row, so neither business is given one. Oakmere Doors has a set in `eval/conversations/oakmere.yaml` and is not served: no prices, no tenant, no number. The small set of ten per business remains in `eval/results/small-set.json`.

## Licence

GNU Affero General Public License v3.0 (`LICENSE`).

The build uses Cursor. The author holds the rights to the code, the fictional tenant data, and the test media. Names, rate cards, and customers in this repository are fictional.
