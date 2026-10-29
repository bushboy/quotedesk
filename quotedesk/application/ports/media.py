from typing import Protocol

from quotedesk.application.dto.agent import ExtractionResult


class ImageHost(Protocol):
    """Where an image's bytes live. The turn never sees them."""

    def get(self, media_id: str) -> tuple[str, bytes] | None: ...


class MediaEnricher(Protocol):
    def for_image(self, provider_message_id: str) -> ExtractionResult | None: ...
