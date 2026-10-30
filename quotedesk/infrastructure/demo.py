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
from quotedesk.application.dto.agent import BusinessView, ModelReply, ToolCall
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
from quotedesk.application.use_cases.tools.book_inspection import BookInspection
from quotedesk.application.use_cases.tools.check_availability import CheckAvailability
from quotedesk.application.use_cases.tools.escalate_to_owner import EscalateToOwner
from quotedesk.application.use_cases.tools.get_quote import GetQuote
from quotedesk.application.use_cases.tools.notify_owner import NotifyOwner
from quotedesk.application.use_cases.tools.request_change import RequestChange
from quotedesk.application.use_cases.tools.update_case import UpdateCase
from quotedesk.domain.case.case_file import CaseFile
from quotedesk.domain.conversation.events import Conversation
from quotedesk.domain.policy.draft import DraftClause, DraftRateRow, DraftRule, PolicyDraft
from quotedesk.domain.quotes.quote import Quote
from quotedesk.domain.quotes.schedule import ScheduleSettings
from quotedesk.domain.services.price import RateCard
from quotedesk.domain.shared.ids import PolicyVersionId, QuoteId
from quotedesk.adapters.outbound.persistence.commercial import MemoryInspections, MemoryMail, MemoryNotices
from quotedesk.adapters.outbound.persistence.tenants import TenantProfile, known_tenant

TENANT_A = UUID("11111111-1111-4111-8111-111111111111")
CONVERSATION = UUID("33333333-3333-4333-8333-333333333333")
WHEN = datetime(2026, 10, 24, 0, 0, tzinfo=timezone.utc)
LIVE_WINDOW = timedelta(seconds=2)


