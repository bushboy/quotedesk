"""The tool inputs. The model and the console pass these into the use cases."""

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
    """The GetQuoteInput a caller passes in."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    conversation_id: UUID


_FORBIDDEN_FACT_KEYS = frozenset({"unit_price", "outcome", "clause_text"})


class FactInput(BaseModel):
    """The FactInput a caller passes in."""
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
    """The ClauseChange."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    clause_id: str
    action: Literal["delete"]


class RequestChangeInput(BaseModel):
    """The RequestChangeInput a caller passes in."""
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
    """The UpdateCaseInput a caller passes in."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    conversation_id: UUID
    job_id: str
    job_type: str | None = None
    facts: tuple[FactInput, ...]
    system: bool = False


class CheckAvailabilityInput(BaseModel):
    """The CheckAvailabilityInput a caller passes in."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    job_type: str
    requested_date: date | None = None


class HoldSlotInput(BaseModel):
    """The HoldSlotInput a caller passes in."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    quote_id: QuoteId
    requested_date: date
    idempotency_key: str
    job_type: str = "replacement"


class BookInspectionInput(BaseModel):
    """The BookInspectionInput a caller passes in."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    conversation_id: UUID
    job_id: str = ""
    address: str = ""
    summary: str = ""
    confirm: bool = False


class EscalateToOwnerInput(BaseModel):
    """The EscalateToOwnerInput a caller passes in."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    conversation_id: UUID
    summary: str = ""


class AcceptQuoteInput(BaseModel):
    """The AcceptQuoteInput a caller passes in."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    quote_id: QuoteId


class GetQuoteStatusInput(BaseModel):
    """The GetQuoteStatusInput a caller passes in."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    quote_id: QuoteId
    verification_code: str | None = None


class CreateDepositLinkInput(BaseModel):
    """The CreateDepositLinkInput a caller passes in."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    quote_id: QuoteId
    idempotency_key: str


class ApproveExceptionInput(BaseModel):
    """The ApproveExceptionInput a caller passes in."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    quote_id: QuoteId
    version: int
    idempotency_key: str = Field(min_length=1)
    expires_at: datetime


class RejectExceptionInput(BaseModel):
    """The RejectExceptionInput a caller passes in."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    quote_id: QuoteId
    version: int
    idempotency_key: str = Field(min_length=1)


class PublishInput(BaseModel):
    """The PublishInput a caller passes in."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    reason: str
    idempotency_key: str = Field(min_length=1)


class RollbackInput(BaseModel):
    """The RollbackInput a caller passes in."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    source_version: PolicyVersionId
    reason: str
    idempotency_key: str = Field(min_length=1)
