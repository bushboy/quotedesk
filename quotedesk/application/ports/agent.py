from typing import Protocol
from uuid import UUID

from quotedesk.application.dto.agent import ModelReply, TurnPrompt


class AgentModel(Protocol):
    def complete(self, prompt: TurnPrompt) -> ModelReply: ...


class ConversationLock(Protocol):
    def acquire(self, conversation_id: UUID) -> bool: ...

    def release(self, conversation_id: UUID) -> None: ...