class Conversations:
    def __init__(self) -> None:
        self.rows: dict[tuple[UUID, UUID], Conversation] = {}
        self.notes: list[tuple[UUID, str, datetime]] = []
        self.remembered: list[tuple[UUID, InboundMessage]] = []
        self._by_sender: dict[tuple[UUID, str], UUID] = {}
        self._names: dict[tuple[UUID, str], str] = {}
        self._replies: list[tuple[UUID, UUID, datetime, str]] = []
        self._claim_lock = threading.Lock()
        self._enrichments: dict[tuple[UUID, str], object] = {}
        self._outbound: dict[tuple[UUID, str], str] = {}
        self._outbound_body: dict[tuple[UUID, str], tuple[UUID, datetime, str]] = {}
        self._held: set[tuple[UUID, UUID]] = set()
        self._change_keys: dict[tuple[UUID, UUID], str] = {}

    def get(self, tenant_id: UUID, conversation_id: UUID) -> Conversation | None:
        return self.rows.get((tenant_id, conversation_id))

    def save(self, tenant_id: UUID, conversation: Conversation) -> None:
        self.rows[(tenant_id, conversation.conversation_id)] = conversation

    def find(self, tenant_id: UUID, wa_id: str) -> UUID | None:
        return self._by_sender.get((tenant_id, wa_id))

    def bind(self, tenant_id: UUID, wa_id: str, conversation_id: UUID) -> None:
        self._by_sender[(tenant_id, wa_id)] = conversation_id

    def sender_for(self, tenant_id: UUID, conversation_id: UUID) -> str | None:
        for (tenant, wa_id), stored in self._by_sender.items():
            if tenant == tenant_id and stored == conversation_id:
                return wa_id
        return None

    def name(self, tenant_id: UUID, wa_id: str) -> str | None:
        return self._names.get((tenant_id, wa_id))

    def rename(self, tenant_id: UUID, wa_id: str, display_name: str) -> None:
        self._names[(tenant_id, wa_id)] = display_name

    def taken(self, conversation_id: UUID) -> bool:
        return conversation_id in self._by_sender.values()

    def place(self, tenant_id: UUID, conversation_id: UUID) -> UUID:
        return conversation_id

    def ids(self, tenant_id: UUID) -> tuple[UUID, ...]:
        return tuple(conversation_id for (tenant, conversation_id) in self.rows if tenant == tenant_id)

    def record_reply(self, tenant_id: UUID, conversation_id: UUID, at: datetime, body: str) -> None:
        self._replies.append((tenant_id, conversation_id, at, body))

    def claim_pending(self, tenant_id: UUID, conversation_id: UUID, ids: tuple[str, ...]) -> tuple[str, ...]:
        wanted = set(ids)
        with self._claim_lock:
            conversation = self.get(tenant_id, conversation_id)
            if conversation is None:
                return ()
            ready = tuple(
                event.provider_message_id
                for event in conversation.log
                if event.provider_message_id in wanted and event.status == "pending"
            )
            if set(ready) != wanted:
                return ready
            log = tuple(
                event.model_copy(update={"status": "claimed"}) if event.provider_message_id in wanted else event
                for event in conversation.log
            )
            self.save(tenant_id, conversation.model_copy(update={"log": log}))
            return ready

    def release_claims(self, tenant_id: UUID) -> None:
        with self._claim_lock:
            for (tenant, conversation_id), conversation in list(self.rows.items()):
                if tenant != tenant_id:
                    continue
                if not any(event.status == "claimed" for event in conversation.log):
                    continue
                log = tuple(
                    event.model_copy(update={"status": "pending"}) if event.status == "claimed" else event
                    for event in conversation.log
                )
                self.rows[(tenant, conversation_id)] = conversation.model_copy(update={"log": log})

    def hold_escalation(self, tenant_id: UUID, conversation_id: UUID) -> None:
        self._held.add((tenant_id, conversation_id))

    def release_escalation(self, tenant_id: UUID, conversation_id: UUID) -> None:
        self._held.discard((tenant_id, conversation_id))

    def escalation_held(self, tenant_id: UUID, conversation_id: UUID) -> bool:
        return (tenant_id, conversation_id) in self._held

    def save_enrichment(self, tenant_id: UUID, message_id: str, result) -> None:
        self._enrichments[(tenant_id, message_id)] = result

    def enrichment(self, tenant_id: UUID, message_id: str):
        return self._enrichments.get((tenant_id, message_id))

    def reserve_outbound(self, tenant_id: UUID, batch_id: str, conversation_id: UUID, at: datetime, body: str) -> str:
        key = (tenant_id, batch_id)
        state = self._outbound.get(key)
        if state == "sent":
            return "skip"
        if state == "unsent":
            return "send"
        self._outbound[key] = "unsent"
        self._outbound_body[key] = (conversation_id, at, body)
        self._replies.append((tenant_id, conversation_id, at, body))
        return "send"

    def finish_outbound(self, tenant_id: UUID, batch_id: str) -> None:
        key = (tenant_id, batch_id)
        if key in self._outbound:
            self._outbound[key] = "sent"

    def unsent(self, tenant_id: UUID, conversation_id: UUID) -> tuple[str, str] | None:
        for (tenant, batch_id), state in self._outbound.items():
            if tenant != tenant_id or state != "unsent":
                continue
            stored_id, _at, body = self._outbound_body[(tenant, batch_id)]
            if stored_id == conversation_id:
                return batch_id, body
        return None

    def change_key(self, tenant_id: UUID, conversation_id: UUID) -> str | None:
        return self._change_keys.get((tenant_id, conversation_id))

    def save_change_key(self, tenant_id: UUID, conversation_id: UUID, key: str | None) -> None:
        stored = (tenant_id, conversation_id)
        if key is None:
            self._change_keys.pop(stored, None)
        else:
            self._change_keys[stored] = key

    def transcript(self, tenant_id: UUID, wa_id: str) -> list[dict[str, str]]:
        conversation_id = self.find(tenant_id, wa_id)
        if conversation_id is None:
            return []
        rows: list[dict[str, str]] = []
        conversation = self.get(tenant_id, conversation_id)
        if conversation is not None:
            for event in conversation.events:
                rows.append({"side": "out", "body": event.body, "at": event.at.isoformat(), "kind": "text"})
        for at, body in self.replies(tenant_id, conversation_id):
            rows.append({"side": "in", "body": body, "at": at.isoformat(), "kind": "text"})
        rows.sort(key=lambda item: item["at"])
        return rows

    def replies(self, tenant_id: UUID, conversation_id: UUID) -> tuple[tuple[datetime, str], ...]:
        return tuple(
            (at, body)
            for tenant, stored, at, body in self._replies
            if tenant == tenant_id and stored == conversation_id
        )

    def trail(self, tenant_id: UUID, conversation_id: UUID) -> tuple[dict[str, str], ...]:
        rows: list[tuple[datetime, int, dict[str, str]]] = []
        conversation = self.get(tenant_id, conversation_id)
        if conversation is not None:
            for event in conversation.events:
                rows.append(
                    (
                        event.at,
                        0,
                        {"role": "customer", "id": event.provider_message_id, "body": event.body},
                    )
                )
        for index, (at, body) in enumerate(self.replies(tenant_id, conversation_id)):
            rows.append((at, 1, {"role": "assistant", "id": f"reply-{index}", "body": body}))
        rows.sort(key=lambda item: (item[0], item[1]))
        return tuple(item[2] for item in rows)

    def note(self, tenant_id: UUID, wa_id: str, at: datetime) -> None:
        self.notes.append((tenant_id, wa_id, at))

    def noted(self, tenant_id: UUID, wa_id: str) -> tuple[datetime, ...]:
        return tuple(at for tenant, sender, at in self.notes if tenant == tenant_id and sender == wa_id)

    def remember(self, tenant_id: UUID, message: InboundMessage) -> None:
        self.remembered.append((tenant_id, message))

    def heard(self, tenant_id: UUID) -> tuple[InboundMessage, ...]:
        return tuple(message for tenant, message in self.remembered if tenant == tenant_id)

    def messages(self, tenant_id: UUID, conversation_id: UUID) -> tuple[InboundMessage, ...]:
        return tuple(
            message
            for tenant, message in self.remembered
            if tenant == tenant_id and message.conversation_id == conversation_id
        )


