"""Postgres stores for the live chat.

The use cases keep calling the same ports. These classes open a transaction,
set the tenant, and use the table adapters. A closed database returns nothing;
the composition root does not replace it with memory.
"""

import logging
from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from quotedesk.adapters.outbound.persistence.quotes import QuoteTables
from quotedesk.adapters.outbound.persistence.records import CaseTables, ConversationTables, bind_tenant, hold_conversation
from quotedesk.adapters.outbound.persistence.commercial import (
    StoredAcceptances,
    StoredCapacity,
    StoredCodes,
    StoredHandovers,
    StoredInspections,
    StoredLinks,
    StoredNotices,
)
from quotedesk.domain.case.case_file import CaseFile
from quotedesk.domain.conversation.events import Conversation
from quotedesk.domain.shared.ids import QuoteId

_log = logging.getLogger(__name__)


def open_thread(database_url: str, memory):
    try:
        thread = StoredThread(database_url, memory)
        if not thread.ready():
            return None
    except SQLAlchemyError:
        _log.info("Conversation store is not reachable")
        return None
    _log.info("Conversation store source=postgres")
    return thread


class StoredThread:
    def __init__(self, database_url: str, memory) -> None:
        self.engine = create_engine(database_url, pool_pre_ping=True, connect_args={"connect_timeout": 1})
        self.cases = StoredCases(self.engine)
        self.conversations = StoredConversations(self.engine)
        self.unit = StoredUnit(self.engine, memory)
        self.ids = StoredIds(self.engine)
        self.codes = StoredCodes(self.engine)
        self.acceptances = StoredAcceptances(self.engine)
        self.links = StoredLinks(self.engine)
        self.capacity = StoredCapacity(self.engine)
        self.handovers = StoredHandovers(self.engine)
        self.inspections = StoredInspections(self.engine)
        self.notices = StoredNotices(self.engine)

    def ready(self) -> bool:
        with self.engine.connect() as connection:
            found = connection.execute(text("SELECT to_regclass('public.assistant_reply')")).scalar_one()
        return found is not None

    def bind(self) -> dict:
        return {
            "conversations": self.conversations,
            "cases": self.cases,
            "unit": self.unit,
            "ids": self.ids,
            "codes": self.codes,
            "acceptances": self.acceptances,
            "links": self.links,
            "capacity": self.capacity,
            "handovers": self.handovers,
            "inspections": self.inspections,
            "notices": self.notices,
        }

    def clear(self, tenant_id: UUID) -> None:
        with self.engine.begin() as connection:
            bind_tenant(connection, tenant_id)
            connection.execute(text("DELETE FROM quote WHERE tenant_id = :tenant_id"), {"tenant_id": tenant_id})
            connection.execute(
                text("DELETE FROM verification_code WHERE tenant_id = :tenant_id"),
                {"tenant_id": tenant_id},
            )
            connection.execute(text("DELETE FROM handover WHERE tenant_id = :tenant_id"), {"tenant_id": tenant_id})
            connection.execute(text("DELETE FROM inspection WHERE tenant_id = :tenant_id"), {"tenant_id": tenant_id})
            connection.execute(text("DELETE FROM owner_notice WHERE tenant_id = :tenant_id"), {"tenant_id": tenant_id})
            connection.execute(text("DELETE FROM acceptance WHERE tenant_id = :tenant_id"), {"tenant_id": tenant_id})
            connection.execute(text("DELETE FROM deposit_link WHERE tenant_id = :tenant_id"), {"tenant_id": tenant_id})
            connection.execute(text("DELETE FROM capacity_hold WHERE tenant_id = :tenant_id"), {"tenant_id": tenant_id})
            connection.execute(text("DELETE FROM capacity_slot WHERE tenant_id = :tenant_id"), {"tenant_id": tenant_id})
            connection.execute(
                text("DELETE FROM sender_bind WHERE tenant_id = :tenant_id"),
                {"tenant_id": tenant_id},
            )
            connection.execute(
                text("DELETE FROM case_file WHERE tenant_id = :tenant_id"),
                {"tenant_id": tenant_id},
            )
            connection.execute(
                text("DELETE FROM conversation WHERE tenant_id = :tenant_id"),
                {"tenant_id": tenant_id},
            )
            connection.execute(
                text("DELETE FROM enrichment WHERE tenant_id = :tenant_id"),
                {"tenant_id": tenant_id},
            )
        self.unit.committed.clear()


