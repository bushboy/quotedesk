"""What the owner's Today tab shows and reads out, for one period."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from quotedesk.domain.shared.money import Money

Period = Literal["today", "yesterday", "week"]


class SummaryLines(BaseModel):
    """One sentence per tile, ready to speak."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    enquiries: str
    quotes: str
    deposits: str
    inspections: str
    waiting: str


class OwnerSummary(BaseModel):
    """Counts and amounts for one period. Waiting counts are as of now, whatever the period."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    period: Period
    label: str
    start: datetime
    end: datetime
    customers: int
    messages: int
    quotes_sent: int
    quoted_value: Money
    ranges: int
    deposits_due: Money
    deposits_paid: int
    inspections_offered: int
    inspections_booked: int
    handovers_waiting: int
    approvals_waiting: int
    oldest_wait: datetime | None
    lines: SummaryLines
    spoken: str
