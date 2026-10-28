from datetime import datetime
from decimal import Decimal

from quotedesk.application.dto.audit import AuditEvent
from quotedesk.application.dto.changes import ChangeRecord
from quotedesk.application.dto.tenant import TenantContext
from quotedesk.application.dto.tool_inputs import RequestChangeInput
from quotedesk.application.dto.tool_outputs import RequestChangeResult
from quotedesk.application.errors import QuoteNotFound, TenantRequired
from quotedesk.application.ports.repositories import QuoteRepository, TenantSettings
from quotedesk.application.ports.runtime import Clock, UnitOfWork
from quotedesk.domain.policy.rules import Outcome
from quotedesk.domain.quotes.quote import Quote, QuoteLine, QuoteState
from quotedesk.domain.shared.errors import StaleQuote, ValidationError
from quotedesk.domain.shared.money import Money

_HUNDRED = Decimal("100")
_ZERO = Decimal("0")
_OUT_OF_RANGE = "A discount is a percent from 0 to 100."
_STALE = "That version is no longer the current quote."


class RequestChange:
    def __init__(
        self,
        quotes: QuoteRepository,
        settings: TenantSettings,
        unit_of_work: UnitOfWork,
        clock: Clock,
    ) -> None:
        self._quotes = quotes
        self._settings = settings
        self._unit = unit_of_work
        self._clock = clock

    def execute(self, context: TenantContext | None, data: RequestChangeInput) -> RequestChangeResult:
        if context is None:
            raise TenantRequired()
        existing = self._unit.find_change(context.tenant_id, data.idempotency_key)
        if existing is not None:
            return existing.result
        quote = self._quotes.get_by_id(context.tenant_id, data.quote_id)
        if quote is None:
            raise QuoteNotFound()
        if data.version != quote.current.number:
            raise StaleQuote(code="quote.stale", sentence=_STALE)
        if data.discount_percent is not None:
            percent = data.discount_percent
            if percent < _ZERO or percent > _HUNDRED:
                raise ValidationError(code="discount.out_of_range", sentence=_OUT_OF_RANGE)
            cap = self._settings.for_tenant(context.tenant_id).discount_cap_percent
            at = self._clock.now()
            if percent <= cap:
                quote = _issue(quote, percent, at)
                applied = percent
                action = "quote.revised"
            else:
                quote = quote.transition(data.version, QuoteState.PENDING_APPROVAL, at=at)
                applied = _ZERO
                action = "quote.change_requested"
            requested = percent
            clause_id = None
            clause_action = None
        else:
            change = data.clause_change
            assert change is not None
            at = self._clock.now()
            quote = quote.transition(data.version, QuoteState.PENDING_APPROVAL, at=at)
            applied = _ZERO
            action = "quote.change_requested"
            requested = None
            clause_id = change.clause_id
            clause_action = change.action
        current = quote.current
        result = RequestChangeResult(
            quote_id=quote.quote_id,
            version=current.number,
            state=current.state,
            discount_percent=applied,
            lines=current.lines,
            clauses=current.clauses,
        )
        record = ChangeRecord(
            tenant_id=context.tenant_id,
            idempotency_key=data.idempotency_key,
            requested_discount_percent=requested,
            clause_id=clause_id,
            clause_action=clause_action,
            reason=data.reason,
            result=result,
        )
        event = AuditEvent(
            tenant_id=context.tenant_id,
            action=action,
            quote_id=quote.quote_id,
            version=current.number,
        )
        try:
            self._unit.save_quote_by_id(context.tenant_id, quote)
            self._unit.save_change(record)
            self._unit.record_audit(event)
            self._unit.commit()
        except Exception:
            self._unit.rollback()
            raise
        return result


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
