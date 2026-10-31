from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from quotedesk.adapters.outbound.persistence.quotes import QuoteTables
from quotedesk.adapters.outbound.persistence.records import CaseTables, ConversationTables, ScheduleTables
from quotedesk.domain.case.case_file import CaseFile
from quotedesk.domain.conversation.events import Conversation
from quotedesk.domain.quotes.quote import Approval
from quotedesk.domain.quotes.schedule import ScheduleCommitment
from quotedesk.infrastructure.db import engine
from tests.adapters.test_quote_tables import _quote

URL = "postgresql+psycopg://quotedesk:quotedesk@127.0.0.1:5432/quotedesk"
TENANT_A = UUID("11111111-1111-4111-8111-111111111111")
TENANT_B = UUID("22222222-2222-4222-8222-222222222222")
CONVERSATION_A = UUID("33333333-3333-4333-8333-333333333333")
CONVERSATION_B = UUID("44444444-4444-4444-8444-444444444444")
WHEN = datetime(2026, 10, 24, 0, 0, tzinfo=timezone.utc)
EARLIER = WHEN
LATER = WHEN + timedelta(minutes=10)


def _upgrade() -> None:
    command.upgrade(Config("alembic.ini"), "head")


def _set(connection, tenant_id: UUID | None) -> None:
    connection.execute(
        text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"),
        {"tenant_id": "" if tenant_id is None else str(tenant_id)},
    )


def test_rls_hides_other_tenants():
    _upgrade()
    database = engine(URL)
    connection = database.connect()
    transaction = connection.begin()
    try:
        _hide_other_tenants(connection)
    finally:
        transaction.rollback()
        connection.close()


def _hide_other_tenants(connection) -> None:
    for tenant, conversation, quote_id, policy_id in (
        (TENANT_A, CONVERSATION_A, "QD-1042", "water-policy-v1.0"),
        (TENANT_B, CONVERSATION_B, "QD-2042", "fab-policy-v1.0"),
    ):
        _set(connection, tenant)
        connection.execute(text("DELETE FROM policy_row WHERE tenant_id = :tenant_id"), {"tenant_id": tenant})
        connection.execute(text("DELETE FROM quote WHERE tenant_id = :tenant_id"), {"tenant_id": tenant})
        connection.execute(text("DELETE FROM case_fact WHERE tenant_id = :tenant_id"), {"tenant_id": tenant})
        connection.execute(text("DELETE FROM case_file WHERE tenant_id = :tenant_id"), {"tenant_id": tenant})
        connection.execute(
            text("DELETE FROM conversation_event WHERE tenant_id = :tenant_id"),
            {"tenant_id": tenant},
        )
        connection.execute(text("DELETE FROM conversation WHERE tenant_id = :tenant_id"), {"tenant_id": tenant})
        connection.execute(
            text("INSERT INTO quote (quote_id, tenant_id, conversation_id) VALUES (:quote_id, :tenant_id, :conversation_id)"),
            {"quote_id": quote_id, "tenant_id": tenant, "conversation_id": conversation},
        )
        connection.execute(
            text("INSERT INTO case_file (conversation_id, tenant_id) VALUES (:conversation_id, :tenant_id)"),
            {"conversation_id": conversation, "tenant_id": tenant},
        )
        connection.execute(
            text("INSERT INTO conversation (conversation_id, tenant_id) VALUES (:conversation_id, :tenant_id)"),
            {"conversation_id": conversation, "tenant_id": tenant},
        )
        connection.execute(
            text("INSERT INTO policy_row (tenant_id, policy_id) VALUES (:tenant_id, :policy_id)"),
            {"tenant_id": tenant, "policy_id": policy_id},
        )
        connection.execute(
            text("INSERT INTO audit_event (tenant_id, action, quote_id, version) VALUES (:tenant_id, 'quote.issued', :quote_id, 1)"),
            {"tenant_id": tenant, "quote_id": quote_id},
        )
    _set(connection, TENANT_A)
    visible = {
        "quote": connection.execute(text("SELECT quote_id FROM quote")).scalars().all(),
        "case_file": connection.execute(text("SELECT conversation_id FROM case_file")).scalars().all(),
        "conversation": connection.execute(text("SELECT conversation_id FROM conversation")).scalars().all(),
        "policy_row": connection.execute(text("SELECT tenant_id FROM policy_row")).scalars().all(),
        "audit_event": connection.execute(text("SELECT tenant_id FROM audit_event")).scalars().all(),
    }
    assert visible["quote"] == ["QD-1042"]
    assert visible["case_file"] == [CONVERSATION_A]
    assert visible["conversation"] == [CONVERSATION_A]
    assert TENANT_B not in visible["policy_row"]
    assert TENANT_A in visible["policy_row"]
    assert TENANT_B not in visible["audit_event"]
    assert TENANT_A in visible["audit_event"]
    _set(connection, None)
    for table in ("quote", "case_file", "conversation", "policy_row", "audit_event"):
        count = connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
        assert count == 0


