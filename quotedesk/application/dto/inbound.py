"""The inbound DTOs. The receive path takes a message and returns whether it was stored."""

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

InboundKind = Literal["text", "image", "audio", "video"]
MediaCategory = Literal["ordinary", "explicit", "sensitive_document"]


class InboundMessage(BaseModel):
    """The InboundMessage."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    conversation_id: UUID
    provider_message_id: str
    wa_id: str
    at: datetime
    kind: InboundKind
    body: str | None = None
    media_id: str | None = None
    mime: str | None = None
    size_bytes: int | None = None
    duration_seconds: Decimal | None = None
    transcript: str | None = None
    image_text: str | None = None


class GateFlags(BaseModel):
    """The GateFlags."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    afrikaans_text: bool
    afrikaans_voice: bool


class GateLimits(BaseModel):
    """The GateLimits."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    max_bytes: int
    max_audio_seconds: Decimal
    messages_per_minute: int
    allowed_types: tuple[str, ...]


class ReceiveResult(BaseModel):
    """The ReceiveResult a use case returns."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    stored: bool
    duplicate: bool
    sentence: str | None
    injection_instruction: bool
