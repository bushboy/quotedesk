from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from quotedesk.domain.policy.clauses import Condition
from quotedesk.domain.policy.rules import Outcome
from quotedesk.domain.quotes.quote import QuoteLine, QuoteState
from quotedesk.domain.shared.ids import PolicyVersionId, QuoteId, RuleId
from quotedesk.domain.shared.money import Money


class GetQuoteResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    quote_id: QuoteId
    version: int
    state: QuoteState
    policy_version: PolicyVersionId
    rule_id: RuleId
    outcome: Outcome
    customer_template: str
    lines: tuple[QuoteLine, ...]
    clauses: tuple[Condition, ...]
    price_type: Literal["fixed", "range", "none"]
    total: Money | None
    range_min: Money | None
    range_max: Money | None
    site_visit_fee: Money | None
    deposit: Money | None
    schedule_status: Literal["none"]
    expiry: date
    verification_code: str | None = None


class RequestChangeResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    quote_id: QuoteId
    version: int
    state: QuoteState
    discount_percent: Decimal
    lines: tuple[QuoteLine, ...]
    clauses: tuple[Condition, ...]


class UpdateCaseResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    job_id: str
    created: bool
    current: dict[str, str]
    missing_required: tuple[str, ...]
    contradiction_count: int


class AvailabilityResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: str
    earliest_window: date | None
    sentence: str


class HoldResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: str
    held_window_start: date
    hold_expires_at: datetime


class QuoteStatusResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    found: bool
    state: QuoteState | None
    expiry: date | None
    version: int | None
    schedule_status: str | None


class AcceptQuoteResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    quote_id: QuoteId
    version: int
    state: QuoteState


class DepositLinkResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    url: str


class ApproveResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    quote_id: QuoteId
    version: int
    state: QuoteState
    discount_percent: Decimal
    lines: tuple[QuoteLine, ...]


class BookInspectionResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    inspection_id: UUID
    status: Literal["offered", "booked", "completed"]
    rule_id: str
    fee: str
    window_start: date | None
    window_end: date | None
    sentence: str


class EscalateToOwnerResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    sentence: str
    brief: str
    notified: str = ""


class PendingRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    quote_id: QuoteId
    version: int
    requested_discount_percent: Decimal
    discount_cap_percent: Decimal
    total: Money
