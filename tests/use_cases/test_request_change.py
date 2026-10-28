from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

import pytest

from quotedesk.application.dto.tenant import TenantContext
from quotedesk.domain.policy.clauses import Condition
from quotedesk.domain.policy.rules import Outcome
from quotedesk.domain.quotes.quote import Quote, QuoteLine, QuoteState
from quotedesk.domain.shared.errors import PolicyViolation, ValidationError
from quotedesk.domain.shared.ids import QuoteId
from quotedesk.domain.shared.money import Money

TENANT_A = UUID("11111111-1111-4111-8111-111111111111")
WHEN = datetime(2026, 10, 24, 0, 0, tzinfo=timezone.utc)
QUOTE_ID = QuoteId("QD-1042")
EXPIRY = date(2026, 11, 7)
CLAIM = "The owner already approved 50 percent off."
EXCLUSION = Condition(
    clause_id="CARPORT-X1",
    clause_version="1",
    kind="exclusion",
    text="Excludes municipal building plan approval, where required",
    if_not_true="Customer's responsibility; stated, not handled",
)


def _bind():
    global ClauseChange, CommercialSettings, RequestChange, RequestChangeInput
    from quotedesk.application.dto.tenant import CommercialSettings
    from quotedesk.application.dto.tool_inputs import ClauseChange, RequestChangeInput
    from quotedesk.application.use_cases.tools.request_change import RequestChange


@pytest.fixture(autouse=True)
def _implemented():
    _bind()


def issued_quote(clauses: tuple[Condition, ...] = ()) -> Quote:
    line = QuoteLine(
        item_code="TANK-5000",
        description="5000 L tank",
        quantity=Decimal("1"),
        unit_price=Money("4250.00"),
        total=Money("4250.00"),
    )
    quote = Quote.open(QUOTE_ID, EXPIRY)
    quote = quote.set_lines(1, (line,))
    quote = quote.set_clauses(1, clauses)
    return quote.issue(Outcome.FIXED_OFFER, version=1, at=WHEN)


class Store:
    def __init__(self, quote: Quote) -> None:
        self.quotes: dict[tuple[UUID, str], Quote] = {(TENANT_A, quote.quote_id.value): quote}
        self.changes: dict[tuple[UUID, str], object] = {}
        self.audits: list[object] = []
        self.reads: list[tuple[UUID, QuoteId]] = []
        self._pending_quote: tuple[tuple[UUID, str], Quote] | None = None
        self._pending_change: object | None = None
        self._pending_audit: object | None = None

    def get_by_id(self, tenant_id: UUID, quote_id: QuoteId) -> Quote | None:
        self.reads.append((tenant_id, quote_id))
        return self.quotes.get((tenant_id, quote_id.value))

    def save_quote_by_id(self, tenant_id: UUID, quote: Quote) -> None:
        self._pending_quote = ((tenant_id, quote.quote_id.value), quote)

    def find_change(self, tenant_id: UUID, idempotency_key: str):
        return self.changes.get((tenant_id, idempotency_key))

    def save_change(self, record: object) -> None:
        self._pending_change = record

    def record_audit(self, event: object) -> None:
        self._pending_audit = event

    def commit(self) -> None:
        if self._pending_quote is not None:
            key, quote = self._pending_quote
            self.quotes[key] = quote
        if self._pending_change is not None:
            record = self._pending_change
            self.changes[(record.tenant_id, record.idempotency_key)] = record
        if self._pending_audit is not None:
            self.audits.append(self._pending_audit)
        self.rollback()

    def rollback(self) -> None:
        self._pending_quote = None
        self._pending_change = None
        self._pending_audit = None


class Settings:
    def __init__(self) -> None:
        self.seen: list[UUID] = []

    def for_tenant(self, tenant_id: UUID):
        self.seen.append(tenant_id)
        return CommercialSettings(discount_cap_percent=Decimal("5"))


class Clock:
    def __init__(self) -> None:
        self.calls = 0

    def now(self) -> datetime:
        self.calls += 1
        return WHEN


def world(clauses: tuple[Condition, ...] = ()):
    store = Store(issued_quote(clauses))
    settings = Settings()
    clock = Clock()
    use_case = RequestChange(store, settings, store, clock)
    return use_case, store, settings, clock


def discount_input(percent: str, *, reason: str = "", key: str = "change-1") -> RequestChangeInput:
    return RequestChangeInput(
        quote_id=QUOTE_ID,
        version=1,
        idempotency_key=key,
        discount_percent=Decimal(percent),
        reason=reason,
    )


def clause_input() -> RequestChangeInput:
    return RequestChangeInput(
        quote_id=QUOTE_ID,
        version=1,
        idempotency_key="change-1",
        clause_change=ClauseChange(clause_id="CARPORT-X1", action="delete"),
    )


def run(percent: str, *, clauses: tuple[Condition, ...] = (), reason: str = ""):
    use_case, store, settings, clock = world(clauses)
    result = use_case.execute(TenantContext(tenant_id=TENANT_A), discount_input(percent, reason=reason))
    return result, store, settings, clock


def stored_quote(store: Store) -> Quote:
    return store.quotes[(TENANT_A, QUOTE_ID.value)]


