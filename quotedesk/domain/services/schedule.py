from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from quotedesk.domain.quotes.schedule import (
    Capacity,
    DepositState,
    ScheduleCommitment,
    ScheduleRequest,
    ScheduleResult,
    ScheduleSettings,
    SlotHold,
)
from quotedesk.domain.shared.errors import PolicyViolation, ValidationError

_NAIVE = "A schedule instant needs a timezone."
_NOT_A_DATE = "A schedule date is a calendar date."
_UNPAID = "A window is held only after the deposit is paid."
_FULL = "That window has no place left."
_NO_TEMPLATE = "A schedule sentence has no template."
_NO_DAY = "That calendar has no open day."


def civil_date(at: datetime, zone: ZoneInfo) -> date:
    _aware(at)
    return at.astimezone(zone).date()


def schedule(
    request: ScheduleRequest,
    capacity: Capacity,
    settings: ScheduleSettings,
    deposit_state: DepositState,
    *,
    today: date,
    at: datetime,
) -> ScheduleResult:
    if type(today) is not date:
        raise ValidationError(code="schedule.not_a_date", sentence=_NOT_A_DATE)
    _aware(at)
    if request.kind == "guarantee":
        return _done("escalated", _sentence(settings, "escalated"), capacity)
    if not request.quote_issued:
        days = settings.lead_time_working_days.get(request.job_type)
        if days is None:
            raise PolicyViolation(code="policy.violation", sentence=_NO_TEMPLATE)
        sentence = _sentence(
            settings,
            "lead_time",
            job_type=request.job_type,
            lead_time_working_days=str(days),
        )
        return _done("none", sentence, capacity)
    if request.kind == "hold" and not deposit_state.paid:
        raise PolicyViolation(code="policy.violation", sentence=_UNPAID)
    if request.kind == "hold" and capacity.remaining(request.requested_date, at) == 0:
        raise PolicyViolation(code="policy.violation", sentence=_FULL)
    if request.kind == "hold":
        expires = at + timedelta(hours=settings.hold_period_hours)
        return _done(
            "held",
            _sentence(settings, "held"),
            _with_hold(capacity, request.requested_date, SlotHold(hold_expires_at=expires)),
            requested_date=request.requested_date,
            held_window_start=request.requested_date,
            held_window_end=request.requested_date,
            hold_expires_at=expires,
        )
    if request.kind == "confirm" and not deposit_state.paid:
        raise PolicyViolation(code="policy.violation", sentence=_UNPAID)
    if request.kind == "confirm":
        missing = tuple(
            name
            for name, present in (
                ("site_measure_signed_off", request.site_measure_signed_off),
                ("materials_confirmed", request.materials_confirmed),
            )
            if not present
        )
        if missing:
            return _done(
                "held",
                _sentence(settings, "held"),
                capacity,
                requested_date=request.requested_date,
                depends_on=missing,
            )
        return _done(
            "confirmed",
            _sentence(settings, "confirmed"),
            capacity,
            requested_date=request.requested_date,
            held_window_start=request.requested_date,
            held_window_end=request.requested_date,
        )
    if request.requested_date is not None and not _has_slot(capacity, request.requested_date):
        if not _working(request.requested_date, settings):
            window = _next_open(request.requested_date, 1, settings, capacity, at)[0]
            return _done(
                "indicative",
                _sentence(settings, "next_working_day", window=window.isoformat()),
                capacity,
                earliest_window=window,
                requested_date=request.requested_date,
            )
    legal = _earliest_legal(today, settings, capacity, at)
    if request.requested_date is not None and request.requested_date < legal:
        return _done(
            "indicative",
            _sentence(settings, "too_soon", window=legal.isoformat()),
            capacity,
            earliest_window=legal,
            requested_date=request.requested_date,
        )
    if request.requested_date is not None and capacity.remaining(request.requested_date, at) == 0:
        offered = _next_open(request.requested_date, 2, settings, capacity, at)
        return _done(
            "indicative",
            _sentence(
                settings,
                "requested_closed",
                first=offered[0].isoformat(),
                second=offered[1].isoformat(),
            ),
            capacity,
            requested_date=request.requested_date,
            offered_dates=offered,
        )
    if request.requested_date is not None and capacity.remaining(request.requested_date, at) > 0:
        return _done(
            "indicative",
            _sentence(settings, "requested_open"),
            capacity,
            earliest_window=request.requested_date,
            requested_date=request.requested_date,
        )
    return _done(
        "indicative",
        _sentence(settings, "earliest", window=legal.isoformat()),
        capacity,
        earliest_window=legal,
    )


def _aware(at: datetime) -> None:
    if at.tzinfo is None or at.tzinfo.utcoffset(at) is None:
        raise ValidationError(code="schedule.instant_naive", sentence=_NAIVE)


def _sentence(settings: ScheduleSettings, key: str, **values: str) -> str:
    template = settings.sentences.get(key)
    if template is None:
        raise PolicyViolation(code="policy.violation", sentence=_NO_TEMPLATE)
    try:
        return template.format(**values)
    except KeyError:
        raise PolicyViolation(code="policy.violation", sentence=_NO_TEMPLATE) from None


def _working(day: date, settings: ScheduleSettings) -> bool:
    return day.weekday() in settings.working_days and day not in settings.blocked_dates


def _has_slot(capacity: Capacity, day: date) -> bool:
    return any(slot.day == day for slot in capacity.slots)


def _earliest_legal(today: date, settings: ScheduleSettings, capacity: Capacity, at: datetime) -> date:
    found = 0
    day = today
    for _ in range(366):
        day += timedelta(days=1)
        if not _working(day, settings):
            continue
        found += 1
        if found >= settings.minimum_notice_working_days and capacity.remaining(day, at) > 0:
            return day
    raise PolicyViolation(code="policy.violation", sentence=_NO_DAY)


def _next_open(
    start: date,
    count: int,
    settings: ScheduleSettings,
    capacity: Capacity,
    at: datetime,
) -> tuple[date, ...]:
    found: list[date] = []
    day = start
    for _ in range(366):
        day += timedelta(days=1)
        if _working(day, settings) and capacity.remaining(day, at) > 0:
            found.append(day)
            if len(found) == count:
                return tuple(found)
    raise PolicyViolation(code="policy.violation", sentence=_NO_DAY)


def _with_hold(capacity: Capacity, day: date, hold: SlotHold) -> Capacity:
    slots = tuple(
        slot.model_copy(update={"holds": slot.holds + (hold,)}) if slot.day == day else slot
        for slot in capacity.slots
    )
    return Capacity(slots=slots)


def _done(status: str, sentence: str, capacity: Capacity, **fields: object) -> ScheduleResult:
    return ScheduleResult(
        commitment=ScheduleCommitment(status=status, sentence=sentence, window_id=None, **fields),
        capacity=capacity,
    )
