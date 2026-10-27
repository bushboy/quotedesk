from uuid import UUID

from pydantic import BaseModel, ConfigDict

from quotedesk.domain.shared.ids import QuoteId


class AuditEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    tenant_id: UUID
    action: str
    quote_id: QuoteId
    version: int
