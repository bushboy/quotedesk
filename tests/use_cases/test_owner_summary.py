from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

import pytest

from quotedesk.application.dto.tenant import TenantContext
from quotedesk.application.errors import TenantRequired
from quotedesk.application.use_cases.operator.owner_summary import SummariseForOwner, period_bounds
from quotedesk.application.use_cases.operator.spoken import rand_words
from quotedesk.domain.policy.rules import Outcome
from quotedesk.domain.quotes.quote import Quote, QuoteLine, QuoteState
from quotedesk.domain.shared.ids import QuoteId
from quotedesk.domain.shared.money import Money

TENANT = UUID("11111111-1111-4111-8111-111111111111")
OTHER = UUID("22222222-2222-4222-8222-222222222222")
CONVERSATION = UUID("33333333-3333-4333-8333-333333333333")
NOW = datetime(2026, 11, 2, 10, 0, tzinfo=timezone.utc)


class Clock:
    def now(self) -> datetime:
        return NOW


class Reads:
    def __init__(self, messages=(), threads=(), inspections=(), handovers=(), held=(), pending=()):
        self._messages, self._threads, self._inspections = messages, threads, inspections
        self._handovers, self._held, self._pending = handovers, set(held), pending

    def messages(self, tenant_id):
        return [m for t, m in self._messages if t == tenant_id]

    def quote_threads(self, tenant_id):
        return [(c, q) for t, c, q in self._threads if t == tenant_id]

    def inspections(self, tenant_id):
        return [i for t, i in self._inspections if t == tenant_id]

    def handovers(self, tenant_id):
        return [h for t, h in self._handovers if t == tenant_id]

    def held(self, tenant_id, conversation_id):
        return (tenant_id, conversation_id) in self._held

    def pending(self, context):
        return tuple(p for t, p in self._pending if t == context.tenant_id)


def fixed(quote_id: str, amount: str, at: datetime, state=QuoteState.WAITING_FOR_DEPOSIT, deposit: str | None = None) -> Quote:
    line = QuoteLine(item_code="TANK-5000", description="5000 L tank", quantity=Decimal("1"), unit_price=Money(amount), total=Money(amount))
    quote = Quote.open(QuoteId(quote_id), date(2026, 11, 16)).set_lines(1, (line,))
    if deposit is not None:
        quote = quote.set_terms(1, price_type="fixed", range_min=None, range_max=None, deposit=Money(deposit), site_visit_fee=None)
    quote = quote.issue(Outcome.FIXED_OFFER, version=1, at=at)
    if state is QuoteState.ISSUED:
        return quote
    if state is QuoteState.DEPOSIT_PAID:
        quote = quote.transition(1, QuoteState.WAITING_FOR_DEPOSIT, at=at)
    return quote.transition(1, state, at=at)


def ranged(quote_id: str, low: str, high: str, at: datetime) -> Quote:
    quote = Quote.open(QuoteId(quote_id), date(2026, 11, 16))
    quote = quote.set_terms(1, price_type="range", range_min=Money(low), range_max=Money(high), deposit=None, site_visit_fee=None)
    return quote.issue(Outcome.INDICATIVE_RANGE, version=1, at=at)


def message(wa_id: str, at: datetime):
    return SimpleNamespace(wa_id=wa_id, at=at)


def run(reads: Reads, period="today", tenant=TENANT):
    return SummariseForOwner(reads, Clock()).execute(TenantContext(tenant_id=tenant), period)


@pytest.mark.parametrize(
    ("amount", "words"),
    [
        ("0", "zero rand"),
        ("1", "one rand"),
        ("1000", "one thousand rand"),
        ("16650.50", "sixteen thousand six hundred and fifty rand and fifty cents"),
        ("1050", "one thousand and fifty rand"),
        ("4995", "four thousand nine hundred and ninety-five rand"),
    ],
)
def test_rand_amounts_are_spoken_in_words(amount, words):
    assert rand_words(Decimal(amount)) == words


