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

`DATABASE_URL` has to be set or the process refuses to start. The conversation stays in memory. Startup reads the `tenant` table when Postgres is up, and otherwise uses the built-in AquaSure and FrameWorks rows. `TENANT` is `aquasure` or `frameworks`. It defaults to `aquasure`. One process is one business. `.env.example` lists every setting. Copying that file does not load it for a shell. The shell that starts uvicorn has to export the variables. `.env` stays uncommitted. Docker Compose does load `.env` into the app container. The compose file still sets `DATABASE_URL`, so the container does not use the `127.0.0.1` address from that file.

Open http://127.0.0.1:8000/chat. http://127.0.0.1:8000/health returns `{"status":"ok"}`.

With `MODEL=spark`, each turn asks the host in `AGENT_PROVIDER`. The reply is that model's, after the tools run. A price, a date, an inclusion, or a guarantee still has to come from a tool. The card for the 5000 L fixture opens only with code `1042`. Refresh loads the same version. **Clear chat** in the menu calls `POST /sim/reset` and starts that conversation again.

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

The two providers are independent. The reply can come from Baseten while the photo still goes to Meta. A side left on `meta` still needs the Meta key and `SPARK_MODEL_ID`.

A photo is read once. A second call on those same bytes asks for segments, and that call uses `IMAGE_PROVIDER` as well. Voice Transcribe is not called. There is no separate setting for Segment Anything.

Startup logs the live choice, for example `Model agent provider=meta id=muse-spark-1.3 image provider=baseten id=...`. `MODEL=script` logs `Model script`.

The page posts Cloud API JSON to `POST /whatsapp/webhook` and paints agent bubbles from `GET /whatsapp/outbox`. The webhook body is not drawn. Uploads go to `POST /sim/media`. The webhook carries a media id, not the file bytes. Reads of the outbox do not delete rows.

`GET /dev/quote-card/{state}` renders the checked-in card fixtures. There is no operator console and no policy editor in the running app.

## Where to change things

```text
quotedesk/domain/            commercial rules. Standard library and Pydantic only.
quotedesk/application/       one use case per action, plus the ports and DTOs it needs.
quotedesk/adapters/          HTTP, the chat page, parsers, persistence.
quotedesk/infrastructure/    settings, the app factory, and container.py, the composition root.
seeds/                       aquasure.yaml is what the app loads. frameworks.yaml is the fabricator policy.
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

`docker compose up --build` starts the app and uses the PostgreSQL already installed on this machine. The container reaches it at `host.docker.internal` on port 5432. That server needs database `quotedesk`, user `quotedesk`, and password `quotedesk`, which is the URL in `.env.example`. The app container also receives `MODEL`, `AGENT_PROVIDER`, `IMAGE_PROVIDER`, the keys those providers need, and `TENANT` from `.env`.

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

`alembic.ini` uses the same local URL as `.env.example`. Those two tests apply the migrations themselves when the database is up.

## What this build simulates

The customer channel is the web chat. `GET /whatsapp/webhook` answers Meta's verification handshake when `WHATSAPP_VERIFY_TOKEN` is set. `WHATSAPP_APP_SECRET` turns on the `X-Hub-Signature-256` check. With that secret set, the chat page's unsigned posts are rejected. Outbound delivery is the in-process outbox. `CHANNEL` accepts `outbox` only.

`seeds/frameworks.yaml` is loaded by tests. The running app loads `seeds/aquasure.yaml` only. With `MODEL=spark`, the chat uses `AGENT_PROVIDER` and a photo uses `IMAGE_PROVIDER`, as in [Model settings](#model-settings). With `MODEL=script`, both stay on the fixed reply and the recorded photo. Voice Transcribe is not called yet. Excel import, approval, and publish exist as use cases. They are not pages. Word, PowerPoint, PDF, and photo import are not in this build. Deposit links, where a use case returns one, are sandbox URLs.

There is no evaluation runner yet. The planned set and the metrics are in the build spec. Do not treat an unrun case as a result.

## Licence

GNU Affero General Public License v3.0 (`LICENSE`).

The build uses Cursor. The author holds the rights to the code, the fictional tenant data, and the test media. Names, rate cards, and customers in this repository are fictional.
