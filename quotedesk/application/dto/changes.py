from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from quotedesk.application.dto.tool_outputs import RequestChangeResult
from quotedesk.domain.shared.ids import QuoteId


class ChangeRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    tenant_id: UUID
    idempotency_key: str
    requested_discount_percent: Decimal | None = None
    clause_id: str | None = None
    clause_action: Literal["delete"] | None = None
    reason: str = ""
    result: RequestChangeResult


class DepositLinkRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    tenant_id: UUID
    idempotency_key: str
    quote_id: QuoteId
    url: str
