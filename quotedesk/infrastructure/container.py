import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI

from quotedesk.adapters.inbound.http.card import router as card_router
from quotedesk.adapters.inbound.http.chat import SimulatedMedia
from quotedesk.adapters.inbound.http.chat import router as chat_router
from quotedesk.adapters.inbound.http.console import router as console_router
from quotedesk.adapters.inbound.http.editor import router as editor_router
from quotedesk.adapters.inbound.http.quote_card import router as quote_card_router
from quotedesk.adapters.inbound.http.whatsapp import router as whatsapp_router
from quotedesk.adapters.outbound.models.image_context import ImageEnricher
from quotedesk.adapters.outbound.models.recorded_extraction import RecordedEnricher
from quotedesk.adapters.outbound.models.spark import SdkTransport, SparkTurn
from quotedesk.infrastructure.config import Settings, get_settings
from quotedesk.infrastructure.demo import QuoteScript, bundle_for, install, with_rate_card
from quotedesk.infrastructure.rate_cards import StoredRateCards
from quotedesk.infrastructure.tenants import resolve_tenant

_TICK_SECONDS = 0.25
_log = logging.getLogger(__name__)


def _configure_logging() -> None:
    """Show webhook, handler, model, and front-end lines under uvicorn and Docker."""
    log = logging.getLogger("quotedesk")
    if log.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    log.propagate = False


def _model(settings: Settings):
    if settings.model == "script":
        return QuoteScript()
    if settings.agent_provider == "baseten":
        return SparkTurn(
            model_id=settings.baseten_model_id,
            base_url=settings.baseten_base_url,
            transport=SdkTransport(settings.baseten_api_key),
        )
    return SparkTurn(
        model_id=settings.spark_model_id,
        base_url=settings.meta_base_url,
        transport=SdkTransport(settings.meta_api_key),
    )


def _enricher(settings: Settings, host):
    if settings.model != "spark":
        return RecordedEnricher()
    if settings.image_provider == "baseten":
        return ImageEnricher(
            host=host,
            transport=SdkTransport(settings.baseten_api_key),
            model_id=settings.baseten_image_model_id,
            base_url=settings.baseten_base_url,
        )
    return ImageEnricher(
        host=host,
        transport=SdkTransport(settings.meta_api_key),
        model_id=settings.spark_model_id,
        base_url=settings.meta_base_url,
    )


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
    _configure_logging()
    if settings is None:
        settings = get_settings()
    app = FastAPI(title="QuoteDesk", lifespan=_worker)
    app.state.settings = settings
    app.state.sim_media = SimulatedMedia()
    profile, source = resolve_tenant(settings.database_url, settings.tenant)
    _log.info(
        "Active tenant slug=%s id=%s name=%s source=%s",
        profile.slug,
        profile.tenant_id,
        profile.display_name,
        source,
    )
    if settings.model == "script":
        _log.info("Model script")
    else:
        _log.info(
            "Model agent provider=%s id=%s image provider=%s id=%s",
            settings.agent_provider,
            settings.baseten_model_id if settings.agent_provider == "baseten" else settings.spark_model_id,
            settings.image_provider,
            settings.baseten_image_model_id if settings.image_provider == "baseten" else settings.spark_model_id,
        )

    rate_cards = StoredRateCards(settings.database_url)

    def reset() -> None:
        install(
            app,
            with_rate_card(bundle_for(profile.slug), rate_cards.load(profile.tenant_id)),
            model=_model(settings),
            card_base="/card",
            card_code="1042",
            sender=_sender(settings),
            live=True,
            enricher=_enricher(settings, app.state.sim_media),
            tenant=profile,
            rate_cards=rate_cards,
        )
        app.state.rate_cards = rate_cards

    reset()
    app.state.reset = reset

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(quote_card_router)
    app.include_router(whatsapp_router)
    app.include_router(card_router)
    app.include_router(chat_router)
    app.include_router(console_router)
    app.include_router(editor_router)
    return app
