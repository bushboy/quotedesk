from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from quotedesk.domain.case.case_file import CaseFile


class ToolCall(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    arguments: dict[str, Any]


class ModelReply(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    tool_calls: tuple[ToolCall, ...] = ()


class Handover(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    conversation_id: UUID
    case: CaseFile
    reason: str


class TurnPrompt(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    event_ids: tuple[str, ...]
    tool_results: tuple[str, ...] = ()
