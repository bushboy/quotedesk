from fastapi import FastAPI

from quotedesk.adapters.inbound.http.quote_card import router as quote_card_router
from quotedesk.infrastructure.config import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    if settings is None:
        settings = get_settings()
    app = FastAPI(title="QuoteDesk")
    app.state.settings = settings

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(quote_card_router)
    return app