class Cases:
    def __init__(self, case: CaseFile) -> None:
        self._rows = {(case.tenant_id, case.conversation_id): case}

    def get(self, tenant_id: UUID, conversation_id: UUID) -> CaseFile | None:
        return self._rows.get((tenant_id, conversation_id))

    def save(self, tenant_id: UUID, case: CaseFile) -> None:
        self._rows[(tenant_id, case.conversation_id)] = case

    def ensure(self, tenant_id: UUID, conversation_id: UUID) -> None:
        if self.get(tenant_id, conversation_id) is None:
            self.save(tenant_id, CaseFile.open(conversation_id, tenant_id))


class Policies:
    """`rate_cards` is where a published rate card is kept. `None` keeps it in memory only."""

    def __init__(self, bundle: PublishedPolicy, rate_cards=None) -> None:
        self.bundle = bundle
        self.rate_cards = rate_cards
        self.bundles: dict[UUID, PublishedPolicy] = {}
        self.active: UUID | None = None
        self.versions: dict[str, PublishedPolicy] = {bundle.policy.version.value: bundle}
        self.drafts: dict[UUID, PolicyDraft] = {}
        self.publishes: dict[tuple[UUID, str], PolicyVersionId] = {}

    def published(self, tenant_id: UUID) -> PublishedPolicy:
        return self.bundles.get(tenant_id, self.bundle)

    def draft(self, tenant_id: UUID) -> PolicyDraft | None:
        return self.drafts.get(tenant_id)

    def save_draft(self, tenant_id: UUID, draft: PolicyDraft) -> None:
        self.drafts[tenant_id] = draft

    def get(self, tenant_id: UUID, version_id: PolicyVersionId) -> PublishedPolicy | None:
        return self.versions.get(version_id.value)

    def save_published(self, tenant_id: UUID, bundle: PublishedPolicy) -> None:
        self.bundles[tenant_id] = bundle
        if self.active is None or tenant_id == self.active:
            self.bundle = bundle
        self.versions[bundle.policy.version.value] = bundle
        if self.rate_cards is not None:
            self.rate_cards.save(tenant_id, bundle.rate_card)

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
    def __init__(self, playbook=None) -> None:
        self._playbook = playbook

    def required(self, job_type: str) -> tuple[str, ...]:
        if self._playbook is not None and self._playbook.populated():
            return self._playbook.required(job_type)
        if job_type == "replacement":
            return ("size_litres", "existing_level_base")
        return ()

    def facts(self, job_type: str):
        if self._playbook is None or not self._playbook.populated():
            return ()
        for job in self._playbook.job_types:
            if job.key == job_type:
                return job.facts
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
        reader = getattr(self._unit, "read_quote", None)
        if reader is None:
            return None
        return reader(tenant_id, quote_id)

    def list_for(self, tenant_id: UUID) -> tuple[Quote, ...]:
        listed = getattr(self._unit, "list_quotes", None)
        if listed is not None:
            return listed(tenant_id)
        return tuple(quote for (stored, _), quote in list(self._unit.committed.items()) if stored == tenant_id)

    def save(self, tenant_id: UUID, conversation_id: UUID, quote) -> None:
        return None


