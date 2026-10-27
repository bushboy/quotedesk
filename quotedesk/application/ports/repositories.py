from typing import Protocol
from uuid import UUID

from quotedesk.application.dto.audit import AuditEvent
from quotedesk.application.dto.published import PublishedPolicy
from quotedesk.domain.case.case_file import CaseFile
from quotedesk.domain.quotes.quote import Quote


class CaseFileRepository(Protocol):
    def get(self, tenant_id: UUID, conversation_id: UUID) -> CaseFile | None: ...


class PolicyRepository(Protocol):
    def published(self, tenant_id: UUID) -> PublishedPolicy | None: ...


class QuoteRepository(Protocol):
    def get(self, tenant_id: UUID, conversation_id: UUID) -> Quote | None: ...

    def save(self, tenant_id: UUID, conversation_id: UUID, quote: Quote) -> None: ...


class AuditLog(Protocol):
    def record(self, event: AuditEvent) -> None: ...
