"""The live stores round-trip a thread, a case, and a quote without downgrading the database."""

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from quotedesk.adapters.outbound.persistence.records import bind_tenant
from quotedesk.application.dto.audit import AuditEvent
from quotedesk.application.dto.inbound import InboundMessage
from quotedesk.domain.case.case_file import CaseFile
from quotedesk.domain.conversation.events import Conversation
from quotedesk.domain.policy.rules import Outcome
from quotedesk.domain.quotes.quote import Quote, QuoteLine
from quotedesk.domain.shared.ids import QuoteId
from quotedesk.domain.shared.money import Money
from quotedesk.infrastructure.db import engine
from quotedesk.adapters.outbound.persistence.stored import StoredThread, open_thread
from quotedesk.infrastructure.demo import Unit

URL = "postgresql+psycopg://quotedesk:quotedesk@127.0.0.1:5432/quotedesk"
TENANT = UUID("11111111-1111-4111-8111-111111111111")
WHEN = datetime(2026, 10, 29, 18, 0, tzinfo=timezone.utc)
QUOTE = QuoteId("QD-9088")


def _erase(database, conversation_id: UUID) -> None:
    with database.begin() as connection:
        bind_tenant(connection, TENANT)
        connection.execute(text("DELETE FROM quote WHERE quote_id = :quote_id"), {"quote_id": QUOTE.value})
        connection.execute(
            text("DELETE FROM sender_bind WHERE conversation_id = :conversation_id"),
            {"conversation_id": conversation_id},
        )
        connection.execute(
            text("DELETE FROM case_file WHERE conversation_id = :conversation_id"),
            {"conversation_id": conversation_id},
        )
        connection.execute(
            text("DELETE FROM conversation WHERE conversation_id = :conversation_id"),
            {"conversation_id": conversation_id},
        )


def test_a_restart_reads_the_thread_the_case_and_the_quote():
    try:
        with engine(URL).connect():
            pass
    except OperationalError:
        pytest.skip("PostgreSQL is not listening on 127.0.0.1:5432.")
    command.upgrade(Config("alembic.ini"), "head")
    opened = open_thread(URL, Unit)
    assert opened is not None
    opened.conversations.tenant_id = TENANT
    conversation_id = uuid4()
    database = opened.engine
    try:
        conversation = Conversation.open(conversation_id).append("m1", WHEN, "5 by 7 metres").conversation
        opened.conversations.save(TENANT, conversation)
        opened.conversations.bind(TENANT, "15559998888", conversation_id)
        opened.conversations.remember(
            TENANT,
            InboundMessage(
                conversation_id=conversation_id,
                provider_message_id="m1",
                wa_id="15559998888",
                at=WHEN,
                kind="text",
                body="5 by 7 metres",
            ),
        )
        opened.conversations.record_reply(TENANT, conversation_id, WHEN, "The indicative range is R 8500.00.")
        opened.conversations.rename(TENANT, "15559998888", "Lerato")
        longer = conversation.append("m2", WHEN, "Economy sheeting").conversation
        opened.conversations.save(TENANT, longer)
        case = (
            CaseFile.open(conversation_id, TENANT)
            .add_job("carport", "carport")
            .record_fact("carport", uuid4(), "size", "5 x 7 meters", "customer_text", uuid4())
        )
        opened.cases.save(TENANT, case)
        quote = Quote.open(QUOTE, date(2026, 11, 12)).set_lines(
            1,
            (
                QuoteLine(
                    item_code="SHEET-ECO",
                    description="Economy sheeting",
                    quantity=Decimal("1"),
                    unit_price=Money("8500.00"),
                    total=Money("8500.00"),
                ),
            ),
        )
        issued = quote.issue(Outcome.INDICATIVE_RANGE, version=1, at=WHEN)
        opened.unit.save_quote(TENANT, conversation_id, issued)
        opened.unit.record_audit(
            AuditEvent(tenant_id=TENANT, action="quote.issued", quote_id=QUOTE, version=1)
        )
        opened.unit.commit()

        restarted = StoredThread(URL, Unit)
        restarted.conversations.tenant_id = TENANT
        loaded = restarted.conversations.get(TENANT, conversation_id)
        assert loaded is not None
        assert loaded.events[0].body == "5 by 7 metres"
        assert restarted.conversations.messages(TENANT, conversation_id)[0].kind == "text"
        heard = restarted.conversations.heard(TENANT)
        assert any(message.wa_id == "15559998888" and message.body == "5 by 7 metres" for message in heard)
        assert restarted.conversations.name(TENANT, "15559998888") == "Lerato"
        assert restarted.conversations.sender_for(TENANT, conversation_id) == "15559998888"
        transcript = restarted.conversations.transcript(TENANT, "15559998888")
        assert [row["side"] for row in transcript] == ["out", "out", "in"]
        assert "8500.00" in transcript[2]["body"]
        assert len(loaded.events) == 2
        restored = restarted.cases.get(TENANT, conversation_id)
        assert restored is not None
        assert restored.jobs[0].facts[0].value == "5 x 7 meters"
        found = restarted.unit.read_quote(TENANT, QUOTE)
        assert found is not None
        assert found.current.lines[0].total == Money("8500.00")
        assert restarted.ids.next_quote_id().value.startswith("QD-")
    finally:
        _erase(database, conversation_id)


