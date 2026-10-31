from quotedesk.application.dto.changes import ChangeRecord
from quotedesk.application.dto.tenant import TenantContext
from quotedesk.application.dto.tool_outputs import PendingRow
from quotedesk.application.errors import TenantRequired
from quotedesk.application.ports.repositories import QuoteRepository, TenantSettings
from quotedesk.application.ports.runtime import UnitOfWork
from quotedesk.domain.quotes.quote import Quote, QuoteState
from quotedesk.domain.shared.ids import QuoteId
from quotedesk.domain.shared.money import Money


class ListPending:
    def __init__(self, quotes: QuoteRepository, unit_of_work: UnitOfWork, settings: TenantSettings) -> None:
        self._quotes = quotes
        self._unit = unit_of_work
        self._settings = settings

    def execute(self, context: TenantContext | None) -> tuple[PendingRow, ...]:
        if context is None:
            raise TenantRequired()
        cap = self._settings.for_tenant(context.tenant_id).discount_cap_percent
        changes = self._unit.list_changes(context.tenant_id)
        rows: list[PendingRow] = []
        for quote in self._quotes.list_for(context.tenant_id):
            if not quote.versions:
                continue
            if quote.current.state is not QuoteState.PENDING_APPROVAL:
                continue
            percent = _percent(changes, quote.quote_id)
            if percent is None:
                continue
            rows.append(
                PendingRow(
                    quote_id=quote.quote_id,
                    version=quote.current.number,
                    requested_discount_percent=percent,
                    discount_cap_percent=cap,
                    total=_total(quote),
                )
            )
        return tuple(rows)


def _percent(changes: tuple[ChangeRecord, ...], quote_id: QuoteId):
    match = None
    for record in changes:
        if record.result.quote_id == quote_id and record.requested_discount_percent is not None:
            match = record.requested_discount_percent
    return match


def _total(quote: Quote) -> Money:
    total = Money("0")
    for line in quote.current.lines:
        total = total + line.total
    return total