def test_audit_is_insert_only():
    _upgrade()
    database = engine(URL)
    with database.connect() as connection:
        transaction = connection.begin()
        _set(connection, TENANT_A)
        connection.execute(
            text("INSERT INTO audit_event (tenant_id, action, quote_id, version) VALUES (:tenant_id, 'quote.issued', 'QD-1042', 1)"),
            {"tenant_id": TENANT_A},
        )
        inserted = connection.execute(text("SELECT count(*) FROM audit_event")).scalar_one()
        assert inserted >= 1
        for statement in (
            "UPDATE audit_event SET action = 'changed'",
            "DELETE FROM audit_event",
        ):
            nested = connection.begin_nested()
            with pytest.raises(ProgrammingError):
                connection.execute(text(statement))
            nested.rollback()
        transaction.rollback()


def test_quote_and_audit_commit_together():
    _upgrade()
    database = engine(URL)
    store = QuoteTables()
    saved = _quote()
    with database.begin() as connection:
        _set(connection, TENANT_A)
        connection.execute(text("DELETE FROM quote WHERE quote_id = 'QD-1042'"))
    with database.connect() as connection:
        transaction = connection.begin()
        store.save(connection, TENANT_A, CONVERSATION_A, saved)
        transaction.rollback()
    with database.connect() as connection:
        failed = connection.begin()
        try:
            with connection.begin_nested():
                store.save(connection, TENANT_A, CONVERSATION_A, saved)
                raise RuntimeError("between")
        except RuntimeError:
            pass
        failed.rollback()
    with database.begin() as connection:
        _set(connection, TENANT_A)
        quotes = connection.execute(text("SELECT count(*) FROM quote WHERE quote_id = 'QD-1042'")).scalar_one()
        audits = connection.execute(
            text("SELECT count(*) FROM audit_event WHERE quote_id = 'QD-1042' AND action = 'quote.and.audit'")
        ).scalar_one()
    assert quotes == 0
    assert audits == 0


def test_repositories_round_trip_the_aggregates():
    _upgrade()
    database = engine(URL)
    saved = _quote().apply_approval(
        1,
        Approval(applies_to_version=1, expires_at=WHEN + timedelta(days=1)),
        at=WHEN,
    )
    case = CaseFile.open(CONVERSATION_A, TENANT_A).add_job("tank", "replacement")
    first = uuid4()
    second = uuid4()
    case = case.record_fact("tank", first, "size_litres", "2500 L", "customer_text", uuid4())
    case = case.record_fact("tank", second, "size_litres", "5000 L", "customer_text", uuid4())
    conversation = Conversation.open(CONVERSATION_A)
    conversation = conversation.append("wamid.LATER", LATER, "second").conversation
    conversation = conversation.append("wamid.EARLIER", EARLIER, "first").conversation
    commitment = ScheduleCommitment(status="none", sentence="No window is held.")
    quotes = QuoteTables()
    cases = CaseTables()
    conversations = ConversationTables()
    schedules = ScheduleTables()
    with database.begin() as connection:
        quotes.save(connection, TENANT_A, CONVERSATION_A, saved)
        quotes.save_evidence(connection, TENANT_A, saved, ("mask-1",))
        cases.save(connection, case)
        conversations.save(connection, TENANT_A, conversation)
        schedules.save(connection, TENANT_A, saved.quote_id.value, commitment)
        loaded_quote = quotes.get(connection, TENANT_A, CONVERSATION_A)
        loaded_evidence = quotes.evidence(connection, TENANT_A, saved.quote_id.value, 1)
        loaded_case = cases.get(connection, TENANT_A, CONVERSATION_A)
        loaded_conversation = conversations.get(connection, TENANT_A, CONVERSATION_A)
        loaded_schedule = schedules.get(connection, TENANT_A, saved.quote_id.value)
    assert loaded_quote is not None
    assert loaded_quote.current.lines[0].item_code == "TANK-5000"
    assert loaded_quote.current.clauses[0].clause_id == "WATER-A1"
    assert loaded_evidence == ("mask-1",)
    assert loaded_quote.current.approvals[0].applies_to_version == 1
    assert loaded_schedule is not None
    assert loaded_schedule.status == "none"
    assert loaded_schedule.sentence == "No window is held."
    assert loaded_case is not None
    by_value = {fact.value: fact for fact in loaded_case.facts("tank")}
    assert by_value["2500 L"].superseded_by == second
    assert by_value["5000 L"].superseded_by is None
    assert loaded_conversation is not None
    assert [event.provider_message_id for event in loaded_conversation.log] == ["wamid.EARLIER", "wamid.LATER"]
    assert conversation.log[0].provider_message_id == "wamid.LATER"
