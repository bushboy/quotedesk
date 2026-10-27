from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError as ModelError

from quotedesk.domain.quotes.schedule import (
    Capacity,
    CapacitySlot,
    DepositState,
    ScheduleCommitment,
    ScheduleRequest,
    ScheduleSettings,
    SlotHold,
)
from quotedesk.domain.services.schedule import civil_date, schedule
from quotedesk.domain.shared.errors import PolicyViolation
from tests.unit.domain.assertions import expect_domain

TODAY = date(2026, 10, 28)
AT = datetime(2026, 10, 28, 8, 0, tzinfo=timezone.utc)
FRIDAY = date(2026, 10, 30)
SATURDAY = date(2026, 10, 31)
TUESDAY = date(2026, 11, 3)
WEDNESDAY = date(2026, 11, 4)

SENTENCES = {
    "lead_time": "A {job_type} is usually about {lead_time_working_days} working days after the deposit.",
    "earliest": "The earliest window is {window}, and it is not reserved.",
    "requested_open": "That date is open. We can hold it when the deposit is paid.",
    "requested_closed": "That date is full. The next open days are {first} and {second}.",
    "too_soon": "That date is too soon. The earliest window is {window}.",
    "next_working_day": "The next working day is {window}.",
    "held": "That window is held until the deposit hold expires.",
    "confirmed": "That date is confirmed.",
    "escalated": "We can't guarantee a date here.",
}


def settings() -> ScheduleSettings:
    return ScheduleSettings(
        lead_time_working_days={"replacement": 5},
        minimum_notice_working_days=2,
        hold_period_hours=48,
        working_days=(0, 1, 2, 3, 4),
        blocked_dates=(date(2026, 11, 2),),
        sentences=SENTENCES,
    )


def capacity(*slots: CapacitySlot) -> Capacity:
    return Capacity(slots=slots)


def slot(day: date, places: int, holds: tuple[SlotHold, ...] = ()) -> CapacitySlot:
    return CapacitySlot(day=day, places=places, holds=holds)


def request(**overrides: object) -> ScheduleRequest:
    fields: dict[str, object] = {
        "kind": "earliest",
        "quote_issued": True,
        "job_type": "replacement",
        "requested_date": None,
        "site_measure_signed_off": False,
        "materials_confirmed": False,
    }
    fields.update(overrides)
    return ScheduleRequest(**fields)


def run(ask: ScheduleRequest, slots: Capacity, *, paid: bool = False, today: date = TODAY, at: datetime = AT):
    return schedule(ask, slots, settings(), DepositState(paid=paid), today=today, at=at)


def test_sched_01_lead_time_before_a_quote():
    slots = capacity(slot(FRIDAY, 1))
    result = run(request(kind="lead_time", quote_issued=False), slots)
    assert result.commitment.status == "none"
    assert "5" in result.commitment.sentence
    assert result.commitment.window_id is None
    assert result.commitment.earliest_window is None
    assert result.capacity == slots


def test_sched_02_earliest_window_is_indicative():
    slots = capacity(slot(FRIDAY, 1))
    result = run(request(kind="earliest"), slots)
    assert result.commitment.status == "indicative"
    assert result.commitment.earliest_window == FRIDAY
    assert result.capacity.remaining(FRIDAY, AT) == slots.remaining(FRIDAY, AT)


def test_sched_03_requested_date_open():
    slots = capacity(slot(FRIDAY, 1), slot(SATURDAY, 1))
    result = run(request(kind="requested_date", requested_date=SATURDAY), slots)
    assert result.commitment.status == "indicative"
    assert result.commitment.held_window_start is None
    assert result.commitment.held_window_end is None
    assert result.commitment.hold_expires_at is None
    assert result.commitment.sentence == SENTENCES["requested_open"]
    assert result.capacity == slots


def test_sched_03_requested_date_closed():
    slots = capacity(slot(FRIDAY, 1), slot(SATURDAY, 0), slot(TUESDAY, 1), slot(WEDNESDAY, 1))
    result = run(request(kind="requested_date", requested_date=SATURDAY), slots)
    assert result.commitment.status == "indicative"
    assert result.commitment.offered_dates == (TUESDAY, WEDNESDAY)
    assert "held" not in result.commitment.sentence
    assert result.capacity == slots


