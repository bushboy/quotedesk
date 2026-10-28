from zoneinfo import ZoneInfo

from quotedesk.application.dto.tenant import TenantContext
from quotedesk.application.dto.tool_inputs import CheckAvailabilityInput
from quotedesk.application.dto.tool_outputs import AvailabilityResult
from quotedesk.application.errors import TenantRequired
from quotedesk.application.ports.repositories import CapacityRepository
from quotedesk.application.ports.runtime import Clock
from quotedesk.domain.quotes.schedule import DepositState, ScheduleRequest, ScheduleSettings
from quotedesk.domain.services.schedule import civil_date, schedule

_ZONE = ZoneInfo("Africa/Johannesburg")


class CheckAvailability:
    def __init__(self, capacity: CapacityRepository, settings: ScheduleSettings, clock: Clock) -> None:
        self._capacity = capacity
        self._settings = settings
        self._clock = clock

    def execute(self, context: TenantContext | None, data: CheckAvailabilityInput) -> AvailabilityResult:
        if context is None:
            raise TenantRequired()
        at = self._clock.now()
        today = civil_date(at, _ZONE)
        kind = "earliest" if data.requested_date is None else "requested_date"
        request = ScheduleRequest(
            kind=kind,
            quote_issued=True,
            job_type=data.job_type,
            requested_date=data.requested_date,
        )
        capacity = self._capacity.get(context.tenant_id)
        result = schedule(
            request,
            capacity,
            self._settings,
            DepositState(paid=False),
            today=today,
            at=at,
        )
        return AvailabilityResult(
            status=result.commitment.status,
            earliest_window=result.commitment.earliest_window,
            sentence=result.commitment.sentence,
        )
