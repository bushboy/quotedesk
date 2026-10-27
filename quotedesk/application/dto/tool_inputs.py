from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

FactSource = Literal[
    "customer_text",
    "voice_transcript",
    "photo_extraction",
    "video_extraction",
    "owner",
]


class GetQuoteInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    conversation_id: UUID


class FactInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    value: str
    source: FactSource
    event_id: UUID
