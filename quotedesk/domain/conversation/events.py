from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

MessageStatus = Literal["pending", "claimed", "answered", "escalated", "failed"]

from quotedesk.domain.shared.errors import PolicyViolation

_BODY = "A message body is not edited."
_MISSING = "That message is not on the conversation."


class ConversationEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider_message_id: str
    at: datetime
    body: str
    transcript_id: str | None = None
    extraction_id: str | None = None
    status: MessageStatus = "pending"
    outcome: str | None = None


class AppendResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    conversation: Conversation
    duplicate: bool


class Conversation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    conversation_id: UUID
    log: tuple[ConversationEvent, ...] = ()

    @classmethod
    def open(cls, conversation_id: UUID) -> "Conversation":
        return cls(conversation_id=conversation_id)

    @property
    def events(self) -> tuple[ConversationEvent, ...]:
        return tuple(sorted(self.log, key=lambda event: event.at))

    def append(self, provider_message_id: str, at: datetime, body: str) -> AppendResult:
        if any(event.provider_message_id == provider_message_id for event in self.log):
            return AppendResult(conversation=self, duplicate=True)
        event = ConversationEvent(provider_message_id=provider_message_id, at=at, body=body)
        return AppendResult(
            conversation=self.model_copy(update={"log": self.log + (event,)}),
            duplicate=False,
        )

    def replace_body(self, provider_message_id: str, body: str) -> "Conversation":
        raise PolicyViolation(code="policy.violation", sentence=_BODY)

    def attach(
        self,
        provider_message_id: str,
        *,
        transcript_id: str | None = None,
        extraction_id: str | None = None,
    ) -> "Conversation":
        if not any(event.provider_message_id == provider_message_id for event in self.log):
            raise PolicyViolation(code="policy.violation", sentence=_MISSING)
        log = tuple(
            event.model_copy(
                update={
                    "transcript_id": transcript_id if transcript_id is not None else event.transcript_id,
                    "extraction_id": extraction_id if extraction_id is not None else event.extraction_id,
                }
            )
            if event.provider_message_id == provider_message_id
            else event
            for event in self.log
        )
        return self.model_copy(update={"log": log})


AppendResult.model_rebuild()
