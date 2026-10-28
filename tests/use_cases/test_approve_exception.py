from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

import pytest

from quotedesk.application.dto.audit import AuditEvent
from quotedesk.application.dto.changes import ChangeRecord
from quotedesk.application.dto.tenant import CommercialSettings, TenantContext
from quotedesk.application.dto.tool_inputs import ApproveExceptionInput, RejectExceptionInput
from quotedesk.application.dto.tool_outputs import RequestChangeResult
from quotedesk.application.use_cases.operator.approve_exception import ApproveException
from quotedesk.application.use_cases.operator.audit_timeline import AuditTimeline
from quotedesk.application.use_cases.operator.list_pending import ListPending
from quotedesk.application.use_cases.operator.reject_exception import RejectException
from quotedesk.domain.policy.clauses import Condition
from quotedesk.domain.policy.rules import Outcome
from quotedesk.domain.quotes.quote import Quote, QuoteLine, QuoteState
from quotedesk.domain.shared.errors import PolicyViolation
from quotedesk.domain.shared.ids import QuoteId
from quotedesk.domain.shared.money import Money

TENANT_A = UUID("11111111-1111-4111-8111-111111111111")
TENANT_B = UUID("22222222-2222-4222-8222-222222222222")
CONVERSATION = UUID("33333333-3333-4333-8333-333333333333")
WHEN = datetime(2026, 11, 1, 8, 0, tzinfo=timezone.utc)
ISSUED_AT = datetime(2026, 10, 24, 0, 0, tzinfo=timezone.utc)
EXPIRY = date(2026, 11, 7)
QUOTE_A = QuoteId("QD-1042")
QUOTE_B = QuoteId("QD-2042")
EXCLUSION = Condition(
    clause_id="CARPORT-X1",
    clause_version="1",
    kind="exclusion",
    text="Excludes municipal building plan approval, where required",
    if_not_true="Customer's responsibility; stated, not handled",
)


def pending_quote(quote_id: QuoteId, clauses: tuple[Condition, ...] = ()) -> Quote:
    line = QuoteLine(
        item_code="TANK-5000",
        description="5000 L tank",
        quantity=Decimal("1"),
        unit_price=Money("4250.00"),
        total=Money("4250.00"),
    )
    quote = Quote.open(quote_id, EXPIRY)
    quote = quote.set_lines(1, (line,))
    quote = quote.set_clauses(1, clauses)
    quote = quote.issue(Outcome.FIXED_OFFER, version=1, at=ISSUED_AT)
    return quote.transition(1, QuoteState.PENDING_APPROVAL, at=ISSUED_AT)


def change_for(tenant_id: UUID, quote: Quote, percent: str = "10") -> ChangeRecord:
    current = quote.current
    return ChangeRecord(
        tenant_id=tenant_id,
        idempotency_key="change-1",
        requested_discount_percent=Decimal(percent),
        result=RequestChangeResult(
            quote_id=quote.quote_id,
            version=current.number,
            state=current.state,
            discount_percent=Decimal("0"),
            lines=current.lines,
            clauses=current.clauses,
        ),
    )


