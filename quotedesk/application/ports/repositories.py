from datetime import datetime
from typing import Protocol
from uuid import UUID

from quotedesk.application.dto.audit import AuditEvent
from quotedesk.application.dto.changes import DepositLinkRecord
from quotedesk.application.dto.inbound import InboundMessage
from quotedesk.application.dto.published import PublishedPolicy
from quotedesk.application.dto.tenant import CommercialSettings
from quotedesk.application.dto.tool_outputs import HoldResult
from quotedesk.domain.case.case_file import CaseFile
from quotedesk.domain.conversation.events import Conversation
from quotedesk.domain.quotes.quote import Quote
from quotedesk.domain.quotes.schedule import Capacity
from quotedesk.domain.shared.ids import QuoteId


class CaseFileRepository(Protocol):
    def get(self, tenant_id: UUID, conversation_id: UUID) -> CaseFile | None: ...

    def save(self, tenant_id: UUID, case: CaseFile) -> None: ...


class ConversationRepository(Protocol):
    def get(self, tenant_id: UUID, conversation_id: UUID) -> Conversation | None: ...

    def save(self, tenant_id: UUID, conversation: Conversation) -> None: ...

    def note(self, tenant_id: UUID, wa_id: str, at: datetime) -> None: ...

    def noted(self, tenant_id: UUID, wa_id: str) -> tuple[datetime, ...]: ...

    def remember(self, tenant_id: UUID, message: InboundMessage) -> None: ...

    def messages(self, tenant_id: UUID, conversation_id: UUID) -> tuple[InboundMessage, ...]: ...


class JobCatalog(Protocol):
    def required(self, job_type: str) -> tuple[str, ...]: ...


class VerificationCodes(Protocol):
    def issue(self, tenant_id: UUID, quote_id: QuoteId) -> str: ...

    def matches(self, tenant_id: UUID, quote_id: QuoteId, code: str) -> bool: ...


class Acceptances(Protocol):
    def has(self, tenant_id: UUID, quote_id: QuoteId, version: int) -> bool: ...


class DepositLinks(Protocol):
    def find(self, tenant_id: UUID, idempotency_key: str) -> DepositLinkRecord | None: ...

    def save(self, record: DepositLinkRecord) -> None: ...


class Deposits(Protocol):
    def paid(self, tenant_id: UUID, quote_id: QuoteId) -> bool: ...


class CapacityRepository(Protocol):
    def get(self, tenant_id: UUID) -> Capacity: ...

    def save(self, tenant_id: UUID, capacity: Capacity) -> None: ...


class SlotHolds(Protocol):
    def find(self, tenant_id: UUID, idempotency_key: str) -> HoldResult | None: ...

    def save(self, tenant_id: UUID, idempotency_key: str, result: HoldResult) -> None: ...


class PolicyRepository(Protocol):
    def published(self, tenant_id: UUID) -> PublishedPolicy | None: ...


class QuoteRepository(Protocol):
    def get(self, tenant_id: UUID, conversation_id: UUID) -> Quote | None: ...

    def get_by_id(self, tenant_id: UUID, quote_id: QuoteId) -> Quote | None: ...

    def list_for(self, tenant_id: UUID) -> tuple[Quote, ...]: ...

    def save(self, tenant_id: UUID, conversation_id: UUID, quote: Quote) -> None: ...


class TenantSettings(Protocol):
    def for_tenant(self, tenant_id: UUID) -> CommercialSettings: ...


class AuditLog(Protocol):
    def record(self, event: AuditEvent) -> None: ...
