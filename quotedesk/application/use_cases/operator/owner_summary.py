"""The owner's numbers for a period. It reads quotes and messages and never writes either."""

from collections.abc import Iterable
from datetime import datetime, time, timedelta, timezone
from typing import Protocol
from uuid import UUID

from quotedesk.application.dto.owner_summary import OwnerSummary, Period, SummaryLines
from quotedesk.application.dto.tenant import TenantContext
from quotedesk.application.errors import TenantRequired
from quotedesk.application.ports.runtime import Clock
from quotedesk.application.use_cases.operator.spoken import plural, rand_words, spoken_time
from quotedesk.domain.quotes.quote import Quote, QuoteState, QuoteVersion
from quotedesk.domain.shared.money import Money

_SAST = timezone(timedelta(hours=2))
_LABELS: dict[str, str] = {"today": "Today", "yesterday": "Yesterday", "week": "This week"}
_DUE = {QuoteState.ISSUED, QuoteState.WAITING_FOR_DEPOSIT}
_PAID = {QuoteState.DEPOSIT_PAID, QuoteState.BOOKING_CONFIRMED}


class OwnerReads(Protocol):
    """What the summary reads. Every method is scoped to one tenant."""

    def messages(self, tenant_id: UUID) -> Iterable: ...

    def quote_threads(self, tenant_id: UUID) -> Iterable[tuple[UUID, Quote]]: ...

    def inspections(self, tenant_id: UUID) -> Iterable: ...

    def handovers(self, tenant_id: UUID) -> Iterable: ...

    def held(self, tenant_id: UUID, conversation_id: UUID) -> bool: ...

    def pending(self, context: TenantContext) -> tuple: ...


def period_bounds(period: Period, now: datetime) -> tuple[datetime, datetime]:
    """The start and end of a period as SAST calendar days, returned in UTC."""
    local = now.astimezone(_SAST).date()
    if period == "yesterday":
        first, last = local - timedelta(days=1), local
    elif period == "week":
        first, last = local - timedelta(days=local.weekday()), local + timedelta(days=1)
    else:
        first, last = local, local + timedelta(days=1)
    start = datetime.combine(first, time(0), tzinfo=_SAST).astimezone(timezone.utc)
    end = datetime.combine(last, time(0), tzinfo=_SAST).astimezone(timezone.utc)
    return start, end


def quote_value(version: QuoteVersion) -> tuple[Money, bool]:
    """A fixed quote counts its lines. A range counts its lowest figure, never R 0.00."""
    if version.lines:
        amount = Money("0")
        for line in version.lines:
            amount = amount + line.total
        return amount, False
    if version.range_min is not None:
        return version.range_min, True
    if version.range_max is not None:
        return version.range_max, True
    return Money("0"), False


def first_sent(quote: Quote) -> datetime | None:
    sent = [version.at for version in quote.versions if version.state is not QuoteState.DRAFT and version.at]
    return min(sent) if sent else None


class SummariseForOwner:
    def __init__(self, reads: OwnerReads, clock: Clock) -> None:
        self._reads = reads
        self._clock = clock

    def execute(self, context: TenantContext | None, period: Period = "today") -> OwnerSummary:
        if context is None:
            raise TenantRequired()
        tenant = context.tenant_id
        if period not in _LABELS:
            period = "today"
        start, end = period_bounds(period, self._clock.now())

        def inside(at: datetime | None) -> bool:
            return at is not None and start <= at < end

        heard = [message for message in self._reads.messages(tenant) if inside(message.at)]
        customers = len({message.wa_id for message in heard})

        sent = 0
        ranges = 0
        value = Money("0")
        due = Money("0")
        paid = 0
        for _conversation_id, quote in self._reads.quote_threads(tenant):
            if not quote.versions:
                continue
            current = quote.current
            if inside(first_sent(quote)):
                sent += 1
                amount, is_range = quote_value(current)
                value = value + amount
                ranges += 1 if is_range else 0
                if current.state in _DUE and current.deposit is not None:
                    due = due + current.deposit
            if current.state in _PAID and inside(current.at):
                paid += 1

        offered = 0
        booked = 0
        waits: list[datetime] = []
        for item in self._reads.inspections(tenant):
            status = getattr(item.status, "value", item.status)
            if status == "offered" and inside(item.at):
                offered += 1
            if status == "booked" and inside(item.at):
                booked += 1

        handovers = 0
        for note in self._reads.handovers(tenant):
            if self._reads.held(tenant, note.conversation_id):
                handovers += 1
                waits.append(note.at)
        approvals = len(self._reads.pending(context))
        oldest = min(waits) if waits else None

        label = _LABELS[period]
        lines = _lines(period, customers, len(heard), sent, value, ranges, due, paid, offered, booked, handovers, approvals, oldest)
        return OwnerSummary(
            period=period,
            label=label,
            start=start,
            end=end,
            customers=customers,
            messages=len(heard),
            quotes_sent=sent,
            quoted_value=value,
            ranges=ranges,
            deposits_due=due,
            deposits_paid=paid,
            inspections_offered=offered,
            inspections_booked=booked,
            handovers_waiting=handovers,
            approvals_waiting=approvals,
            oldest_wait=oldest,
            lines=lines,
            spoken=" ".join(
                (
                    f"{label}, {_lowered(lines.enquiries)}",
                    lines.quotes,
                    lines.deposits,
                    lines.inspections,
                    lines.waiting,
                )
            ),
        )


def _lowered(sentence: str) -> str:
    if sentence.startswith("No "):
        return "no " + sentence[3:]
    return sentence


def _lines(period, customers, messages, sent, value, ranges, due, paid, offered, booked, handovers, approvals, oldest) -> SummaryLines:
    past = period != "today"
    if customers == 0:
        enquiries = "No customers wrote in."
    else:
        wrote = "wrote in" if customers > 1 or past else "wrote in"
        enquiries = f"{plural(customers, 'customer', 'customers')} {wrote}, with {plural(messages, 'message', 'messages')}."
    if sent == 0:
        quotes = "No quotes went out."
    else:
        went = "quote went out" if sent == 1 else "quotes went out"
        quotes = f"{sent} {went}, worth {rand_words(value.amount)}."
        if ranges:
            quotes += f" {plural(ranges, 'price range is', 'price ranges are')} counted at the lowest figure."
    if due.amount == 0 and paid == 0:
        deposits = "No deposits are due."
    elif paid == 0:
        deposits = f"Deposits of {rand_words(due.amount)} are due."
    else:
        paid_text = plural(paid, "deposit was paid", "deposits were paid")
        deposits = f"Deposits of {rand_words(due.amount)} are due, and {paid_text}." if due.amount else f"{paid_text[0].upper()}{paid_text[1:]}."
    if offered == 0 and booked == 0:
        inspections = "No inspections were offered or booked."
    else:
        inspections = f"{plural(offered, 'inspection was', 'inspections were')} offered and {booked} booked."
    total = handovers + approvals
    if total == 0:
        waiting = "Nothing is waiting for you."
    else:
        parts = []
        if handovers:
            parts.append(plural(handovers, "customer to call back", "customers to call back"))
        if approvals:
            parts.append(plural(approvals, "discount to approve", "discounts to approve"))
        waiting = f"Waiting for you: {' and '.join(parts)}."
        if oldest is not None:
            waiting += f" The oldest has waited since {spoken_time(oldest)}."
    return SummaryLines(enquiries=enquiries, quotes=quotes, deposits=deposits, inspections=inspections, waiting=waiting)
