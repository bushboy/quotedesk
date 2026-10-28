"""In-memory AquaSure app for the harness and the web chat.

Nothing here opens a database connection or a network socket.
"""

import threading
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import FastAPI

from quotedesk.adapters.outbound.channels.outbox import Outbox, OutboxSender
from quotedesk.adapters.outbound.models.recorded_extraction import RecordedEnricher
from quotedesk.application.dto.agent import ModelReply, ToolCall
from quotedesk.application.use_cases.tools.get_quote_status import GetQuoteStatus
from quotedesk.application.dto.inbound import GateFlags, GateLimits, InboundMessage
from quotedesk.application.dto.published import PublishedPolicy
from quotedesk.application.dto.tenant import CommercialSettings, TenantContext
from quotedesk.application.use_cases.conversation.receive_inbound import ReceiveInboundEvent
from quotedesk.application.use_cases.conversation.run_agent_turn import HandoverToHuman, RunAgentTurn
from quotedesk.application.use_cases.editor.publish_policy import PublishPolicy
from quotedesk.application.use_cases.operator.approve_exception import ApproveException
from quotedesk.application.use_cases.operator.list_pending import ListPending
from quotedesk.application.use_cases.operator.reject_exception import RejectException
from quotedesk.application.use_cases.tools.check_availability import CheckAvailability
from quotedesk.application.use_cases.tools.get_quote import GetQuote
from quotedesk.application.use_cases.tools.request_change import RequestChange
from quotedesk.application.use_cases.tools.update_case import UpdateCase
from quotedesk.domain.case.case_file import CaseFile
from quotedesk.domain.conversation.events import Conversation
from quotedesk.domain.policy.draft import DraftClause, DraftRateRow, DraftRule, PolicyDraft
from quotedesk.domain.quotes.quote import Quote
from quotedesk.domain.quotes.schedule import Capacity, ScheduleSettings
from quotedesk.domain.shared.ids import PolicyVersionId, QuoteId

TENANT_A = UUID("11111111-1111-4111-8111-111111111111")
CONVERSATION = UUID("33333333-3333-4333-8333-333333333333")
WHEN = datetime(2026, 10, 24, 0, 0, tzinfo=timezone.utc)
LIVE_WINDOW = timedelta(seconds=2)


class Conversations:
    def __init__(self) -> None:
        self.rows: dict[tuple[UUID, UUID], Conversation] = {}
        self.notes: list[tuple[UUID, str, datetime]] = []
        self.remembered: list[tuple[UUID, InboundMessage]] = []

    def get(self, tenant_id: UUID, conversation_id: UUID) -> Conversation | None:
        return self.rows.get((tenant_id, conversation_id))

    def save(self, tenant_id: UUID, conversation: Conversation) -> None:
        self.rows[(tenant_id, conversation.conversation_id)] = conversation

    def note(self, tenant_id: UUID, wa_id: str, at: datetime) -> None:
        self.notes.append((tenant_id, wa_id, at))

    def noted(self, tenant_id: UUID, wa_id: str) -> tuple[datetime, ...]:
        return tuple(at for tenant, sender, at in self.notes if tenant == tenant_id and sender == wa_id)

    def remember(self, tenant_id: UUID, message: InboundMessage) -> None:
        self.remembered.append((tenant_id, message))

    def messages(self, tenant_id: UUID, conversation_id: UUID) -> tuple[InboundMessage, ...]:
        return tuple(
            message
            for tenant, message in self.remembered
            if tenant == tenant_id and message.conversation_id == conversation_id
        )


class Cases:
    def __init__(self, case: CaseFile) -> None:
        self.case = case

    def get(self, tenant_id: UUID, conversation_id: UUID) -> CaseFile | None:
        if tenant_id != TENANT_A or conversation_id != self.case.conversation_id:
            return None
        return self.case

    def save(self, tenant_id: UUID, case: CaseFile) -> None:
        self.case = case