class StoredCases:
    def __init__(self, engine) -> None:
        self._engine = engine
        self._tables = CaseTables()

    def get(self, tenant_id: UUID, conversation_id: UUID) -> CaseFile | None:
        with self._engine.begin() as connection:
            return self._tables.get(connection, tenant_id, conversation_id)

    def save(self, tenant_id: UUID, case: CaseFile) -> None:
        with self._engine.begin() as connection:
            self._tables.save(connection, case)

    def ensure(self, tenant_id: UUID, conversation_id: UUID) -> None:
        if self.get(tenant_id, conversation_id) is None:
            self.save(tenant_id, CaseFile.open(conversation_id, tenant_id))


class StoredConversations:
    def __init__(self, engine) -> None:
        self._engine = engine
        self._tables = ConversationTables()
        self.tenant_id: UUID | None = None

    def get(self, tenant_id: UUID, conversation_id: UUID) -> Conversation | None:
        with self._engine.begin() as connection:
            return self._tables.get(connection, tenant_id, conversation_id)

    def save(self, tenant_id: UUID, conversation: Conversation) -> None:
        with self._engine.begin() as connection:
            self._tables.save(connection, tenant_id, conversation)

    def note(self, tenant_id: UUID, wa_id: str, at: datetime) -> None:
        return None

    def noted(self, tenant_id: UUID, wa_id: str) -> tuple[datetime, ...]:
        with self._engine.begin() as connection:
            bind_tenant(connection, tenant_id)
            rows = connection.execute(
                text(
                    """
                    SELECT at FROM inbound_message
                    WHERE tenant_id = :tenant_id AND wa_id = :wa_id
                    ORDER BY at
                    """
                ),
                {"tenant_id": tenant_id, "wa_id": wa_id},
            )
        return tuple(row.at for row in rows)

    def heard(self, tenant_id: UUID) -> tuple:
        """Every inbound message for this tenant, oldest first."""
        from quotedesk.application.dto.inbound import InboundMessage

        with self._engine.begin() as connection:
            bind_tenant(connection, tenant_id)
            rows = connection.execute(
                text(
                    """
                    SELECT conversation_id, provider_message_id, wa_id, at, kind, body, media_id, mime,
                           size_bytes, duration_seconds, transcript, image_text
                    FROM inbound_message
                    WHERE tenant_id = :tenant_id
                    ORDER BY at
                    """
                ),
                {"tenant_id": tenant_id},
            ).all()
        return tuple(
            InboundMessage(
                conversation_id=row.conversation_id,
                provider_message_id=row.provider_message_id,
                wa_id=row.wa_id,
                at=row.at,
                kind=row.kind,
                body=row.body,
                media_id=row.media_id,
                mime=row.mime,
                size_bytes=row.size_bytes,
                duration_seconds=Decimal(row.duration_seconds) if row.duration_seconds is not None else None,
                transcript=row.transcript,
                image_text=row.image_text,
            )
            for row in rows
        )

    def remember(self, tenant_id: UUID, message) -> None:
        with self._engine.begin() as connection:
            bind_tenant(connection, tenant_id)
            connection.execute(
                text(
                    """
                    INSERT INTO inbound_message (
                        tenant_id, provider_message_id, conversation_id, wa_id, at, kind, body,
                        media_id, mime, size_bytes, duration_seconds, transcript, image_text
                    )
                    VALUES (
                        :tenant_id, :provider_message_id, :conversation_id, :wa_id, :at, :kind, :body,
                        :media_id, :mime, :size_bytes, :duration_seconds, :transcript, :image_text
                    )
                    ON CONFLICT (tenant_id, provider_message_id) DO UPDATE SET
                        kind = EXCLUDED.kind,
                        body = EXCLUDED.body,
                        media_id = EXCLUDED.media_id,
                        mime = EXCLUDED.mime,
                        size_bytes = EXCLUDED.size_bytes,
                        duration_seconds = EXCLUDED.duration_seconds,
                        transcript = EXCLUDED.transcript,
                        image_text = EXCLUDED.image_text
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "provider_message_id": message.provider_message_id,
                    "conversation_id": message.conversation_id,
                    "wa_id": message.wa_id,
                    "at": message.at,
                    "kind": message.kind,
                    "body": message.body,
                    "media_id": message.media_id,
                    "mime": message.mime,
                    "size_bytes": message.size_bytes,
                    "duration_seconds": message.duration_seconds,
                    "transcript": message.transcript,
                    "image_text": message.image_text,
                },
            )

    def messages(self, tenant_id: UUID, conversation_id: UUID):
        from quotedesk.application.dto.inbound import InboundMessage

        with self._engine.begin() as connection:
            bind_tenant(connection, tenant_id)
            rows = connection.execute(
                text(
                    """
                    SELECT provider_message_id, wa_id, at, kind, body, media_id, mime, size_bytes,
                           duration_seconds, transcript, image_text
                    FROM inbound_message
                    WHERE tenant_id = :tenant_id AND conversation_id = :conversation_id
                    ORDER BY at
                    """
                ),
                {"tenant_id": tenant_id, "conversation_id": conversation_id},
            )
            return tuple(
                InboundMessage(
                    conversation_id=conversation_id,
                    provider_message_id=row.provider_message_id,
                    wa_id=row.wa_id,
                    at=row.at,
                    kind=row.kind,
                    body=row.body,
                    media_id=row.media_id,
                    mime=row.mime,
                    size_bytes=row.size_bytes,
                    duration_seconds=Decimal(row.duration_seconds) if row.duration_seconds is not None else None,
                    transcript=row.transcript,
                    image_text=row.image_text,
                )
                for row in rows
            )

    def find(self, tenant_id: UUID, wa_id: str) -> UUID | None:
        with self._engine.begin() as connection:
            bind_tenant(connection, tenant_id)
            row = connection.execute(
                text(
                    """
                    SELECT conversation_id FROM sender_bind
                    WHERE tenant_id = :tenant_id AND wa_id = :wa_id
                    """
                ),
                {"tenant_id": tenant_id, "wa_id": wa_id},
            ).one_or_none()
        return None if row is None else row.conversation_id

    def sender_for(self, tenant_id: UUID, conversation_id: UUID) -> str | None:
        with self._engine.begin() as connection:
            bind_tenant(connection, tenant_id)
            row = connection.execute(
                text(
                    """
                    SELECT wa_id FROM sender_bind
                    WHERE tenant_id = :tenant_id AND conversation_id = :conversation_id
                    LIMIT 1
                    """
                ),
                {"tenant_id": tenant_id, "conversation_id": conversation_id},
            ).one_or_none()
        return None if row is None else row.wa_id

    def name(self, tenant_id: UUID, wa_id: str) -> str | None:
        with self._engine.begin() as connection:
            bind_tenant(connection, tenant_id)
            row = connection.execute(
                text(
                    """
                    SELECT display_name FROM sender_bind
                    WHERE tenant_id = :tenant_id AND wa_id = :wa_id
                    """
                ),
                {"tenant_id": tenant_id, "wa_id": wa_id},
            ).one_or_none()
        if row is None or not row.display_name:
            return None
        return row.display_name

    def rename(self, tenant_id: UUID, wa_id: str, display_name: str) -> None:
        with self._engine.begin() as connection:
            bind_tenant(connection, tenant_id)
            connection.execute(
                text(
                    """
                    UPDATE sender_bind
                    SET display_name = :display_name
                    WHERE tenant_id = :tenant_id AND wa_id = :wa_id
                    """
                ),
                {"tenant_id": tenant_id, "wa_id": wa_id, "display_name": display_name},
            )

    def bind(self, tenant_id: UUID, wa_id: str, conversation_id: UUID) -> None:
        with self._engine.begin() as connection:
            bind_tenant(connection, tenant_id)
            connection.execute(
                text(
                    """
                    INSERT INTO sender_bind (tenant_id, wa_id, conversation_id)
                    VALUES (:tenant_id, :wa_id, :conversation_id)
                    ON CONFLICT (tenant_id, wa_id) DO UPDATE SET conversation_id = EXCLUDED.conversation_id
                    """
                ),
                {"tenant_id": tenant_id, "wa_id": wa_id, "conversation_id": conversation_id},
            )

    def taken(self, conversation_id: UUID) -> bool:
        if self.tenant_id is None:
            return False
        with self._engine.begin() as connection:
            bind_tenant(connection, self.tenant_id)
            row = connection.execute(
                text(
                    """
                    SELECT 1 FROM sender_bind
                    WHERE tenant_id = :tenant_id AND conversation_id = :conversation_id
                    """
                ),
                {"tenant_id": self.tenant_id, "conversation_id": conversation_id},
            ).first()
        return row is not None

    def place(self, tenant_id: UUID, conversation_id: UUID) -> UUID:
        """A conversation id this tenant owns.

        The same id can already be stored for another business. Row-level
        security hides that row, so messages written here would not come back
        on this tenant's turn. Those messages move onto a new conversation.
        """
        with self._engine.begin() as connection:
            bind_tenant(connection, tenant_id)
            if hold_conversation(connection, tenant_id, conversation_id):
                return conversation_id
            fresh = uuid4()
            connection.execute(
                text(
                    """
                    INSERT INTO conversation (conversation_id, tenant_id)
                    VALUES (:conversation_id, :tenant_id)
                    """
                ),
                {"conversation_id": fresh, "tenant_id": tenant_id},
            )
            _rehome(connection, conversation_id, fresh)
            return fresh

    def ids(self, tenant_id: UUID) -> tuple[UUID, ...]:
        with self._engine.begin() as connection:
            bind_tenant(connection, tenant_id)
            rows = connection.execute(
                text("SELECT conversation_id FROM conversation WHERE tenant_id = :tenant_id"),
                {"tenant_id": tenant_id},
            )
        return tuple(row.conversation_id for row in rows)

    def record_reply(self, tenant_id: UUID, conversation_id: UUID, at: datetime, body: str) -> None:
        with self._engine.begin() as connection:
            bind_tenant(connection, tenant_id)
            if not hold_conversation(connection, tenant_id, conversation_id):
                raise RuntimeError("That conversation belongs to another tenant.")
            connection.execute(
                text(
                    """
                    INSERT INTO assistant_reply (tenant_id, conversation_id, at, body)
                    VALUES (:tenant_id, :conversation_id, :at, :body)
                    """
                ),
                {"tenant_id": tenant_id, "conversation_id": conversation_id, "at": at, "body": body},
            )

    def claim_pending(self, tenant_id: UUID, conversation_id: UUID, ids: tuple[str, ...]) -> tuple[str, ...]:
        with self._engine.begin() as connection:
            return self._tables.claim_pending(connection, tenant_id, conversation_id, ids)

    def release_claims(self, tenant_id: UUID) -> None:
        with self._engine.begin() as connection:
            self._tables.release_claims(connection, tenant_id)

    def hold_escalation(self, tenant_id: UUID, conversation_id: UUID) -> None:
        with self._engine.begin() as connection:
            self._tables.hold_escalation(connection, tenant_id, conversation_id, True)

    def release_escalation(self, tenant_id: UUID, conversation_id: UUID) -> None:
        with self._engine.begin() as connection:
            self._tables.hold_escalation(connection, tenant_id, conversation_id, False)

    def escalation_held(self, tenant_id: UUID, conversation_id: UUID) -> bool:
        with self._engine.begin() as connection:
            return self._tables.escalation_held(connection, tenant_id, conversation_id)

    def save_enrichment(self, tenant_id: UUID, message_id: str, result) -> None:
        with self._engine.begin() as connection:
            self._tables.save_enrichment(connection, tenant_id, message_id, result.model_dump_json())

    def enrichment(self, tenant_id: UUID, message_id: str):
        from quotedesk.application.dto.agent import ExtractionResult

        with self._engine.begin() as connection:
            payload = self._tables.enrichment(connection, tenant_id, message_id)
        if payload is None:
            return None
        return ExtractionResult.model_validate_json(payload)

    def reserve_outbound(self, tenant_id: UUID, batch_id: str, conversation_id: UUID, at: datetime, body: str) -> str:
        with self._engine.begin() as connection:
            return self._tables.reserve_outbound(connection, tenant_id, batch_id, conversation_id, at, body)

    def finish_outbound(self, tenant_id: UUID, batch_id: str) -> None:
        with self._engine.begin() as connection:
            self._tables.finish_outbound(connection, tenant_id, batch_id)

    def unsent(self, tenant_id: UUID, conversation_id: UUID) -> tuple[str, str] | None:
        with self._engine.begin() as connection:
            return self._tables.unsent(connection, tenant_id, conversation_id)

    def change_key(self, tenant_id: UUID, conversation_id: UUID) -> str | None:
        with self._engine.begin() as connection:
            return self._tables.change_key(connection, tenant_id, conversation_id)

    def save_change_key(self, tenant_id: UUID, conversation_id: UUID, key: str | None) -> None:
        with self._engine.begin() as connection:
            self._tables.save_change_key(connection, tenant_id, conversation_id, key)

    def replies(self, tenant_id: UUID, conversation_id: UUID) -> tuple[tuple[datetime, str], ...]:
        with self._engine.begin() as connection:
            bind_tenant(connection, tenant_id)
            rows = connection.execute(
                text(
                    """
                    SELECT at, body FROM assistant_reply
                    WHERE tenant_id = :tenant_id AND conversation_id = :conversation_id
                    ORDER BY at, reply_id
                    """
                ),
                {"tenant_id": tenant_id, "conversation_id": conversation_id},
            )
        return tuple((row.at, row.body) for row in rows)

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


class StoredUnit:
    """A unit of work whose quote and audit commit is one database transaction.

    Operator changes stay on the in-memory unit. The quote card reads through
    `read_quote` so a restart still opens the card.
    """

    def __init__(self, engine, memory) -> None:
        self._memory = memory()
        self._engine = engine
        self._quotes = QuoteTables()

    def __getattr__(self, name: str):
        return getattr(self._memory, name)

    def get_quote(self, tenant_id: UUID, conversation_id: UUID):
        found = self._memory.get_quote(tenant_id, conversation_id)
        if found is not None:
            return found
        with self._engine.begin() as connection:
            loaded = self._quotes.get(connection, tenant_id, conversation_id)
        if loaded is not None:
            self._memory.committed[(tenant_id, conversation_id)] = loaded
        return loaded

    def read_quote(self, tenant_id: UUID, quote_id: QuoteId):
        for (stored, _), quote in self._memory.committed.items():
            if stored == tenant_id and quote.quote_id == quote_id:
                return quote
        with self._engine.begin() as connection:
            loaded = self._quotes.find(connection, tenant_id, quote_id.value)
        return loaded

    def list_quotes(self, tenant_id: UUID):
        with self._engine.begin() as connection:
            return self._quotes.list_for(connection, tenant_id)

    def list_quote_threads(self, tenant_id: UUID):
        with self._engine.begin() as connection:
            return self._quotes.threads(connection, tenant_id)

    def commit(self) -> None:
        with self._memory._commit_lock:
            self._persist()
            self._memory._apply()
        self._memory.rollback()

    def _persist(self) -> None:
        quote = self._memory._pending_quote
        key = self._memory._pending_key
        replace = self._memory._pending_replace
        audit = self._memory._pending_audit
        if quote is None and replace is None:
            if audit is None:
                return
        with self._engine.begin() as connection:
            chosen = None
            tenant_id = None
            conversation_id = None
            if replace is not None:
                tenant_id, chosen = replace
                conversation_id = _conversation_id(connection, tenant_id, chosen.quote_id.value)
                if conversation_id is None and key is not None:
                    conversation_id = key[1]
                    tenant_id = key[0]
            elif key is not None and quote is not None:
                tenant_id, conversation_id = key
                chosen = quote
            if chosen is not None and tenant_id is not None and conversation_id is not None:
                self._quotes.save(connection, tenant_id, conversation_id, chosen)
            if audit is not None:
                bind_tenant(connection, audit.tenant_id)
                connection.execute(
                    text(
                        """
                        INSERT INTO audit_event (tenant_id, action, quote_id, version)
                        VALUES (:tenant_id, :action, :quote_id, :version)
                        """
                    ),
                    {
                        "tenant_id": audit.tenant_id,
                        "action": audit.action,
                        "quote_id": audit.quote_id.value,
                        "version": audit.version,
                    },
                )


class StoredIds:
    def __init__(self, engine) -> None:
        self._engine = engine

    def next_quote_id(self) -> QuoteId:
        with self._engine.begin() as connection:
            number = connection.execute(text("SELECT nextval('quote_seq')")).scalar_one()
        return QuoteId(f"QD-{number}")

    def next_fact_id(self) -> UUID:
        return uuid4()

    def next_idempotency_key(self) -> str:
        return str(uuid4())


def _rehome(connection, previous: UUID, fresh: UUID) -> None:
    """Move this tenant's rows off a conversation id owned by someone else."""
    connection.execute(
        text(
            """
            INSERT INTO case_file (conversation_id, tenant_id)
            SELECT :fresh, tenant_id FROM case_file WHERE conversation_id = :previous
            """
        ),
        {"fresh": fresh, "previous": previous},
    )
    connection.execute(
        text("UPDATE case_fact SET conversation_id = :fresh WHERE conversation_id = :previous"),
        {"fresh": fresh, "previous": previous},
    )
    connection.execute(
        text("DELETE FROM case_file WHERE conversation_id = :previous"),
        {"previous": previous},
    )
    for table in ("conversation_event", "inbound_message", "assistant_reply", "quote", "handover"):
        connection.execute(
            text(f"UPDATE {table} SET conversation_id = :fresh WHERE conversation_id = :previous"),
            {"fresh": fresh, "previous": previous},
        )


def _conversation_id(connection, tenant_id: UUID, quote_id: str) -> UUID | None:
    bind_tenant(connection, tenant_id)
    row = connection.execute(
        text(
            """
            SELECT conversation_id FROM quote
            WHERE tenant_id = :tenant_id AND quote_id = :quote_id
            """
        ),
        {"tenant_id": tenant_id, "quote_id": quote_id},
    ).one_or_none()
    return None if row is None else row.conversation_id
