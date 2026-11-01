"""The agent ports. The turn calls a model and a conversation lock through these."""

from typing import Protocol
from uuid import UUID

from quotedesk.application.dto.agent import ModelReply, TurnPrompt


class AgentModel(Protocol):
    """The port for AgentModel."""
    def complete(self, prompt: TurnPrompt) -> ModelReply: ...


class ConversationLock(Protocol):
    """The port for ConversationLock."""
    def acquire(self, conversation_id: UUID) -> bool: ...

    def release(self, conversation_id: UUID) -> None: ...
