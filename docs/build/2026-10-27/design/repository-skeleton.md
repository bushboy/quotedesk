# Repository skeleton

Written 27 October 2026. The daytime scaffold implements this note. Domain types do not.

## Layout

Empty packages exist so later slices have a home. Each directory below has an `__init__.py`. Modules named in the architecture that are not in the "modules today" list stay absent until their slice.

```text
quotedesk/
  domain/
    shared/
    quotes/
    policy/
    case/
    conversation/
    services/
  application/
    ports/
    dto/
    use_cases/
      conversation/
      tools/
      operator/
      editor/
      imports/
      evaluation/
  adapters/
    inbound/
      http/
      agent_tools/
    outbound/
      models/meta/
      models/baseten/
      persistence/
      channels/
      parsers/
      payments/
      storage/
  infrastructure/
tests/
  unit/domain/
  use_cases/
  adapters/
  e2e/
  fixtures/quote_card/
seeds/
harness/scenarios/
harness/media/
eval/photo_cases/
eval/results/
```

## Modules today

| Module | Behaviour |
| --- | --- |
| `quotedesk/infrastructure/config.py` | Settings from the environment. |
| `quotedesk/infrastructure/main.py` | Uvicorn entry. Calls the composition root. Does not build the app at import time. |
| `quotedesk/infrastructure/container.py` | The only module that imports a concrete adapter. Wires health and the quote-card preview. |
| `quotedesk/infrastructure/db.py` | Docstring only. Does not open a connection. |
| `quotedesk/infrastructure/workers.py` | Docstring only. Does not start a loop. |
| `quotedesk/adapters/inbound/http/quote_card.py` | Preview route from [quote-card-states.md](quote-card-states.md). |

No other adapter is imported. No table is created. SQLAlchemy, Alembic, and a database driver are not dependencies today.

## Settings

`Settings` is a Pydantic settings model in `quotedesk.infrastructure.config`.

| Field | Rule |
| --- | --- |
| `database_url` | Required string. Environment name `DATABASE_URL`. No default. |

`get_settings()` reads the process environment. A missing `DATABASE_URL` raises `quotedesk.infrastructure.config.SettingsError` with the sentence `DATABASE_URL is required.` Startup uses `get_settings()` and so fails closed.

`create_app(settings)` takes a `Settings` instance. The health test passes one in and does not need a running database. `create_app()` with no argument loads settings from the environment.

`.env.example` contains only the local Compose URL:

```text
DATABASE_URL=postgresql+psycopg://quotedesk:quotedesk@localhost:5432/quotedesk
```

That URL is the local development database. It is not a deployed secret. `.gitignore` ignores `.env`, `__pycache__/`, `.venv/`, and `.pytest_cache/`.

## Health

`GET /health` returns 200 and `{"status": "ok"}`. The handler does not open a database connection and does not require a row.

Uvicorn factory: `quotedesk.infrastructure.main:create_app`.

## Import contracts

`.importlinter` uses root package `quotedesk`.

Layers, listed from outer to inner. A layer may import the layers below it.

```text
quotedesk.infrastructure
quotedesk.adapters
quotedesk.application
quotedesk.domain
```

A second contract forbids these modules from importing `quotedesk.adapters`:

- `quotedesk.infrastructure.main`
- `quotedesk.infrastructure.config`
- `quotedesk.infrastructure.db`
- `quotedesk.infrastructure.workers`

`quotedesk.infrastructure.container` is the exception. Domain may import the standard library and Pydantic, and may not import `application`, `adapters`, or `infrastructure`.

## Compose and licence

`docker-compose.yml` runs PostgreSQL 16 only, database `quotedesk`, user `quotedesk`, password `quotedesk`, published on port 5432. The API runs on the host.

`LICENSE` is the GNU Affero General Public License v3.0. The copyright line is `Copyright (C) 2026 The QuoteDesk authors`.

`pyproject.toml` targets Python 3.12. Tuesday dependencies are FastAPI, Uvicorn, Pydantic v2, pydantic-settings, pytest, httpx, and import-linter.

## Tag

`hackathon-start` is applied to the first commit that contains `LICENSE` and `quotedesk/infrastructure/main.py`.