class Policies:
    def __init__(self, bundle: PublishedPolicy) -> None:
        self.bundle = bundle
        self.versions: dict[str, PublishedPolicy] = {bundle.policy.version.value: bundle}
        self.drafts: dict[UUID, PolicyDraft] = {}
        self.publishes: dict[tuple[UUID, str], PolicyVersionId] = {}

    def published(self, tenant_id: UUID) -> PublishedPolicy:
        return self.bundle

    def draft(self, tenant_id: UUID) -> PolicyDraft | None:
        return self.drafts.get(tenant_id)

    def save_draft(self, tenant_id: UUID, draft: PolicyDraft) -> None:
        self.drafts[tenant_id] = draft

    def get(self, tenant_id: UUID, version_id: PolicyVersionId) -> PublishedPolicy | None:
        return self.versions.get(version_id.value)

    def save_published(self, tenant_id: UUID, bundle: PublishedPolicy) -> None:
        self.bundle = bundle
        self.versions[bundle.policy.version.value] = bundle

    def find_publish(self, tenant_id: UUID, idempotency_key: str) -> PolicyVersionId | None:
        return self.publishes.get((tenant_id, idempotency_key))

    def remember_publish(self, tenant_id: UUID, idempotency_key: str, version: PolicyVersionId) -> None:
        self.publishes[(tenant_id, idempotency_key)] = version


class _Staged:
    """A staged write kept per thread, so the turn worker and an owner page never share one stage."""

    def __set_name__(self, owner, name: str) -> None:
        self.name = name

    def __get__(self, unit, owner=None):
        if unit is None:
            return self
        return getattr(unit._stage, self.name, None)

    def __set__(self, unit, value) -> None:
        setattr(unit._stage, self.name, value)


class Unit:
    _pending_key = _Staged()
    _pending_quote = _Staged()
    _pending_audit = _Staged()
    _pending_replace = _Staged()
    _pending_change = _Staged()
    _pending_result = _Staged()

    def __init__(self) -> None:
        self._stage = threading.local()
        self._commit_lock = threading.Lock()
        self.committed: dict[tuple[UUID, UUID], Quote] = {}
        self.audits: list = []
        self.changes: dict[tuple[UUID, str], object] = {}
        self.operator_results: dict[tuple[UUID, str], object] = {}
        self._pending_key = None
        self._pending_quote = None
        self._pending_audit = None
        self._pending_replace = None
        self._pending_change = None
        self._pending_result = None

    def get_quote(self, tenant_id: UUID, conversation_id: UUID) -> Quote | None:
        return self.committed.get((tenant_id, conversation_id))

    def save_quote(self, tenant_id: UUID, conversation_id: UUID, quote: Quote) -> None:
        self._pending_key = (tenant_id, conversation_id)
        self._pending_quote = quote

    def record_audit(self, event) -> None:
        self._pending_audit = event

    def save_quote_by_id(self, tenant_id: UUID, quote: Quote) -> None:
        self._pending_replace = (tenant_id, quote)

    def find_change(self, tenant_id: UUID, idempotency_key: str):
        return self.changes.get((tenant_id, idempotency_key))

    def save_change(self, record) -> None:
        self._pending_change = record

    def list_changes(self, tenant_id: UUID) -> tuple:
        return tuple(record for (tenant, _), record in list(self.changes.items()) if tenant == tenant_id)

    def find_operator_result(self, tenant_id: UUID, idempotency_key: str):
        return self.operator_results.get((tenant_id, idempotency_key))

    def save_operator_result(self, tenant_id: UUID, idempotency_key: str, result) -> None:
        self._pending_result = ((tenant_id, idempotency_key), result)

    def list_audits(self, tenant_id: UUID) -> tuple:
        return tuple(event for event in list(self.audits) if event.tenant_id == tenant_id)

    def commit(self) -> None:
        with self._commit_lock:
            self._apply()
        self.rollback()

    def _apply(self) -> None:
        if self._pending_key is not None and self._pending_quote is not None:
            self.committed[self._pending_key] = self._pending_quote
        if self._pending_replace is not None:
            tenant_id, quote = self._pending_replace
            for key, stored in list(self.committed.items()):
                if key[0] == tenant_id and stored.quote_id == quote.quote_id:
                    self.committed[key] = quote
                    break
        if self._pending_change is not None:
            self.changes[(self._pending_change.tenant_id, self._pending_change.idempotency_key)] = (
                self._pending_change
            )
        if self._pending_result is not None:
            key, result = self._pending_result
            self.operator_results[key] = result
        if self._pending_audit is not None:
            self.audits.append(self._pending_audit)

    def rollback(self) -> None:
        self._pending_key = None
        self._pending_quote = None
        self._pending_audit = None
        self._pending_replace = None
        self._pending_change = None
        self._pending_result = None


