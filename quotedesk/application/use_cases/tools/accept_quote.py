from quotedesk.application.dto.tenant import TenantContext
from quotedesk.application.dto.tool_inputs import AcceptQuoteInput
from quotedesk.application.dto.tool_outputs import AcceptQuoteResult
from quotedesk.application.errors import QuoteNotFound, TenantRequired
from quotedesk.application.ports.runtime import Clock, UnitOfWork
from quotedesk.domain.quotes.quote import QuoteState
from quotedesk.domain.shared.errors import PolicyViolation

_SENTENCE = "Only an issued quote can be accepted."


class AcceptQuote:
    def __init__(self, quotes, acceptances, unit_of_work: UnitOfWork, clock: Clock) -> None:
        self._quotes = quotes
        self._acceptances = acceptances
        self._unit = unit_of_work
        self._clock = clock

    def execute(self, context: TenantContext | None, data: AcceptQuoteInput) -> AcceptQuoteResult:
        if context is None:
            raise TenantRequired()
        quote = self._quotes.get_by_id(context.tenant_id, data.quote_id)
        if quote is None:
            raise QuoteNotFound()
        current = quote.current
        if current.state is QuoteState.WAITING_FOR_DEPOSIT and self._acceptances.has(
            context.tenant_id, data.quote_id, current.number
        ):
            return _result(quote)
        if current.state is not QuoteState.ISSUED:
            raise PolicyViolation(code="policy.violation", sentence=_SENTENCE)
        at = self._clock.now()
        moved = quote.transition(current.number, QuoteState.WAITING_FOR_DEPOSIT, at=at)
        self._acceptances.record(context.tenant_id, data.quote_id, current.number, at)
        try:
            self._unit.save_quote_by_id(context.tenant_id, moved)
            self._unit.commit()
        except Exception:
            self._unit.rollback()
            raise
        return _result(moved)


def _result(quote) -> AcceptQuoteResult:
    current = quote.current
    return AcceptQuoteResult(quote_id=quote.quote_id, version=current.number, state=current.state)