def test_sched_04_inside_minimum_lead():
    with pytest.raises(ModelError):
        request(kind="requested_date", requested_date=date(2026, 10, 29), override=True)
    slots = capacity(slot(FRIDAY, 1))
    result = run(request(kind="requested_date", requested_date=date(2026, 10, 29)), slots)
    assert result.commitment.status == "indicative"
    assert result.commitment.earliest_window == FRIDAY
    assert result.commitment.sentence == SENTENCES["too_soon"].format(window="2026-10-30")


def test_sched_05_hold_after_deposit():
    slots = capacity(slot(SATURDAY, 1))
    result = run(request(kind="hold", requested_date=SATURDAY), slots, paid=True)
    assert result.commitment.status == "held"
    assert result.commitment.hold_expires_at == datetime(2026, 10, 30, 8, 0, tzinfo=timezone.utc)
    assert result.capacity.remaining(SATURDAY, AT) == 0
    assert slots.remaining(SATURDAY, AT) == 1


def test_sched_05_hold_without_deposit_refused():
    slots = capacity(slot(SATURDAY, 1))
    expect_domain(
        lambda: run(request(kind="hold", requested_date=SATURDAY), slots, paid=False),
        PolicyViolation,
        "policy.violation",
        "A window is held only after the deposit is paid.",
    )
    assert slots.remaining(SATURDAY, AT) == 1


def test_sched_06_confirmed_when_dependencies_met():
    slots = capacity(slot(FRIDAY, 1))
    confirmed = run(
        request(
            kind="confirm",
            requested_date=FRIDAY,
            site_measure_signed_off=True,
            materials_confirmed=True,
        ),
        slots,
        paid=True,
    )
    assert confirmed.commitment.status == "confirmed"
    assert confirmed.commitment.depends_on == ()
    held = run(
        request(
            kind="confirm",
            requested_date=FRIDAY,
            site_measure_signed_off=False,
            materials_confirmed=True,
        ),
        slots,
        paid=True,
    )
    assert held.commitment.status == "held"
    assert held.commitment.depends_on == ("site_measure_signed_off",)
    assert held.capacity == slots


def test_sched_07_no_guarantee():
    slots = capacity(slot(FRIDAY, 1))
    result = run(request(kind="guarantee"), slots)
    assert result.commitment.status == "escalated"
    assert result.commitment.offered_dates == ()
    assert result.commitment.held_window_start is None
    assert result.commitment.hold_expires_at is None
    assert result.capacity == slots
    assert "state" not in ScheduleCommitment.model_fields


def test_sched_now_now_is_a_date_request():
    slots = capacity(slot(FRIDAY, 1))
    too_soon = run(request(kind="requested_date", requested_date=date(2026, 10, 29)), slots)
    now_now = run(request(kind="requested_date", requested_date=TODAY), slots)
    assert now_now.commitment.status == too_soon.commitment.status == "indicative"
    assert now_now.commitment.earliest_window == too_soon.commitment.earliest_window == FRIDAY
    assert now_now.commitment.sentence == too_soon.commitment.sentence


def test_sched_skips_weekends_and_blocked_dates():
    slots = capacity(slot(TUESDAY, 1))
    result = run(
        request(kind="requested_date", requested_date=SATURDAY),
        slots,
        today=SATURDAY,
    )
    assert result.commitment.status == "indicative"
    assert result.commitment.earliest_window == TUESDAY
    assert "held" not in result.commitment.sentence


def test_sched_second_hold_of_a_full_slot_fails():
    slots = capacity(slot(SATURDAY, 1))
    first = run(request(kind="hold", requested_date=SATURDAY), slots, paid=True)
    assert len(first.capacity.slots[0].holds) == 1
    expect_domain(
        lambda: run(request(kind="hold", requested_date=SATURDAY), first.capacity, paid=True),
        PolicyViolation,
        "policy.violation",
        "That window has no place left.",
    )
    assert len(first.capacity.slots[0].holds) == 1
    assert first.capacity.remaining(SATURDAY, AT) == 0


def test_sched_expired_hold_releases():
    expired = SlotHold(hold_expires_at=datetime(2026, 10, 28, 7, 59, tzinfo=timezone.utc))
    slots = capacity(slot(SATURDAY, 1, (expired,)))
    result = run(request(kind="hold", requested_date=SATURDAY), slots, paid=True)
    assert result.commitment.status == "held"
    assert slots.remaining(SATURDAY, AT) == 1


def test_sched_local_date_not_utc():
    at = datetime(2026, 10, 30, 22, 30, tzinfo=timezone.utc)
    assert civil_date(at, ZoneInfo("Africa/Johannesburg")) == date(2026, 10, 31)