class QuoteClock:
    def now(self) -> datetime:
        return WHEN


class TurnClock:
    def __init__(self) -> None:
        self.instant = WHEN + timedelta(seconds=5)

    def now(self) -> datetime:
        return self.instant


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class Ids:
    def next_quote_id(self) -> QuoteId:
        return QuoteId("QD-1042")

    def next_fact_id(self) -> UUID:
        return uuid4()

    def next_idempotency_key(self) -> str:
        return str(uuid4())


class Catalog:
    def required(self, job_type: str) -> tuple[str, ...]:
        if job_type == "replacement":
            return ("size_litres", "existing_level_base")
        return ()


class Media:
    def __init__(self) -> None:
        self.objects: list = []

    def put(self, tenant_id: UUID, message_id: str, mime: str, size_bytes: int) -> None:
        self.objects.append((tenant_id, message_id, mime, size_bytes))


class Ordinary:
    def classify(self, data: InboundMessage) -> str:
        return "ordinary"


class Slot:
    def __init__(self) -> None:
        self.model = Thanks()

    def complete(self, prompt):
        return self.model.complete(prompt)


class Thanks:
    def complete(self, prompt) -> ModelReply:
        return ModelReply(text="Thanks.", tool_calls=())


class Lock:
    def __init__(self) -> None:
        self._lock = threading.Lock()

    def acquire(self, conversation_id: UUID) -> bool:
        return self._lock.acquire(blocking=False)

    def release(self, conversation_id: UUID) -> None:
        self._lock.release()


EVENT = "44444444-4444-4444-8444-444444444444"
CARD_URL = "/card/QD-1042?code=1042"
QUOTE_REPLY = f"The total is R 4 250. Your card: {CARD_URL}"


def quote_facts() -> list[dict[str, str]]:
    return [
        {"key": "job", "value": "replacement", "source": "customer_text", "event_id": EVENT},
        {"key": "size_litres", "value": "5000", "source": "customer_text", "event_id": EVENT},
        {"key": "size_source", "value": "customer_stated", "source": "customer_text", "event_id": EVENT},
        {"key": "existing_level_base", "value": "true", "source": "customer_text", "event_id": EVENT},
        {"key": "item_codes", "value": "TANK-5000", "source": "customer_text", "event_id": EVENT},
        {"key": "required_fields", "value": "true", "source": "customer_text", "event_id": EVENT},
        {"key": "agreement", "value": "true", "source": "customer_text", "event_id": EVENT},
        {"key": "measurement", "value": "true", "source": "customer_text", "event_id": EVENT},
        {"key": "media_usable", "value": "true", "source": "customer_text", "event_id": EVENT},
        {"key": "rate_card", "value": "true", "source": "customer_text", "event_id": EVENT},
        {"key": "photo_note", "value": "tank on a sound base", "source": "photo_extraction", "event_id": EVENT},
    ]


class QuoteScript:
    def complete(self, prompt) -> ModelReply:
        return ModelReply(
            text=QUOTE_REPLY,
            tool_calls=(
                ToolCall(
                    name="update_case",
                    arguments={
                        "conversation_id": str(CONVERSATION),
                        "job_id": "tank",
                        "job_type": "replacement",
                        "facts": quote_facts(),
                    },
                ),
                ToolCall(name="get_quote", arguments={"conversation_id": str(CONVERSATION)}),
            ),
        )


