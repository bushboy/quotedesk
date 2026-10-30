from quotedesk.application.dto.changes import DepositLinkRecord
from quotedesk.application.dto.tenant import TenantContext
from quotedesk.application.dto.tool_inputs import CreateDepositLinkInput
from quotedesk.application.dto.tool_outputs import DepositLinkResult
from quotedesk.application.errors import QuoteNotFound, TenantRequired
from quotedesk.application.ports.repositories import Acceptances, DepositLinks, QuoteRepository
from quotedesk.domain.quotes.quote import QuoteState
from quotedesk.domain.shared.errors import PolicyViolation

_SENTENCE = "A deposit link follows an accepted issued quote."
_HOST = "https://sandbox.payfast.example/deposit"


class CreateDepositLink:
    def __init__(self, quotes: QuoteRepository, acceptances: Acceptances, links: DepositLinks) -> None:
        self._quotes = quotes
        self._acceptances = acceptances
        self._links = links

    def execute(self, context: TenantContext | None, data: CreateDepositLinkInput) -> DepositLinkResult:
        if context is None:
            raise TenantRequired()
        stored = self._links.find(context.tenant_id, data.idempotency_key)
        if stored is not None:
            return DepositLinkResult(url=stored.url)
        quote = self._quotes.get_by_id(context.tenant_id, data.quote_id)
        if quote is None:
            raise QuoteNotFound()
        current = quote.current
        accepted = current.state in (QuoteState.ISSUED, QuoteState.WAITING_FOR_DEPOSIT) and self._acceptances.has(
            context.tenant_id, data.quote_id, current.number
        )
        if not accepted:
            raise PolicyViolation(code="policy.violation", sentence=_SENTENCE)
        url = f"{_HOST}/{data.quote_id.value}"
        self._links.save(
            DepositLinkRecord(
                tenant_id=context.tenant_id,
                idempotency_key=data.idempotency_key,
                quote_id=data.quote_id,
                url=url,
            )
        )
        return DepositLinkResult(url=url)
