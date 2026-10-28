from datetime import date, datetime, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError as ModelError

from quotedesk.application.dto.tenant import TenantContext
from quotedesk.application.dto.tool_inputs import CreateDepositLinkInput
from quotedesk.application.errors import TenantRequired
from quotedesk.application.use_cases.tools.create_deposit_link import CreateDepositLink
from quotedesk.domain.policy.rules import Outcome
from quotedesk.domain.quotes.quote import Quote, QuoteState
from quotedesk.domain.shared.errors import PolicyViolation
from quotedesk.domain.shared.ids import QuoteId

TENANT = UUID("11111111-1111-4111-8111-111111111111")
WHEN = datetime(2026, 10, 24, 0, 0, tzinfo=timezone.utc)
QUOTE = QuoteId("QD-1042")
URL = "https://sandbox.payfast.example/deposit/QD-1042"
SENTENCE = "A deposit link follows an accepted issued quote."


def quote_in(outcome: Outcome) -> Quote:
    return Quote.open(QUOTE, date(2026, 11, 7)).issue(outcome, version=1, at=WHEN)


class Quotes:
    def __init__(self, quote: Quote) -> None:
        self.quote = quote
        self.reads = 0

    def get(self, tenant_id: UUID, conversation_id: UUID):
        return None

    def get_by_id(self, tenant_id: UUID, quote_id: QuoteId):
        self.reads += 1
        if tenant_id != TENANT or quote_id != QUOTE:
            return None
        return self.quote

    def save(self, tenant_id: UUID, conversation_id: UUID, quote: Quote) -> None:
        raise AssertionError("A deposit link does not save the quote.")


class Acceptances:
    def __init__(self, accepted: bool) -> None:
        self.accepted = accepted

    def has(self, tenant_id: UUID, quote_id: QuoteId, version: int) -> bool:
        return self.accepted


class Links:
    def __init__(self) -> None:
        self.rows = {}

    def find(self, tenant_id: UUID, idempotency_key: str):
        return self.rows.get((tenant_id, idempotency_key))

    def save(self, record) -> None:
        self.rows[(record.tenant_id, record.idempotency_key)] = record


def test_deposit_link_only_after_acceptance():
    quotes = Quotes(quote_in(Outcome.FIXED_OFFER))
    links = Links()
    tool = CreateDepositLink(quotes, Acceptances(True), links)
    data = CreateDepositLinkInput(quote_id=QUOTE, idempotency_key="deposit-1")
    with pytest.raises(TenantRequired):
        tool.execute(None, data)
    assert quotes.reads == 0
    opened = tool.execute(TenantContext(tenant_id=TENANT), data)
    assert opened.url == URL
    assert "payfast.co.za" not in opened.url
    again = tool.execute(TenantContext(tenant_id=TENANT), data)
    assert again.url == URL
    assert again == opened
    assert len(links.rows) == 1
    assert quotes.reads == 1
    refused = CreateDepositLink(Quotes(quote_in(Outcome.FIXED_OFFER)), Acceptances(False), Links())
    with pytest.raises(PolicyViolation) as missing:
        refused.execute(TenantContext(tenant_id=TENANT), data)
    assert missing.value.code == "policy.violation"
    assert str(missing.value) == SENTENCE
    assert refused._links.rows == {}
    for outcome in (Outcome.ESCALATION, Outcome.SITE_ASSESSMENT):
        denied = CreateDepositLink(Quotes(quote_in(outcome)), Acceptances(True), Links())
        with pytest.raises(PolicyViolation) as caught:
            denied.execute(TenantContext(tenant_id=TENANT), data)
        assert str(caught.value) == SENTENCE
        assert denied._links.rows == {}
        with pytest.raises(PolicyViolation):
            denied.execute(TenantContext(tenant_id=TENANT), data)
    stored = quote_in(Outcome.ESCALATION)
    assert stored.current.state is QuoteState.ESCALATED
    assessed = quote_in(Outcome.SITE_ASSESSMENT)
    assert assessed.current.state is QuoteState.SITE_ASSESSMENT_OFFERED
    with pytest.raises(ModelError):
        CreateDepositLinkInput(quote_id=QUOTE, idempotency_key="deposit-1", unit_price="1")