class Remembering:
    def __init__(self, inner: GetQuote) -> None:
        self.inner = inner
        self.last = None

    def execute(self, context, data):
        result = self.inner.execute(context, data)
        self.last = result
        return result


class QuoteLookup:
    def __init__(self, unit: Unit) -> None:
        self._unit = unit

    def get(self, tenant_id: UUID, conversation_id: UUID):
        return self._unit.get_quote(tenant_id, conversation_id)

    def get_by_id(self, tenant_id: UUID, quote_id: QuoteId):
        for (stored, _), quote in self._unit.committed.items():
            if stored == tenant_id and quote.quote_id == quote_id:
                return quote
        return None

    def list_for(self, tenant_id: UUID) -> tuple[Quote, ...]:
        return tuple(quote for (stored, _), quote in list(self._unit.committed.items()) if stored == tenant_id)

    def save(self, tenant_id: UUID, conversation_id: UUID, quote) -> None:
        return None


class Codes:
    def issue(self, tenant_id: UUID, quote_id: QuoteId) -> str:
        raise AssertionError("GetQuoteStatus does not mint a code.")

    def matches(self, tenant_id: UUID, quote_id: QuoteId, code: str) -> bool:
        return quote_id.value == "QD-1042" and code == "1042"


def published_bundle() -> PublishedPolicy:
    from pathlib import Path

    from quotedesk.adapters.outbound.parsers.aquasure import load_policy
    from quotedesk.domain.policy.clauses import ClausePolicy
    from quotedesk.domain.services.price import RateCard, RateCardItem
    from quotedesk.domain.shared.money import Money

    path = Path("seeds/aquasure.yaml")
    if not path.is_file():
        path = Path(__file__).resolve().parents[2] / "seeds" / "aquasure.yaml"
    return PublishedPolicy(
        policy=load_policy(path),
        rate_card=RateCard(
            vat_inclusive=True,
            site_visit_fee=Money("750.00"),
            items=(
                RateCardItem(item_code="TANK-5000", description="5000 L tank", unit_price=Money("4250.00")),
            ),
        ),
        clause_policy=ClausePolicy(
            templates=(),
            settings={"deposit_percent": 30, "validity_days": 14},
            rate_card_codes=("TANK-5000",),
        ),
    )


def policy_draft(bundle: PublishedPolicy, discount_cap_percent: Decimal) -> PolicyDraft:
    """The editor's starting draft: a copy of the published bundle with every rule enabled."""
    settings = bundle.clause_policy.settings
    vat_inclusive = bundle.rate_card.vat_inclusive
    return PolicyDraft(
        deposit_percent=int(settings["deposit_percent"]),
        discount_cap_percent=int(discount_cap_percent),
        validity_days=int(settings["validity_days"]),
        vat_inclusive=vat_inclusive,
        rate_rows=tuple(
            DraftRateRow(item_code=item.item_code, unit_price=item.unit_price.amount, vat_inclusive=vat_inclusive)
            for item in bundle.rate_card.items
        ),
        clauses=tuple(
            DraftClause(clause_id=t.clause_id, text=t.text, variation_item_code=t.variation_item_code)
            for t in bundle.clause_policy.templates
        ),
        required_facts=(),
        rules=tuple(DraftRule(rule_id=rule.rule_id.value, enabled=True) for rule in bundle.policy.rules),
        settings=tuple(settings),
    )


class _Caps:
    def for_tenant(self, tenant_id: UUID) -> CommercialSettings:
        return CommercialSettings(discount_cap_percent=Decimal("5"))


class _Capacity:
    def get(self, tenant_id: UUID) -> Capacity:
        return Capacity()

    def save(self, tenant_id: UUID, capacity: Capacity) -> None:
        return None


def _caps() -> _Caps:
    return _Caps()


def _capacity() -> _Capacity:
    return _Capacity()


