from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from quotedesk.domain.shared.errors import ValidationError

ScheduleStatus = Literal["none", "indicative", "held", "confirmed", "escalated"]
RequestKind = Literal["lead_time", "earliest", "requested_date", "hold", "confirm", "guarantee"]

_NOT_A_DATE = "A schedule date is a calendar date."


def _civil(value: object) -> date | None:
    if value is None:
        return None
    if type(value) is date:
        return value
    raise ValidationError(code="schedule.not_a_date", sentence=_NOT_A_DATE)


class ScheduleRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: RequestKind
    quote_issued: bool
    job_type: str
    requested_date: date | None = None
    site_measure_signed_off: bool = False
    materials_confirmed: bool = False

    def __init__(self, **data: object) -> None:
        data["requested_date"] = _civil(data.get("requested_date"))
        super().__init__(**data)


class SlotHold(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    hold_expires_at: datetime


class CapacitySlot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    day: date
    places: int
    holds: tuple[SlotHold, ...] = ()


class Capacity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    slots: tuple[CapacitySlot, ...] = ()

    def remaining(self, day: date, at: datetime) -> int:
        for slot in self.slots:
            if slot.day == day:
                used = sum(1 for hold in slot.holds if hold.hold_expires_at >= at)
                return slot.places - used
        return 0


class ScheduleSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    lead_time_working_days: dict[str, int]
    minimum_notice_working_days: int
    hold_period_hours: int
    working_days: tuple[int, ...]
    blocked_dates: tuple[date, ...]
    sentences: dict[str, str]


class DepositState(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    paid: bool


class ScheduleCommitment(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: ScheduleStatus
    sentence: str
    earliest_window: date | None = None
    requested_date: date | None = None
    held_window_start: date | None = None
    held_window_end: date | None = None
    hold_expires_at: datetime | None = None
    window_id: str | None = None
    offered_dates: tuple[date, ...] = ()
    depends_on: tuple[str, ...] = ()


class ScheduleResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    commitment: ScheduleCommitment
    capacity: Capacity
