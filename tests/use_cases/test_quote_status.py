from datetime import date, datetime, timezone
from uuid import UUID

import pytest

from quotedesk.application.dto.tenant import TenantContext
from quotedesk.application.dto.tool_inputs import GetQuoteStatusInput
from quotedesk.application.errors import TenantRequired
from quotedesk.application.use_cases.tools.get_quote_status import GetQuoteStatus
from quotedesk.domain.policy.rules import Outcome
from quotedesk.domain.quotes.quote import Quote, QuoteState
from quotedesk.domain.shared.ids import QuoteId

TENANT = UUID("11111111-1111-4111-8111-111111111111")
OTHER = UUID("22222222-2222-4222-8222-222222222222")
WHEN = datetime(2026, 10, 24, 0, 0, tzinfo=timezone.utc)
QUOTE = QuoteId("QD-1042")
OTHER_QUOTE = QuoteId("QD-1043")
EXPIRY = date(2026, 11, 7)


def issued(quote_id: QuoteId = QUOTE) -> Quote:
    return Quote.open(quote_id, EXPIRY).issue(Outcome.FIXED_OFFER, version=1, at=WHEN)


class Quotes:
    def __init__(self, rows: dict[tuple[UUID, QuoteId], Quote]) -> None:
        self.rows = rows
        self.reads: list[tuple[UUID, QuoteId]] = []
        self.saved = False

    def get(self, tenant_id: UUID, conversation_id: UUID) -> Quote | None:
        return None

    def get_by_id(self, tenant_id: UUID, quote_id: QuoteId) -> Quote | None:
        self.reads.append((tenant_id, quote_id))
        return self.rows.get((tenant_id, quote_id))

    def save(self, tenant_id: UUID, conversation_id: UUID, quote: Quote) -> None:
        self.saved = True


class Codes:
    def __init__(self) -> None:
        self.issued = 0
        self.book = {
            (TENANT, QUOTE): "1042",
            (TENANT, OTHER_QUOTE): "1043",
        }

    def issue(self, tenant_id: UUID, quote_id: QuoteId) -> str:
        self.issued += 1
        return self.book[(tenant_id, quote_id)]

    def matches(self, tenant_id: UUID, quote_id: QuoteId, code: str) -> bool:
        return self.book.get((tenant_id, quote_id)) == code


def test_status_requires_the_verification_code():
    expired = issued().transition(1, QuoteState.EXPIRED, at=WHEN)
    quotes = Quotes(
        {
            (TENANT, QUOTE): issued(),
            (TENANT, OTHER_QUOTE): issued(OTHER_QUOTE),
        }
    )
    codes = Codes()
    tool = GetQuoteStatus(quotes, codes)
    data = GetQuoteStatusInput(quote_id=QUOTE)
    with pytest.raises(TenantRequired):
        tool.execute(None, data)
    assert quotes.reads == []
    context = TenantContext(tenant_id=TENANT)
    wrong = tool.execute(context, GetQuoteStatusInput(quote_id=QUOTE, verification_code="0000"))
    missing = tool.execute(context, GetQuoteStatusInput(quote_id=QUOTE, verification_code=None))
    blank = tool.execute(context, GetQuoteStatusInput(quote_id=QUOTE, verification_code=""))
    other = tool.execute(context, GetQuoteStatusInput(quote_id=QUOTE, verification_code="1043"))
    absent = tool.execute(TenantContext(tenant_id=OTHER), GetQuoteStatusInput(quote_id=QUOTE, verification_code="1042"))
    padded = tool.execute(context, GetQuoteStatusInput(quote_id=QUOTE, verification_code="1042 "))
    assert wrong == missing == blank == other == absent == padded
    assert wrong.found is False
    assert wrong.state is None
    assert wrong.expiry is None
    assert wrong.version is None
    assert wrong.schedule_status is None
    opened = tool.execute(context, GetQuoteStatusInput(quote_id=QUOTE, verification_code="1042"))
    assert opened.found is True
    assert opened.state is QuoteState.ISSUED
    assert opened.expiry == EXPIRY
    assert opened.version == 1
    assert opened.schedule_status == "none"
    quotes.rows[(TENANT, QUOTE)] = expired
    lapsed = tool.execute(context, GetQuoteStatusInput(quote_id=QUOTE, verification_code="1042"))
    assert lapsed.found is True
    assert lapsed.state is QuoteState.EXPIRED
    assert lapsed.expiry == EXPIRY
    assert lapsed.version == 1
    assert lapsed.schedule_status == "none"
    assert codes.issued == 0
    assert quotes.saved is False
