from datetime import datetime
from decimal import Decimal

from quotedesk.application.dto.audit import AuditEvent
from quotedesk.application.dto.changes import ChangeRecord
from quotedesk.application.dto.tenant import TenantContext
from quotedesk.application.dto.tool_inputs import ApproveExceptionInput
from quotedesk.application.dto.tool_outputs import ApproveResult
from quotedesk.application.errors import QuoteNotFound, TenantRequired
from quotedesk.application.ports.repositories import QuoteRepository
from quotedesk.application.ports.runtime import Clock, UnitOfWork
from quotedesk.domain.policy.rules import Outcome
from quotedesk.domain.quotes.quote import Approval, Quote, QuoteLine, QuoteState
from quotedesk.domain.shared.errors import PolicyViolation, StaleQuote
from quotedesk.domain.shared.ids import QuoteId
from quotedesk.domain.shared.money import Money

_HUNDRED = Decimal("100")
_WAITING = "That quote is not waiting for approval."
_NO_DISCOUNT = "That request has no discount to approve."
_STALE = "That version is no longer the current quote."


class ApproveException:
    def __init__(self, quotes: QuoteRepository, unit_of_work: UnitOfWork, clock: Clock) -> None:
        self._quotes = quotes
        self._unit = unit_of_work
        self._clock = clock

    def execute(self, context: TenantContext | None, data: ApproveExceptionInput) -> ApproveResult:
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
        percent = _requested_percent(self._unit.list_changes(context.tenant_id), data.quote_id)
        at = self._clock.now()
        approval = Approval(applies_to_version=data.version, expires_at=data.expires_at)
        quote = quote.apply_approval(data.version, approval, at=at)
        quote = _issue(quote, percent, at)
        current = quote.current
        result = ApproveResult(
            quote_id=quote.quote_id,
            version=current.number,
            state=current.state,
            discount_percent=percent,
            lines=current.lines,
        )
        event = AuditEvent(
            tenant_id=context.tenant_id,
            action="quote.approved",
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


def _requested_percent(changes: tuple[ChangeRecord, ...], quote_id: QuoteId) -> Decimal:
    match = None
    for record in changes:
        if record.result.quote_id == quote_id and record.requested_discount_percent is not None:
            match = record
    if match is None or match.requested_discount_percent is None:
        raise PolicyViolation(code="policy.violation", sentence=_NO_DISCOUNT)
    return match.requested_discount_percent


def _issue(quote: Quote, percent: Decimal, at: datetime) -> Quote:
    current = quote.current
    lines = tuple(
        QuoteLine(
            item_code=line.item_code,
            description=line.description,
            quantity=line.quantity,
            unit_price=_reduce(line.unit_price, percent),
            total=_reduce(line.total, percent),
        )
        for line in current.lines
    )
    return quote.revise(
        Outcome.FIXED_OFFER,
        line_items=lines,
        clauses=current.clauses,
        expiry=current.expiry,
        at=at,
    )


def _reduce(amount: Money, percent: Decimal) -> Money:
    reduced = (amount.amount * (_HUNDRED - percent)) / _HUNDRED
    return Money(reduced)
