from typing import Literal

from pydantic import BaseModel, ConfigDict


class OutboxMessage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    body: str
    status: Literal["pending"]


class Outbox:
    def __init__(self) -> None:
        self._rows: list[OutboxMessage] = []

    def append(self, body: str) -> OutboxMessage:
        message = OutboxMessage(body=body, status="pending")
        self._rows.append(message)
        return message

    def pending(self) -> tuple[OutboxMessage, ...]:
        return tuple(self._rows)
