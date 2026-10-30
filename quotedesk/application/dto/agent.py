from datetime import datetime
from enum import Enum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TurnOutcome(str, Enum):
    ASKED = "asked"
    QUOTED = "quoted"
    INSPECTION_OFFERED = "inspection_offered"
    INSPECTION_BOOKED = "inspection_booked"
    ESCALATED = "escalated"
    ANSWERED = "answered"

from quotedesk.domain.case.case_file import CaseFile
from quotedesk.domain.services.confidence import RecordedMask

PromptKind = Literal["text", "image", "audio", "video"]


class ToolCall(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    arguments: dict[str, Any]
    call_id: str = ""


class ModelReply(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    tool_calls: tuple[ToolCall, ...] = ()


class Handover(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    conversation_id: UUID
    case: CaseFile
    reason: str


class HandoverNote(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    conversation_id: UUID
    reason: str
    brief: str
    at: datetime


class PromptMessage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider_message_id: str
    kind: PromptKind
    body: str
    role: Literal["customer", "assistant"] = "customer"


class PromptFact(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    job_id: str
    key: str
    value: str
    source: str
    event_id: UUID


class CaseView(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    facts: tuple[PromptFact, ...] = ()
    missing_required: tuple[str, ...] = ()
    contradiction_count: int = 0


class PromptRateItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    item_code: str
    description: str


class PromptExtraction(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider_message_id: str
    summary: str
    objects: tuple[str, ...]


class ExtractionResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    summary: str
    objects: tuple[str, ...]
    blur: bool = False
    darkness: bool = False
    wrong_subject: bool = False
    masks: tuple[RecordedMask, ...] = ()
    sam_error: bool = False
    sam_sentence: str = ""


class ToolPayload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    body: dict[str, Any]


class BusinessView(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = ""
    trade: str = ""
    area: str = ""
    about: str = ""


class TurnPrompt(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    event_ids: tuple[str, ...]
    tool_results: tuple[str, ...] = ()
    messages: tuple[PromptMessage, ...] = ()
    case: CaseView = Field(default_factory=CaseView)
    rate_card: tuple[PromptRateItem, ...] = ()
    tool_payloads: tuple[ToolPayload, ...] = ()
    extractions: tuple[PromptExtraction, ...] = ()
    business: BusinessView = Field(default_factory=BusinessView)
    task: str = ""
    effort: Literal["low", "medium"] = "medium"
    exchanges: tuple[dict[str, Any], ...] = ()
