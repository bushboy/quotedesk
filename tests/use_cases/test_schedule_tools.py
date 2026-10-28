from datetime import date, datetime, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError as ModelError

from quotedesk.application.dto.tenant import TenantContext
from quotedesk.application.dto.tool_inputs import CheckAvailabilityInput, HoldSlotInput
from quotedesk.application.errors import TenantRequired
from quotedesk.application.use_cases.tools.check_availability import CheckAvailability
from quotedesk.application.use_cases.tools.hold_slot import HoldSlot
from quotedesk.domain.quotes.schedule import Capacity, CapacitySlot, ScheduleSettings
from quotedesk.domain.shared.errors import PolicyViolation
from quotedesk.domain.shared.ids import QuoteId

TENANT = UUID("11111111-1111-4111-8111-111111111111")
AT = datetime(2026, 10, 28, 8, 0, tzinfo=timezone.utc)
FRIDAY = date(2026, 10, 30)
QUOTE = QuoteId("QD-1042")


def settings() -> ScheduleSettings:
    return ScheduleSettings(
        lead_time_working_days={"replacement": 5},
        minimum_notice_working_days=2,
        hold_period_hours=48,
        working_days=(0, 1, 2, 3, 4),
        blocked_dates=(date(2026, 11, 2),),
        sentences={
            "lead_time": "A {job_type} is usually about {lead_time_working_days} working days after the deposit.",
            "earliest": "The earliest window is {window}, and it is not reserved.",
            "requested_open": "That date is open. We can hold it when the deposit is paid.",
            "requested_closed": "That date is full. The next open days are {first} and {second}.",
            "too_soon": "That date is too soon. The earliest window is {window}.",
            "next_working_day": "The next working day is {window}.",
            "held": "That window is held until the deposit hold expires.",
            "confirmed": "That date is confirmed.",
            "escalated": "We can't guarantee a date here.",
        },
    )


class Slots:
    def __init__(self, capacity: Capacity) -> None:
        self.capacity = capacity
        self.saves = 0

    def get(self, tenant_id: UUID) -> Capacity:
        return self.capacity

    def save(self, tenant_id: UUID, capacity: Capacity) -> None:
        self.saves += 1
        self.capacity = capacity


class Clock:
    def now(self) -> datetime:
        return AT


class Paid:
    def __init__(self, paid: bool) -> None:
        self._paid = paid
        self.calls = 0

    def paid(self, tenant_id: UUID, quote_id: QuoteId) -> bool:
        self.calls += 1
        return self._paid


class Holds:
    def __init__(self) -> None:
        self.rows: dict[tuple[UUID, str], object] = {}

    def find(self, tenant_id: UUID, idempotency_key: str):
        return self.rows.get((tenant_id, idempotency_key))

    def save(self, tenant_id: UUID, idempotency_key: str, result) -> None:
        self.rows[(tenant_id, idempotency_key)] = result


def open_day() -> Capacity:
    return Capacity(slots=(CapacitySlot(day=FRIDAY, places=1),))


def test_check_availability_reserves_nothing():
    capacity = open_day()
    slots = Slots(capacity)
    tool = CheckAvailability(slots, settings(), Clock())
    with pytest.raises(TenantRequired):
        tool.execute(None, CheckAvailabilityInput(job_type="replacement"))
    assert slots.saves == 0
    before = capacity.remaining(FRIDAY, AT)
    result = tool.execute(TenantContext(tenant_id=TENANT), CheckAvailabilityInput(job_type="replacement"))
    assert result.status == "indicative"
    assert result.earliest_window == FRIDAY
    assert result.sentence == "The earliest window is 2026-10-30, and it is not reserved."
    assert slots.saves == 0
    assert slots.capacity.remaining(FRIDAY, AT) == before == 1
    with pytest.raises(ModelError):
        CheckAvailabilityInput(job_type="replacement", unit_price="1")


def test_hold_slot_idempotent():
    slots = Slots(open_day())
    holds = Holds()
    tool = HoldSlot(slots, Paid(True), holds, settings(), Clock())
    data = HoldSlotInput(quote_id=QUOTE, requested_date=FRIDAY, idempotency_key="hold-1")
    first = tool.execute(TenantContext(tenant_id=TENANT), data)
    second = tool.execute(TenantContext(tenant_id=TENANT), data)
    assert first == second
    assert first.status == "held"
    assert first.held_window_start == FRIDAY
    assert first.hold_expires_at == datetime(2026, 10, 30, 8, 0, tzinfo=timezone.utc)
    assert slots.saves == 1
    day = slots.capacity.slots[0]
    assert len(day.holds) == 1


def test_hold_slot_requires_a_paid_deposit():
    capacity = open_day()
    slots = Slots(capacity)
    tool = HoldSlot(slots, Paid(False), Holds(), settings(), Clock())
    with pytest.raises(TenantRequired):
        tool.execute(None, HoldSlotInput(quote_id=QUOTE, requested_date=FRIDAY, idempotency_key="hold-1"))
    assert slots.saves == 0
    with pytest.raises(PolicyViolation) as caught:
        tool.execute(
            TenantContext(tenant_id=TENANT),
            HoldSlotInput(quote_id=QUOTE, requested_date=FRIDAY, idempotency_key="hold-1"),
        )
    assert caught.value.code == "policy.violation"
    assert str(caught.value) == "A window is held only after the deposit is paid."
    assert slots.saves == 0
    assert slots.capacity.remaining(FRIDAY, AT) == 1
    assert slots.capacity is capacity
    with pytest.raises(ModelError):
        HoldSlotInput(quote_id=QUOTE, requested_date=FRIDAY, idempotency_key="hold-1", unit_price="1")
