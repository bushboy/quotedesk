import logging
from typing import Literal

from pydantic import BaseModel, ConfigDict

_log = logging.getLogger(__name__)


class OutboxMessage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    body: str
    status: Literal["pending"]
    id: int = 0
    wa_id: str = ""


class Outbox:
    def __init__(self) -> None:
        self._rows: list[OutboxMessage] = []
        self._next = 0

    def append(self, body: str, wa_id: str = "") -> OutboxMessage:
        self._next += 1
        message = OutboxMessage(id=self._next, wa_id=wa_id, body=body, status="pending")
        self._rows.append(message)
        return message

    def pending(self) -> tuple[OutboxMessage, ...]:
        return tuple(self._rows)


class OutboxSender:
    def __init__(self, outbox: Outbox) -> None:
        self._outbox = outbox

    def send(self, wa_id: str, body: str) -> None:
        _log.info("Front end reply wa_id=%s body=%s", wa_id, body)
        self._outbox.append(body, wa_id)