class Store:
    def __init__(self) -> None:
        self.quotes: dict[tuple[UUID, str], Quote] = {}
        self.changes: dict[UUID, list[ChangeRecord]] = {}
        self.results: dict[tuple[UUID, str], object] = {}
        self.audits: list[AuditEvent] = []
        self._pending_quote: tuple[tuple[UUID, str], Quote] | None = None
        self._pending_result: tuple[tuple[UUID, str], object] | None = None
        self._pending_audit: AuditEvent | None = None

    def add(self, tenant_id: UUID, quote: Quote, percent: str = "10") -> None:
        self.quotes[(tenant_id, quote.quote_id.value)] = quote
        self.changes.setdefault(tenant_id, []).append(change_for(tenant_id, quote, percent))

    def get_by_id(self, tenant_id: UUID, quote_id: QuoteId) -> Quote | None:
        return self.quotes.get((tenant_id, quote_id.value))

    def list_for(self, tenant_id: UUID) -> tuple[Quote, ...]:
        return tuple(quote for (tenant, _), quote in self.quotes.items() if tenant == tenant_id)

    def save_quote_by_id(self, tenant_id: UUID, quote: Quote) -> None:
        self._pending_quote = ((tenant_id, quote.quote_id.value), quote)

    def find_operator_result(self, tenant_id: UUID, idempotency_key: str):
        return self.results.get((tenant_id, idempotency_key))

    def save_operator_result(self, tenant_id: UUID, idempotency_key: str, result: object) -> None:
        self._pending_result = ((tenant_id, idempotency_key), result)

    def list_changes(self, tenant_id: UUID) -> tuple[ChangeRecord, ...]:
        return tuple(self.changes.get(tenant_id, ()))

    def list_audits(self, tenant_id: UUID) -> tuple[AuditEvent, ...]:
        return tuple(event for event in self.audits if event.tenant_id == tenant_id)

    def record_audit(self, event: AuditEvent) -> None:
        self._pending_audit = event

    def commit(self) -> None:
        if self._pending_quote is not None:
            key, quote = self._pending_quote
            self.quotes[key] = quote
        if self._pending_result is not None:
            key, result = self._pending_result
            self.results[key] = result
        if self._pending_audit is not None:
            self.audits.append(self._pending_audit)
        self.rollback()

    def rollback(self) -> None:
        self._pending_quote = None
        self._pending_result = None
        self._pending_audit = None


class Settings:
    def for_tenant(self, tenant_id: UUID) -> CommercialSettings:
        return CommercialSettings(discount_cap_percent=Decimal("5"))


class Clock:
    def now(self) -> datetime:
        return WHEN


def store_with(*tenants: tuple[UUID, QuoteId]) -> Store:
    store = Store()
    for tenant_id, quote_id in tenants:
        clauses = (EXCLUSION,) if quote_id == QUOTE_A else ()
        store.add(tenant_id, pending_quote(quote_id, clauses))
    return store


def approve_input(quote_id: QuoteId = QUOTE_A, *, expires_at: datetime | None = None) -> ApproveExceptionInput:
    if expires_at is None:
        expires_at = WHEN + timedelta(days=7)
    return ApproveExceptionInput(
        quote_id=quote_id,
        version=1,
        idempotency_key="approve-1",
        expires_at=expires_at,
    )


def reject_input(quote_id: QuoteId = QUOTE_A) -> RejectExceptionInput:
    return RejectExceptionInput(quote_id=quote_id, version=1, idempotency_key="reject-1")


def test_approve_exception_issues_one_new_version():
    store = store_with((TENANT_A, QUOTE_A))
    result = ApproveException(store, store, Clock()).execute(TenantContext(tenant_id=TENANT_A), approve_input())
    stored = store.get_by_id(TENANT_A, QUOTE_A)
    assert stored is not None
    previous = stored.version(1)
    current = stored.current
    assert len(stored.versions) == 2
    assert previous.state is QuoteState.REVISED
    assert previous.lines[0].total == Money("4250.00")
    assert previous.lines[0].unit_price == Money("4250.00")
    assert len(previous.approvals) == 1
    assert previous.approvals[0].applies_to_version == 1
    assert current.number == 2
    assert current.state is QuoteState.ISSUED
    assert current.lines[0].total == Money("3825.00")
    assert current.lines[0].unit_price == Money("3825.00")
    assert current.approvals == ()
    assert current.clauses == (EXCLUSION,)
    assert current.expiry == EXPIRY
    assert result.version == 2
    assert result.state is QuoteState.ISSUED
    assert result.discount_percent == Decimal("10")
    assert type(result.discount_percent) is Decimal
    assert result.lines[0].total == Money("3825.00")
    assert len(store.audits) == 1
    assert store.audits[0].action == "quote.approved"
    assert store.audits[0].version == 2
    assert store.audits[0].actor == "owner"
    with pytest.raises(PolicyViolation) as caught:
        stored.apply_approval(2, previous.approvals[0], at=WHEN)
    assert caught.value.code == "policy.violation"
    assert caught.value.sentence == "An approval applies to one version."


