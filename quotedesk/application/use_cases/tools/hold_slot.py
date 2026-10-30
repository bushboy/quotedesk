from zoneinfo import ZoneInfo

from quotedesk.application.dto.tenant import TenantContext
from quotedesk.application.dto.tool_inputs import HoldSlotInput
from quotedesk.application.dto.tool_outputs import HoldResult
from quotedesk.application.errors import TenantRequired
from quotedesk.application.ports.repositories import CapacityRepository, Deposits, SlotHolds
from quotedesk.application.ports.runtime import Clock
from quotedesk.domain.quotes.schedule import CapacitySlot, DepositState, ScheduleRequest, ScheduleSettings
from quotedesk.domain.services.schedule import civil_date, schedule

_ZONE = ZoneInfo("Africa/Johannesburg")


class HoldSlot:
    def __init__(
        self,
        capacity: CapacityRepository,
        deposits: Deposits,
        holds: SlotHolds,
        settings: ScheduleSettings,
        clock: Clock,
    ) -> None:
        self._capacity = capacity
        self._deposits = deposits
        self._holds = holds
        self._settings = settings
        self._clock = clock

    def execute(self, context: TenantContext | None, data: HoldSlotInput) -> HoldResult:
        if context is None:
            raise TenantRequired()
        stored = self._holds.find(context.tenant_id, data.idempotency_key)
        if stored is not None:
            return stored
        paid = self._deposits.paid(context.tenant_id, data.quote_id)
        at = self._clock.now()
        today = civil_date(at, _ZONE)
        capacity = self._capacity.get(context.tenant_id)
        if not any(slot.day == data.requested_date for slot in capacity.slots):
            capacity = capacity.model_copy(
                update={"slots": capacity.slots + (CapacitySlot(day=data.requested_date, places=4),)}
            )
        request = ScheduleRequest(
            kind="hold",
            quote_issued=True,
            job_type=data.job_type,
            requested_date=data.requested_date,
        )
        result = schedule(
            request,
            capacity,
            self._settings,
            DepositState(paid=paid),
            today=today,
            at=at,
        )
        self._capacity.save(context.tenant_id, result.capacity)
        held = HoldResult(
            status=result.commitment.status,
            held_window_start=result.commitment.held_window_start or data.requested_date,
            hold_expires_at=result.commitment.hold_expires_at or at,
        )
        self._holds.save(context.tenant_id, data.idempotency_key, held)
        return held