def test_today_is_the_sast_calendar_day():
    start, end = period_bounds("today", datetime(2026, 11, 1, 22, 30, tzinfo=timezone.utc))
    assert start == datetime(2026, 11, 1, 22, 0, tzinfo=timezone.utc)
    assert end - start == timedelta(days=1)


def test_a_known_day_reads_as_one_paragraph():
    hour = NOW - timedelta(hours=1)
    reads = Reads(
        messages=[(TENANT, message("2782", hour)), (TENANT, message("2782", hour)), (TENANT, message("2783", hour))],
        threads=[
            (TENANT, CONVERSATION, fixed("QD-1001", "5550.00", hour, deposit="1665.00")),
            (TENANT, CONVERSATION, fixed("QD-1002", "11100.00", hour, deposit="3330.00")),
        ],
    )
    found = run(reads)
    assert (found.customers, found.messages, found.quotes_sent) == (2, 3, 2)
    assert found.quoted_value == Money("16650.00")
    assert found.deposits_due == Money("4995.00")
    assert found.spoken == (
        "Today, 2 customers wrote in, with 3 messages. "
        "2 quotes went out, worth sixteen thousand six hundred and fifty rand. "
        "Deposits of four thousand nine hundred and ninety-five rand are due. "
        "No inspections were offered or booked. "
        "Nothing is waiting for you."
    )
    assert "R " not in found.spoken


def test_a_range_counts_at_its_lowest_figure_not_zero():
    found = run(Reads(threads=[(TENANT, CONVERSATION, ranged("QD-1003", "12600.00", "18200.00", NOW))]))
    assert found.quoted_value == Money("12600.00")
    assert found.ranges == 1
    assert "twelve thousand six hundred rand" in found.lines.quotes


def test_another_tenant_never_shows():
    reads = Reads(
        messages=[(OTHER, message("2799", NOW))],
        threads=[(OTHER, CONVERSATION, fixed("QD-1009", "999.00", NOW))],
        handovers=[(OTHER, SimpleNamespace(conversation_id=CONVERSATION, at=NOW))],
        held=[(OTHER, CONVERSATION)],
    )
    found = run(reads)
    assert (found.customers, found.quotes_sent, found.handovers_waiting) == (0, 0, 0)
    assert run(reads, tenant=OTHER).quotes_sent == 1


def test_an_empty_day_is_all_zeros():
    found = run(Reads())
    assert (found.customers, found.messages, found.quotes_sent, found.deposits_paid) == (0, 0, 0, 0)
    assert found.quoted_value == Money("0")
    assert found.spoken.startswith("Today, no customers wrote in.")


def test_yesterday_leaves_out_today():
    found = run(Reads(messages=[(TENANT, message("2782", NOW))]), period="yesterday")
    assert found.customers == 0
    assert found.label == "Yesterday"


def test_waiting_counts_held_callbacks_and_says_since_when_without_names():
    waited = datetime(2026, 11, 2, 7, 40, tzinfo=timezone.utc)
    reads = Reads(
        handovers=[(TENANT, SimpleNamespace(conversation_id=CONVERSATION, at=waited))],
        held=[(TENANT, CONVERSATION)],
        pending=[(TENANT, object())],
    )
    found = run(reads)
    assert (found.handovers_waiting, found.approvals_waiting) == (1, 1)
    assert found.lines.waiting == "Waiting for you: 1 customer to call back and 1 discount to approve. The oldest has waited since 9:40."


def test_a_paid_deposit_counts_on_the_day_it_was_paid():
    found = run(Reads(threads=[(TENANT, CONVERSATION, fixed("QD-1004", "4250.00", NOW, state=QuoteState.DEPOSIT_PAID))]))
    assert found.deposits_paid == 1


def test_no_tenant_is_refused():
    with pytest.raises(TenantRequired):
        SummariseForOwner(Reads(), Clock()).execute(None)