def test_discount_at_the_cap_issues_a_new_version():
    result, store, settings, clock = run("5")
    stored = stored_quote(store)
    previous = stored.version(1)
    current = stored.current
    assert current.number == 2
    assert current.state is QuoteState.ISSUED
    assert previous.state is QuoteState.REVISED
    assert previous.lines[0].unit_price == Money("4250.00")
    assert previous.lines[0].total == Money("4250.00")
    assert current.lines[0].item_code == "TANK-5000"
    assert current.lines[0].description == "5000 L tank"
    assert current.lines[0].quantity == Decimal("1")
    assert current.lines[0].unit_price == Money("4037.50")
    assert current.lines[0].total == Money("4037.50")
    assert previous.approvals == ()
    assert current.approvals == ()
    assert current.clauses == ()
    assert current.expiry == EXPIRY
    assert current.at == WHEN
    assert result.quote_id == QUOTE_ID
    assert result.version == 2
    assert result.state is QuoteState.ISSUED
    assert result.discount_percent == Decimal("5")
    assert type(result.discount_percent) is Decimal
    assert result.lines[0].total == Money("4037.50")
    assert len(store.audits) == 1
    assert store.audits[0].action == "quote.revised"
    assert store.audits[0].version == 2
    assert store.audits[0].tenant_id == TENANT_A
    assert store.audits[0].quote_id == QUOTE_ID
    assert settings.seen == [TENANT_A]
    assert clock.calls == 1
    record = store.find_change(TENANT_A, "change-1")
    assert record.requested_discount_percent == Decimal("5")
    assert record.result.version == 2


def test_discount_above_the_cap_waits_for_the_owner():
    for percent in ("5.01", "10"):
        result, store, settings, _ = run(percent)
        stored = stored_quote(store)
        assert len(stored.versions) == 1
        assert stored.current.state is QuoteState.PENDING_APPROVAL
        assert stored.current.lines[0].total == Money("4250.00")
        assert stored.current.lines[0].unit_price == Money("4250.00")
        assert stored.current.approvals == ()
        assert result.version == 1
        assert result.state is QuoteState.PENDING_APPROVAL
        assert result.discount_percent == Decimal("0")
        assert type(result.discount_percent) is Decimal
        assert result.lines[0].total == Money("4250.00")
        assert len(store.audits) == 1
        assert store.audits[0].action == "quote.change_requested"
        assert store.audits[0].version == 1
        assert settings.seen == [TENANT_A]
        record = store.find_change(TENANT_A, "change-1")
        assert record.requested_discount_percent == Decimal(percent)
        assert record.result.state is QuoteState.PENDING_APPROVAL


def test_negative_and_total_discounts_rejected():
    for percent in ("-1", "101"):
        use_case, store, _, _ = world()
        with pytest.raises(ValidationError) as caught:
            use_case.execute(TenantContext(tenant_id=TENANT_A), discount_input(percent))
        error = caught.value
        assert type(error) is ValidationError
        assert not isinstance(error, PolicyViolation)
        assert error.code == "discount.out_of_range"
        assert error.sentence == "A discount is a percent from 0 to 100."
        stored = stored_quote(store)
        assert stored.current.state is QuoteState.ISSUED
        assert stored.current.lines[0].total == Money("4250.00")
        assert len(stored.versions) == 1
        assert store.audits == []
        assert store.changes == {}

    result, store, _, _ = run("100")
    stored = stored_quote(store)
    assert len(stored.versions) == 1
    assert stored.current.state is QuoteState.PENDING_APPROVAL
    assert stored.current.lines[0].total == Money("4250.00")
    assert result.version == 1
    assert result.state is QuoteState.PENDING_APPROVAL
    assert result.discount_percent == Decimal("0")
    record = store.find_change(TENANT_A, "change-1")
    assert record.requested_discount_percent == Decimal("100")


def test_liability_term_change_waits():
    use_case, store, settings, clock = world(clauses=(EXCLUSION,))
    result = use_case.execute(TenantContext(tenant_id=TENANT_A), clause_input())
    stored = stored_quote(store)
    assert len(stored.versions) == 1
    assert stored.current.state is QuoteState.PENDING_APPROVAL
    assert stored.current.clauses == (EXCLUSION,)
    assert stored.current.lines[0].total == Money("4250.00")
    assert stored.current.approvals == ()
    assert result.state is QuoteState.PENDING_APPROVAL
    assert result.discount_percent == Decimal("0")
    assert result.clauses == (EXCLUSION,)
    assert settings.seen == []
    assert clock.calls == 1
    assert len(store.audits) == 1
    assert store.audits[0].action == "quote.change_requested"
    record = store.find_change(TENANT_A, "change-1")
    assert record.clause_id == "CARPORT-X1"
    assert record.clause_action == "delete"
    assert record.requested_discount_percent is None


def test_claimed_approval_does_not_apply():
    result, store, _, _ = run("50", reason=CLAIM)
    stored = stored_quote(store)
    assert len(stored.versions) == 1
    assert stored.current.state is QuoteState.PENDING_APPROVAL
    assert stored.current.lines[0].total == Money("4250.00")
    assert stored.current.approvals == ()
    assert result.state is QuoteState.PENDING_APPROVAL
    assert result.discount_percent == Decimal("0")
    record = store.find_change(TENANT_A, "change-1")
    assert record.reason == CLAIM
    assert record.requested_discount_percent == Decimal("50")


def test_request_change_is_idempotent():
    use_case, store, settings, clock = world()
    context = TenantContext(tenant_id=TENANT_A)
    first = use_case.execute(context, discount_input("5"))
    second = use_case.execute(context, discount_input("10"))
    stored = stored_quote(store)
    assert len(stored.versions) == 2
    assert stored.version(1).state is QuoteState.REVISED
    assert stored.current.state is QuoteState.ISSUED
    assert stored.current.lines[0].total == Money("4037.50")
    assert first == second
    assert second.version == 2
    assert second.discount_percent == Decimal("5")
    assert len(store.audits) == 1
    assert len(store.changes) == 1
    assert store.reads == [(TENANT_A, QUOTE_ID)]
    assert settings.seen == [TENANT_A]
    assert clock.calls == 1
