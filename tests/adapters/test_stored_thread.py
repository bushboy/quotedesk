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
from quotedesk.infrastructure.stored import StoredThread, open_thread

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
    opened = open_thread(URL)
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

        restarted = StoredThread(URL)
        restarted.conversations.tenant_id = TENANT
        loaded = restarted.conversations.get(TENANT, conversation_id)
        assert loaded is not None
        assert loaded.events[0].body == "5 by 7 metres"
        assert restarted.conversations.messages(TENANT, conversation_id)[0].kind == "text"
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