class Codes:
    def issue(self, tenant_id: UUID, quote_id: QuoteId) -> str:
        raise AssertionError("GetQuoteStatus does not mint a code.")

    def matches(self, tenant_id: UUID, quote_id: QuoteId, code: str) -> bool:
        return code == "1042"


def with_rate_card(bundle: PublishedPolicy, card: RateCard | None) -> PublishedPolicy:
    """The bundle with a stored rate card in place of the built-in one, and the item codes to match."""
    if card is None:
        return bundle
    codes = tuple(item.item_code for item in card.items)
    return bundle.model_copy(
        update={
            "rate_card": card,
            "policy": bundle.policy.model_copy(update={"rate_card_codes": codes}),
            "clause_policy": bundle.clause_policy.model_copy(update={"rate_card_codes": codes}),
        }
    )


def bundle_for(slug: str) -> PublishedPolicy:
    """The published policy for the business this process started as."""
    if slug == "frameworks":
        return _frameworks_bundle()
    return published_bundle()


def _frameworks_bundle() -> PublishedPolicy:
    from pathlib import Path

    from quotedesk.adapters.outbound.parsers.aquasure import load_playbook, load_policy
    from quotedesk.domain.policy.clauses import ClausePolicy
    from quotedesk.domain.services.price import RateCard, RateCardItem
    from quotedesk.domain.shared.money import Money

    path = Path("seeds/frameworks.yaml")
    if not path.is_file():
        path = Path(__file__).resolve().parents[2] / "seeds" / "frameworks.yaml"
    return PublishedPolicy(
        policy=load_policy(path),
        rate_card=RateCard(
            vat_inclusive=True,
            site_visit_fee=Money("750.00"),
            items=(
                RateCardItem(item_code="SHEET-ECO", description="Economy sheeting", unit_price=Money("180.00"), unit="per m²", role="product"),
                RateCardItem(item_code="SHEET-POLY", description="Polycarbonate sheeting", unit_price=Money("260.00"), unit="per m²", role="product"),
            ),
        ),
        clause_policy=ClausePolicy(
            templates=(),
            settings={"deposit_percent": 30, "validity_days": 14},
            rate_card_codes=("SHEET-ECO", "SHEET-POLY"),
        ),
        playbook=load_playbook(path),
    )


