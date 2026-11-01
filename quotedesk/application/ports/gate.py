"""The channel ports. The receive path sends a reply, stores media, and classifies an image."""

from typing import Protocol
from uuid import UUID

from quotedesk.application.dto.inbound import InboundMessage, MediaCategory


class ChannelSender(Protocol):
    """The port for ChannelSender."""
    def send(self, wa_id: str, body: str, *, buttons: tuple[str, ...] = (), image_url: str | None = None) -> None: ...


class MediaStore(Protocol):
    """The port for MediaStore."""
    def put(self, tenant_id: UUID, message_id: str, mime: str, size_bytes: int) -> None: ...


class MediaClassifier(Protocol):
    """The port for MediaClassifier."""
    def classify(self, data: InboundMessage) -> MediaCategory: ...
