from datetime import datetime
from typing import Protocol
from uuid import UUID

from quotedesk.application.dto.audit import AuditEvent
from quotedesk.domain.quotes.quote import Quote
from quotedesk.domain.shared.ids import QuoteId


class Clock(Protocol):
    def now(self) -> datetime: ...


class IdGenerator(Protocol):
    def next_quote_id(self) -> QuoteId: ...


class UnitOfWork(Protocol):
    def get_quote(self, tenant_id: UUID, conversation_id: UUID) -> Quote | None: ...

    def save_quote(self, tenant_id: UUID, conversation_id: UUID, quote: Quote) -> None: ...

    def record_audit(self, event: AuditEvent) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...
