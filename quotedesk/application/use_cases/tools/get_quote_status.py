from quotedesk.application.dto.tenant import TenantContext
from quotedesk.application.dto.tool_inputs import GetQuoteStatusInput
from quotedesk.application.dto.tool_outputs import QuoteStatusResult
from quotedesk.application.errors import TenantRequired
from quotedesk.application.ports.repositories import QuoteRepository, VerificationCodes

_EMPTY = QuoteStatusResult(found=False, state=None, expiry=None, version=None, schedule_status=None)


class GetQuoteStatus:
    def __init__(self, quotes: QuoteRepository, codes: VerificationCodes) -> None:
        self._quotes = quotes
        self._codes = codes

    def execute(self, context: TenantContext | None, data: GetQuoteStatusInput) -> QuoteStatusResult:
        if context is None:
            raise TenantRequired()
        if data.verification_code is None or data.verification_code == "":
            return _EMPTY
        quote = self._quotes.get_by_id(context.tenant_id, data.quote_id)
        if quote is None:
            return _EMPTY
        if not self._codes.matches(context.tenant_id, data.quote_id, data.verification_code):
            return _EMPTY
        current = quote.current
        return QuoteStatusResult(
            found=True,
            state=current.state,
            expiry=current.expiry,
            version=current.number,
            schedule_status="none",
        )