def _schedule_settings() -> ScheduleSettings:
    return ScheduleSettings(
        lead_time_working_days={"replacement": 5},
        minimum_notice_working_days=2,
        hold_period_hours=48,
        working_days=(0, 1, 2, 3, 4),
        blocked_dates=(date(2026, 11, 2),),
        sentences={
            "lead_time": "A {job_type} is usually about {lead_time_working_days} working days after the deposit.",
            "earliest": "The earliest window is {window}, and it is not reserved.",
            "requested_open": "That date is open. We can hold it when the deposit is paid.",
            "requested_closed": "That date is full. The next open days are {first} and {second}.",
            "too_soon": "That date is too soon. The earliest window is {window}.",
            "next_working_day": "The next working day is {window}.",
            "held": "That window is held until the deposit hold expires.",
            "confirmed": "That date is confirmed.",
            "escalated": "We can't guarantee a date here.",
        },
    )


def install(
    app: FastAPI,
    bundle: PublishedPolicy,
    model=None,
    card_base: str | None = None,
    card_code: str | None = None,
    sender=None,
    live: bool = False,
) -> None:
    """`live` runs on wall-clock time with a short quiet window, for a person at the chat page.

    The harness keeps the fixed clock so scenario `at` offsets stay meaningful.
    `sender` is the ChannelSender. It defaults to the in-process outbox.
    """
    published = bundle
    conversations = Conversations()
    cases = Cases(CaseFile.open(CONVERSATION, TENANT_A))
    unit = Unit()
    outbox = Outbox()
    if sender is None:
        sender = OutboxSender(outbox)
    slot = Slot()
    if model is not None:
        slot.model = model
    clock = SystemClock() if live else TurnClock()
    receive = ReceiveInboundEvent(conversations, sender, Media(), Ordinary(), clock)
    ids = Ids()
    catalog = Catalog()
    policies = Policies(published)
    policies.save_draft(TENANT_A, policy_draft(published, _caps().for_tenant(TENANT_A).discount_cap_percent))
    update = UpdateCase(cases, catalog, ids)
    quoted = Remembering(GetQuote(cases, policies, unit, QuoteClock(), ids))
    handover = HandoverToHuman(cases)
    turn = RunAgentTurn(
        conversations,
        sender,
        slot,
        Lock(),
        update,
        quoted,
        handover,
        clock,
        request_change=RequestChange(QuoteLookup(unit), _caps(), unit, clock),
        check_availability=CheckAvailability(_capacity(), _schedule_settings(), clock),
        catalog=catalog,
        policies=policies,
        ids=ids,
        window=LIVE_WINDOW if live else timedelta(seconds=5),
        card_base=card_base,
        card_code=card_code,
        enricher=RecordedEnricher(),
    )
    app.state.tenant_id = TENANT_A
    app.state.conversation_id = CONVERSATION
    app.state.conversations = conversations
    app.state.cases = cases
    app.state.unit = unit
    app.state.outbox = outbox
    app.state.slot = slot
    app.state.clock = clock
    app.state.receive = receive
    app.state.turn = turn
    app.state.quoted = quoted
    app.state.status = GetQuoteStatus(QuoteLookup(unit), Codes())
    app.state.policies = policies
    app.state.list_pending = ListPending(QuoteLookup(unit), unit, _caps())
    app.state.approve = ApproveException(QuoteLookup(unit), unit, clock)
    app.state.reject = RejectException(QuoteLookup(unit), unit, clock)
    app.state.publish = PublishPolicy(policies, unit, clock)
    app.state.flags = GateFlags(afrikaans_text=False, afrikaans_voice=False)
    allowed = ("image/jpeg", "image/png", "audio/ogg", "video/mp4")
    app.state.limits = GateLimits(
        max_bytes=100,
        max_audio_seconds=Decimal("30"),
        messages_per_minute=10 if live else 3,
        allowed_types=allowed + ("audio/webm", "audio/mp4") if live else allowed,
    )

    def run_turn() -> None:
        turn.execute(TenantContext(tenant_id=app.state.tenant_id), app.state.conversation_id)

    app.state.run_turn = run_turn
