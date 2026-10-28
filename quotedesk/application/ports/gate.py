from typing import Protocol
from uuid import UUID

from quotedesk.application.dto.inbound import InboundMessage, MediaCategory


class ChannelSender(Protocol):
    def send(self, wa_id: str, body: str) -> None: ...


class MediaStore(Protocol):
    def put(self, tenant_id: UUID, message_id: str, mime: str, size_bytes: int) -> None: ...


class MediaClassifier(Protocol):
    def classify(self, data: InboundMessage) -> MediaCategory: ...
