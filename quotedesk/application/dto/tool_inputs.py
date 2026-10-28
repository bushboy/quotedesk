from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.functional_validators import BeforeValidator

from quotedesk.domain.shared.ids import PolicyVersionId, QuoteId

FactSource = Literal[
    "customer_text",
    "voice_transcript",
    "photo_extraction",
    "video_extraction",
    "owner",
]


class GetQuoteInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    conversation_id: UUID


_FORBIDDEN_FACT_KEYS = frozenset({"unit_price", "outcome", "clause_text"})


class FactInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    value: str
    source: FactSource
    event_id: UUID

    @model_validator(mode="after")
    def _not_commercial(self) -> Self:
        if self.key in _FORBIDDEN_FACT_KEYS:
            raise ValueError("A fact is not a price, an outcome, or a clause.")
        return self


def _reject_float(value: Any) -> Any:
    if isinstance(value, float):
        raise ValueError("A discount percent is a decimal, not a floating-point number.")
    return value


class ClauseChange(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    clause_id: str
    action: Literal["delete"]


class RequestChangeInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    quote_id: QuoteId
    version: int
    idempotency_key: str = Field(min_length=1)
    discount_percent: Annotated[Decimal, BeforeValidator(_reject_float)] | None = None
    clause_change: ClauseChange | None = None
    reason: str = ""

    @model_validator(mode="after")
    def _one_change(self) -> Self:
        discount = self.discount_percent is not None
        clause = self.clause_change is not None
        if discount == clause:
            raise ValueError("A change is a discount or a clause, and only one.")
        return self


class UpdateCaseInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    conversation_id: UUID
    job_id: str
    job_type: str | None = None
    facts: tuple[FactInput, ...]


class CheckAvailabilityInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    job_type: str
    requested_date: date | None = None


class HoldSlotInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    quote_id: QuoteId
    requested_date: date
    idempotency_key: str


class GetQuoteStatusInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    quote_id: QuoteId
    verification_code: str | None = None


class CreateDepositLinkInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    quote_id: QuoteId
    idempotency_key: str


class ApproveExceptionInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    quote_id: QuoteId
    version: int
    idempotency_key: str = Field(min_length=1)
    expires_at: datetime


class RejectExceptionInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    quote_id: QuoteId
    version: int
    idempotency_key: str = Field(min_length=1)


class PublishInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    reason: str
    idempotency_key: str = Field(min_length=1)


class RollbackInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source_version: PolicyVersionId
    reason: str
    idempotency_key: str = Field(min_length=1)