OTHER = UUID("22222222-2222-4222-8222-222222222222")


def test_a_message_is_stored_for_the_tenant_that_sends_it():
    try:
        with engine(URL).connect():
            pass
    except OperationalError:
        pytest.skip("PostgreSQL is not listening on 127.0.0.1:5432.")
    command.upgrade(Config("alembic.ini"), "head")
    opened = open_thread(URL, Unit)
    assert opened is not None
    conversation_id = uuid4()
    database = opened.engine
    placed = None
    try:
        opened.conversations.save(TENANT, Conversation.open(conversation_id).append("a1", WHEN, "aqua").conversation)
        with database.begin() as connection:
            bind_tenant(connection, OTHER)
            connection.execute(
                text(
                    """
                    INSERT INTO conversation_event (
                        conversation_id, tenant_id, provider_message_id, at, body, arrival
                    )
                    VALUES (:conversation_id, :tenant_id, 'b1', :at, 'Good morning', 0)
                    """
                ),
                {"conversation_id": conversation_id, "tenant_id": OTHER, "at": WHEN},
            )
        placed = opened.conversations.place(OTHER, conversation_id)
        assert placed != conversation_id
        assert opened.conversations.place(OTHER, placed) == placed
        owned = opened.conversations.get(OTHER, placed)
        assert owned is not None
        assert owned.events[0].body == "Good morning"
        assert placed in opened.conversations.ids(OTHER)
        assert conversation_id not in opened.conversations.ids(OTHER)
        kept = opened.conversations.get(TENANT, conversation_id)
        assert kept is not None
        assert kept.events[0].body == "aqua"
        opened.conversations.save(
            OTHER,
            owned.append("b2", WHEN, "A 6 by 4 metre carport.").conversation,
        )
        reread = opened.conversations.get(OTHER, placed)
        assert reread is not None
        assert [event.body for event in reread.events] == ["Good morning", "A 6 by 4 metre carport."]
    finally:
        _erase(database, conversation_id)
        if placed is not None:
            _erase_as(database, OTHER, placed)


def _erase_as(database, tenant_id: UUID, conversation_id: UUID) -> None:
    with database.begin() as connection:
        bind_tenant(connection, tenant_id)
        connection.execute(
            text("DELETE FROM sender_bind WHERE conversation_id = :conversation_id"),
            {"conversation_id": conversation_id},
        )
        connection.execute(
            text("DELETE FROM case_file WHERE conversation_id = :conversation_id"),
            {"conversation_id": conversation_id},
        )
        connection.execute(
            text("DELETE FROM conversation WHERE conversation_id = :conversation_id"),
            {"conversation_id": conversation_id},
        )

