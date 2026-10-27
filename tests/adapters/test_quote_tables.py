import json
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from alembic import command
from alembic.config import Config
from sqlalchemy import text

from quotedesk.adapters.outbound.persistence.quotes import QuoteTables
from quotedesk.domain.policy.clauses import Condition
from quotedesk.domain.policy.rules import Outcome
from quotedesk.domain.quotes.quote import Quote, QuoteLine, QuoteState
from quotedesk.domain.shared.ids import QuoteId
from quotedesk.domain.shared.money import Money
from quotedesk.infrastructure.db import engine

TENANT = UUID("11111111-1111-4111-8111-111111111111")
CONVERSATION = UUID("33333333-3333-4333-8333-333333333333")
URL = "postgresql+psycopg://quotedesk:quotedesk@127.0.0.1:5432/quotedesk"
FIXTURE = Path("tests/fixtures/quotes/aquasure_5000l.json")
FORBIDDEN = ("case_file", "case_fact", "conversation", "conversation_event", "schedule")


def _quote() -> Quote:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    line = payload["line_items"][0]
    clauses = tuple(Condition(**clause) for clause in payload["clauses"])
    opened = Quote.open(QuoteId(payload["quote_id"]), date.fromisoformat(payload["expiry"]))
    drafted = opened.set_lines(
        1,
        (
            QuoteLine(
                item_code=line["item_code"],
                description=line["description"],
                quantity=Decimal(line["quantity"]),
                unit_price=Money(line["unit_price"]),
                total=Money(line["total"]),
            ),
        ),
    ).set_clauses(1, clauses)
    return drafted.issue(
        Outcome.FIXED_OFFER,
        version=1,
        at=datetime(2026, 10, 24, 0, 0, tzinfo=timezone.utc),
    )


def test_quote_tables_round_trip_the_5000l_quote():
    command.upgrade(Config("alembic.ini"), "head")
    store = QuoteTables()
    saved = _quote()
    database = engine(URL)
    with database.begin() as connection:
        names = {
            row.name
            for row in connection.execute(text("SELECT table_name AS name FROM information_schema.tables WHERE table_schema = 'public'"))
        }
        for forbidden in FORBIDDEN:
            assert forbidden not in names
        store.save(connection, TENANT, CONVERSATION, saved)
        loaded = store.get(connection, TENANT, CONVERSATION)
    assert loaded is not None
    assert loaded.current.number == saved.current.number == 1
    assert loaded.current.state is QuoteState.ISSUED
    assert loaded.current.lines[0].item_code == "TANK-5000"
    assert loaded.current.lines[0].description == "5000 L tank"
    assert loaded.current.lines[0].total == Money("4250.00")
    assert type(loaded.current.lines[0].total.amount) is Decimal
    assert [clause.clause_id for clause in loaded.current.clauses] == ["WATER-A1", "GEN-V1", "GEN-S1"]
    assert loaded.current.clauses[0].text == saved.current.clauses[0].text
    assert loaded.current.approvals == ()
