import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI

from quotedesk.adapters.inbound.http.card import router as card_router
from quotedesk.adapters.inbound.http.chat import SimulatedMedia
from quotedesk.adapters.inbound.http.chat import router as chat_router
from quotedesk.adapters.inbound.http.quote_card import router as quote_card_router
from quotedesk.adapters.inbound.http.whatsapp import router as whatsapp_router
from quotedesk.infrastructure.config import Settings, get_settings
from quotedesk.infrastructure.demo import QuoteScript, install, published_bundle

_TICK_SECONDS = 0.25
_log = logging.getLogger(__name__)


def _sender(settings: Settings):
    """The ChannelSender. `None` is the in-process outbox the chat page and harness read.

    A real provider goes here, e.g. a Cloud API or Twilio sender selected by `settings.channel`.
    """
    if settings.channel == "outbox":
        return None
    raise ValueError(f"Unknown channel {settings.channel!r}.")


@asynccontextmanager
async def _worker(app: FastAPI):
    """Run the turn loop after each quiet window, independent of any request."""
    stop = threading.Event()

    def loop() -> None:
        while not stop.wait(_TICK_SECONDS):
            try:
                app.state.run_turn()
            except Exception:
                _log.exception("Turn failed.")

    thread = threading.Thread(target=loop, name="turn-worker", daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=2)


def create_app(settings: Settings | None = None) -> FastAPI:
    if settings is None:
        settings = get_settings()
    app = FastAPI(title="QuoteDesk", lifespan=_worker)
    app.state.settings = settings
    app.state.sim_media = SimulatedMedia()

    def reset() -> None:
        install(
            app,
            published_bundle(),
            model=QuoteScript(),
            card_base="/card",
            card_code="1042",
            sender=_sender(settings),
            live=True,
        )

    reset()
    app.state.reset = reset

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(quote_card_router)
    app.include_router(whatsapp_router)
    app.include_router(card_router)
    app.include_router(chat_router)
    return app