def test_approve_expired_request_fails():
    store = store_with((TENANT_A, QUOTE_A))
    expired = WHEN - timedelta(seconds=1)
    with pytest.raises(PolicyViolation) as caught:
        ApproveException(store, store, Clock()).execute(
            TenantContext(tenant_id=TENANT_A),
            approve_input(expires_at=expired),
        )
    assert caught.value.code == "policy.violation"
    assert caught.value.sentence == "An approval after expiry does not apply."
    stored = store.get_by_id(TENANT_A, QUOTE_A)
    assert stored is not None
    assert len(stored.versions) == 1
    assert stored.current.state is QuoteState.PENDING_APPROVAL
    assert stored.current.lines[0].total == Money("4250.00")
    assert store.audits == []


def test_reject_exception_leaves_the_issued_quote():
    store = store_with((TENANT_A, QUOTE_A))
    result = RejectException(store, store, Clock()).execute(TenantContext(tenant_id=TENANT_A), reject_input())
    stored = store.get_by_id(TENANT_A, QUOTE_A)
    assert stored is not None
    assert len(stored.versions) == 1
    assert stored.current.state is QuoteState.ISSUED
    assert stored.current.lines[0].total == Money("4250.00")
    assert stored.current.approvals == ()
    assert result.version == 1
    assert result.state is QuoteState.ISSUED
    assert result.discount_percent == Decimal("0")
    assert len(store.audits) == 1
    assert store.audits[0].action == "quote.change_rejected"
    assert store.audits[0].version == 1
    assert store.audits[0].actor == "owner"


def test_approve_is_idempotent():
    store = store_with((TENANT_A, QUOTE_A))
    use_case = ApproveException(store, store, Clock())
    context = TenantContext(tenant_id=TENANT_A)
    first = use_case.execute(context, approve_input())
    second = use_case.execute(context, approve_input())
    stored = store.get_by_id(TENANT_A, QUOTE_A)
    assert stored is not None
    assert len(stored.versions) == 2
    assert first == second
    assert len(store.audits) == 1


def test_queue_is_tenant_scoped():
    store = store_with((TENANT_A, QUOTE_A), (TENANT_B, QUOTE_B))
    context = TenantContext(tenant_id=TENANT_A)
    rows = ListPending(store, store, Settings()).execute(context)
    assert len(rows) == 1
    row = rows[0]
    assert row.quote_id == QUOTE_A
    assert row.version == 1
    assert row.requested_discount_percent == Decimal("10")
    assert row.discount_cap_percent == Decimal("5")
    assert row.total == Money("4250.00")
    assert QUOTE_B not in {item.quote_id for item in rows}
    ApproveException(store, store, Clock()).execute(context, approve_input())
    assert ListPending(store, store, Settings()).execute(context) == ()


def test_audit_timeline_lists_the_write_path():
    store = Store()
    events = (
        AuditEvent(
            tenant_id=TENANT_A,
            action="quote.issued",
            quote_id=QUOTE_A,
            version=1,
            actor="system",
            conversation_id=CONVERSATION,
        ),
        AuditEvent(
            tenant_id=TENANT_A,
            action="quote.change_requested",
            quote_id=QUOTE_A,
            version=1,
            actor="system",
            conversation_id=CONVERSATION,
        ),
        AuditEvent(
            tenant_id=TENANT_A,
            action="quote.approved",
            quote_id=QUOTE_A,
            version=2,
            actor="owner",
            conversation_id=CONVERSATION,
        ),
        AuditEvent(
            tenant_id=TENANT_A,
            action="quote.issued",
            quote_id=QUOTE_A,
            version=1,
            conversation_id=None,
        ),
    )
    for event in events:
        store.record_audit(event)
        store.commit()
    timeline = AuditTimeline(store).execute(TenantContext(tenant_id=TENANT_A), CONVERSATION)
    assert [event.action for event in timeline] == [
        "quote.issued",
        "quote.change_requested",
        "quote.approved",
    ]
    assert [event.actor for event in timeline] == ["system", "system", "owner"]
    assert all(event.conversation_id == CONVERSATION for event in timeline)