def published_bundle() -> PublishedPolicy:
    from pathlib import Path

    from quotedesk.adapters.outbound.parsers.aquasure import load_playbook, load_policy
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
                RateCardItem(item_code="TANK-2500", description="2500 L tank", unit_price=Money("2850.00")),
                RateCardItem(item_code="TANK-5000", description="5000 L tank", unit_price=Money("4250.00")),
                RateCardItem(item_code="TANK-10000", description="10000 L tank", unit_price=Money("7900.00")),
            ),
        ),
        clause_policy=ClausePolicy(
            templates=(),
            settings={"deposit_percent": 30, "validity_days": 14},
            rate_card_codes=("TANK-2500", "TANK-5000", "TANK-10000"),
        ),
        playbook=load_playbook(path),
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
            DraftRateRow(
                item_code=item.item_code,
                unit_price=item.unit_price.amount,
                vat_inclusive=vat_inclusive,
                description=item.description,
                unit=item.unit,
                role=item.role,
            )
            for item in bundle.rate_card.items
        ),
        clauses=tuple(
            DraftClause(clause_id=t.clause_id, text=t.text, variation_item_code=t.variation_item_code)
            for t in bundle.clause_policy.templates
        ),
        required_facts=(),
        rules=tuple(DraftRule(rule_id=rule.rule_id.value, enabled=True) for rule in bundle.policy.rules),
        settings=tuple(settings),
        playbook=bundle.playbook,
    )


class _Caps:
    def for_tenant(self, tenant_id: UUID) -> CommercialSettings:
        return CommercialSettings(discount_cap_percent=Decimal("5"))


def _caps() -> _Caps:
    return _Caps()


