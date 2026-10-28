from decimal import Decimal

from quotedesk.application.dto.audit import AuditEvent
from quotedesk.application.dto.tenant import TenantContext
from quotedesk.application.dto.tool_inputs import RejectExceptionInput
from quotedesk.application.dto.tool_outputs import ApproveResult
from quotedesk.application.errors import QuoteNotFound, TenantRequired
from quotedesk.application.ports.repositories import QuoteRepository
from quotedesk.application.ports.runtime import Clock, UnitOfWork
from quotedesk.domain.quotes.quote import QuoteState
from quotedesk.domain.shared.errors import PolicyViolation, StaleQuote

_WAITING = "That quote is not waiting for approval."
_STALE = "That version is no longer the current quote."
_ZERO = Decimal("0")


class RejectException:
    def __init__(self, quotes: QuoteRepository, unit_of_work: UnitOfWork, clock: Clock) -> None:
        self._quotes = quotes
        self._unit = unit_of_work
        self._clock = clock

    def execute(self, context: TenantContext | None, data: RejectExceptionInput) -> ApproveResult:
        if context is None:
            raise TenantRequired()
        existing = self._unit.find_operator_result(context.tenant_id, data.idempotency_key)
        if existing is not None:
            return existing
        quote = self._quotes.get_by_id(context.tenant_id, data.quote_id)
        if quote is None:
            raise QuoteNotFound()
        if quote.current.state is not QuoteState.PENDING_APPROVAL:
            raise PolicyViolation(code="policy.violation", sentence=_WAITING)
        if data.version != quote.current.number:
            raise StaleQuote(code="quote.stale", sentence=_STALE)
        at = self._clock.now()
        quote = quote.transition(data.version, QuoteState.ISSUED, at=at)
        current = quote.current
        result = ApproveResult(
            quote_id=quote.quote_id,
            version=current.number,
            state=current.state,
            discount_percent=_ZERO,
            lines=current.lines,
        )
        event = AuditEvent(
            tenant_id=context.tenant_id,
            action="quote.change_rejected",
            quote_id=quote.quote_id,
            version=current.number,
            actor="owner",
            at=at,
        )
        try:
            self._unit.save_quote_by_id(context.tenant_id, quote)
            self._unit.save_operator_result(context.tenant_id, data.idempotency_key, result)
            self._unit.record_audit(event)
            self._unit.commit()
        except Exception:
            self._unit.rollback()
            raise
        return result
