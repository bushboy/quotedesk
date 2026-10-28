from typing import Protocol

from quotedesk.application.dto.agent import ExtractionResult


class MediaEnricher(Protocol):
    def for_image(self, provider_message_id: str) -> ExtractionResult | None: ...