def _schedule_settings() -> ScheduleSettings:
    return ScheduleSettings(
        lead_time_working_days={
            "replacement": 5,
            "new_system": 7,
            "new_installation": 7,
            "borehole": 10,
            "carport": 8,
            "window": 8,
            "door": 8,
            "shutter": 8,
            "inspection": 5,
            "site_assessment": 5,
        },
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


_LIVE_BYTES = 5 * 1024 * 1024


def install(
    app: FastAPI,
    bundle: PublishedPolicy,
    model=None,
    card_base: str | None = None,
    card_code: str | None = None,
    sender=None,
    live: bool = False,
    enricher=None,
    tenant: TenantProfile | None = None,
    rate_cards=None,
    conversations=None,
    cases=None,
    unit=None,
    ids=None,
    codes=None,
    acceptances=None,
    links=None,
    capacity=None,
    handovers=None,
    inspections=None,
    notices=None,
    bundles=None,
) -> None:
    """`live` runs on wall-clock time with a short quiet window, for a person at the chat page.

    The harness keeps the fixed clock so scenario `at` offsets stay meaningful.
    `sender` is the ChannelSender. It defaults to the in-process outbox.
    """
    published = bundle
    profile = tenant or known_tenant("aquasure")
    conversations = conversations or Conversations()
    cases = cases or Cases(CaseFile.open(CONVERSATION, profile.tenant_id))
    from quotedesk.application.use_cases.tools.accept_quote import AcceptQuote
    from quotedesk.application.use_cases.tools.create_deposit_link import CreateDepositLink
    from quotedesk.application.use_cases.tools.hold_slot import HoldSlot
    from quotedesk.adapters.outbound.persistence.commercial import (
        IssuedCodes,
        MemoryAcceptances,
        MemoryCapacity,
        MemoryDeposits,
        MemoryHandovers,
        MemoryHolds,
        MemoryLinks,
        SequencingIds,
    )

    unit = unit or Unit()
    ids = ids or SequencingIds()
    if codes is None and live:
        codes = IssuedCodes()
    acceptances = acceptances or MemoryAcceptances()
    links = links or MemoryLinks()
    capacity = capacity or MemoryCapacity()
    handovers = handovers or MemoryHandovers()
    inspections = inspections or MemoryInspections()
    notices = notices or MemoryNotices()
    holds = MemoryHolds()
    outbox = Outbox()
    if sender is None:
        sender = OutboxSender(outbox)
    slot = Slot()
    if model is not None:
        slot.model = model
    clock = SystemClock() if live else TurnClock()
    receive = ReceiveInboundEvent(conversations, sender, Media(), Ordinary(), clock)
    catalog = Catalog(published.playbook)
    policies = Policies(published, rate_cards)
    policies.active = profile.tenant_id
    policies.bundles = dict(bundles or {})
    policies.bundles[profile.tenant_id] = published
    policies.save_draft(
        profile.tenant_id,
        policy_draft(published, _caps().for_tenant(profile.tenant_id).discount_cap_percent),
    )
    update = UpdateCase(cases, catalog, ids)
    lookup = QuoteLookup(unit)
    quoted = Remembering(GetQuote(cases, policies, unit, clock, ids, codes))
    handover = HandoverToHuman(cases, handovers, clock)
    book = BookInspection(cases, policies, capacity, _schedule_settings(), clock, inspections, unit, conversations)
    escalate = EscalateToOwner(
        cases,
        conversations,
        policies,
        handovers,
        inspections,
        NotifyOwner(notices, sender, MemoryMail()),
        clock,
        quotes=unit,
    )
    turn = RunAgentTurn(
        conversations,
        sender,
        slot,
        Lock(),
        update,
        quoted,
        handover,
        clock,
        request_change=RequestChange(lookup, _caps(), unit, clock),
        check_availability=CheckAvailability(capacity, _schedule_settings(), clock),
        accept_quote=AcceptQuote(lookup, acceptances, unit, clock),
        create_deposit_link=CreateDepositLink(lookup, acceptances, links),
        hold_slot=HoldSlot(capacity, MemoryDeposits(), holds, _schedule_settings(), clock),
        catalog=catalog,
        policies=policies,
        ids=ids,
        window=LIVE_WINDOW if live else timedelta(seconds=5),
        card_base=card_base,
        card_code=card_code,
        enricher=RecordedEnricher() if enricher is None else enricher,
        business=BusinessView(
            name=profile.display_name,
            trade=profile.trade,
            area=profile.area,
            about=profile.about,
        ),
        cases=cases,
        book_inspection=book,
        escalate_to_owner=escalate,
    )
    app.state.tenant_id = profile.tenant_id
    app.state.tenant = profile
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
    app.state.status = GetQuoteStatus(lookup, codes if codes is not None else Codes())
    app.state.quotes = lookup
    app.state.handovers = handovers
    app.state.inspections = inspections
    app.state.codes = codes
    app.state.policies = policies
    app.state.list_pending = ListPending(lookup, unit, _caps())
    app.state.approve = ApproveException(lookup, unit, clock)
    app.state.reject = RejectException(lookup, unit, clock)
    app.state.publish = PublishPolicy(policies, unit, clock)
    app.state.flags = GateFlags(afrikaans_text=False, afrikaans_voice=False)
    allowed = ("image/jpeg", "image/png", "audio/ogg", "video/mp4")
    app.state.limits = GateLimits(
        max_bytes=_LIVE_BYTES if live else 100,
        max_audio_seconds=Decimal("30"),
        messages_per_minute=10 if live else 3,
        allowed_types=allowed + ("audio/webm", "audio/mp4") if live else allowed,
    )

    for conversation_id in conversations.ids(profile.tenant_id):
        release = getattr(conversations, "release_claims", None)
        if release is not None:
            release(profile.tenant_id)
            break

    def run_turn() -> None:
        tenants = getattr(app.state, "tenant_ids", None) or (app.state.tenant_id,)
        for tenant_id in tenants:
            context = TenantContext(tenant_id=tenant_id)
            for conversation_id in conversations.ids(tenant_id):
                turn.execute(context, conversation_id)

    app.state.run_turn = run_turn
