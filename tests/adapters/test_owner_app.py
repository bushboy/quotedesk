import html
import re
from datetime import date
from decimal import Decimal
from uuid import UUID

from fastapi.testclient import TestClient

from quotedesk.application.dto.agent import HandoverNote
from quotedesk.application.dto.inbound import InboundMessage
from quotedesk.domain.policy.rules import Outcome
from quotedesk.domain.quotes.quote import Quote, QuoteLine
from quotedesk.domain.shared.ids import QuoteId
from quotedesk.domain.shared.money import Money
from quotedesk.infrastructure.config import Settings
from quotedesk.infrastructure.main import create_app

TENANT_A = UUID("11111111-1111-4111-8111-111111111111")
TENANT_B = UUID("22222222-2222-4222-8222-222222222222")
FIRST = UUID("33333333-3333-4333-8333-333333333333")
SECOND = UUID("66666666-6666-4666-8666-666666666666")
_SQL = "ProgrammingError: (psycopg.errors.UndefinedColumn) column \"included\" does not exist [SQL: INSERT INTO quote_version ...]"


def _client(monkeypatch, password: str = "") -> TestClient:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    settings = Settings(
        database_url="postgresql://quotedesk:quotedesk@127.0.0.1:1/quotedesk",
        model="script",
        store="memory",
        owner_password=password,
    )
    return TestClient(create_app(settings))


def _plain(response) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(response.text)))


def _issued(app, tenant: UUID, conversation: UUID, quote_id: str, amount: str) -> None:
    now = app.state.clock.now()
    line = QuoteLine(item_code="TANK-5000", description="5000 L tank", quantity=Decimal("1"), unit_price=Money(amount), total=Money(amount))
    quote = Quote.open(QuoteId(quote_id), date(2030, 1, 1)).set_lines(1, (line,)).issue(Outcome.FIXED_OFFER, version=1, at=now)
    app.state.unit.committed[(tenant, conversation)] = quote


def _heard(app, tenant: UUID, conversation: UUID, wa_id: str, body: str) -> None:
    app.state.conversations.remember(
        tenant,
        InboundMessage(
            conversation_id=conversation,
            provider_message_id=f"wamid.{wa_id}.{body[:4]}",
            wa_id=wa_id,
            at=app.state.clock.now(),
            kind="text",
            body=body,
        ),
    )


def test_every_tab_opens(monkeypatch):
    client = _client(monkeypatch)
    for path in ("/console", "/console/inbox", "/console/quotes", "/console/customers", "/console/policy", "/console/settings"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert "Something went wrong" not in response.text
    assert "Sign-in off" in client.get("/console").text


def test_the_tiles_and_the_summary_agree_and_skip_other_tenants(monkeypatch):
    client = _client(monkeypatch)
    app = client.app
    _issued(app, TENANT_A, FIRST, "QD-1042", "4250.00")
    _heard(app, TENANT_A, FIRST, "27821110001", "I need a 5000 L tank")
    _issued(app, TENANT_B, SECOND, "QD-2042", "9999.00")
    _heard(app, TENANT_B, SECOND, "27821110002", "Someone else's carport")

    data = client.get("/console/summary").json()
    page = client.get("/console").text

    assert (data["customers"], data["quotes_sent"], data["quoted_value"]) == (1, 1, "4250.00")
    assert '<span class="value num" id="tile-customers">1</span>' in page
    assert '<span class="value num" id="tile-quotes">1</span>' in page
    assert 'id="tile-value">R 4 250.00</span>' in page
    assert "four thousand two hundred and fifty rand" in data["spoken"]
    assert "QD-2042" not in page
    assert "9 999" not in page


def test_an_empty_day_shows_zeros_and_empty_states(monkeypatch):
    client = _client(monkeypatch)
    page = client.get("/console").text
    assert '<span class="value num" id="tile-customers">0</span>' in page
    assert "No customer has been in touch yet." in page
    assert "No quote has gone out yet." in page
    assert client.get("/console/summary").json()["spoken"].startswith("Today, no customers wrote in.")


def test_a_leaked_database_error_never_reaches_the_owner(monkeypatch):
    client = _client(monkeypatch)
    client.app.state.conversations.hold_escalation(TENANT_A, FIRST)
    client.app.state.handovers.append(TENANT_A, HandoverNote(conversation_id=FIRST, reason=_SQL, brief=_SQL, at=client.app.state.clock.now()))
    for path in ("/console/inbox", f"/console/brief/{FIRST}"):
        text = client.get(path).text
        assert "psycopg" not in text
        assert "[SQL:" not in text
    assert "This brief could not be built." in _plain(client.get("/console/inbox"))


def test_a_failing_page_is_a_sentence_not_a_stack_trace(monkeypatch):
    client = _client(monkeypatch)

    class Broken:
        def heard(self, tenant_id):
            raise RuntimeError("psycopg exploded [SQL: SELECT 1]")

    client.app.state.conversations = Broken()
    response = client.get("/console/customers")
    assert response.status_code == 500
    assert "Something went wrong on this page." in response.text
    assert "psycopg" not in response.text


def test_the_case_page_shows_who_what_and_actions(monkeypatch):
    client = _client(monkeypatch)
    app = client.app
    app.state.conversations.bind(TENANT_A, "27821234567", FIRST)
    app.state.conversations.rename(TENANT_A, "27821234567", "Lerato")
    _heard(app, TENANT_A, FIRST, "27821234567", "My borehole pump is broken")
    app.state.conversations.hold_escalation(TENANT_A, FIRST)
    app.state.handovers.append(TENANT_A, HandoverNote(conversation_id=FIRST, reason="Not on the rate card.", brief="pump", at=app.state.clock.now()))

    page = _plain(client.get(f"/console/brief/{FIRST}"))

    assert "Lerato" in page
    assert "+27821234567" in page
    assert "Waiting for you" in page
    assert "My borehole pump is broken" in page
    assert "Release to assistant" in page
    assert "https://wa.me/27821234567" in client.get(f"/console/brief/{FIRST}").text
    assert "Customer:" in page


def test_sign_in_guards_every_owner_route(monkeypatch):
    client = _client(monkeypatch, password="s3cret")
    response = client.get("/console/quotes", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/console/login?next=/console/quotes"
    assert client.get("/console/summary").status_code == 401
    assert client.post("/console/approve", data={"quote_id": "QD-1042", "version": "1"}).status_code == 401
    assert client.post("/editor/publish", data={"reason": "x"}).status_code == 401
    assert client.get("/editor", follow_redirects=False).status_code == 303

    wrong = client.post("/console/login", data={"password": "nope", "next": "/console/quotes"})
    assert wrong.status_code == 401
    assert "That password is not right." in wrong.text

    right = client.post("/console/login", data={"password": "s3cret", "next": "/console/quotes"}, follow_redirects=False)
    assert right.status_code == 303
    assert right.headers["location"] == "/console/quotes"
    assert client.get("/console/quotes").status_code == 200
    assert "Sign out" in client.get("/console").text

    client.post("/console/logout")
    assert client.get("/console", follow_redirects=False).status_code == 303


def test_sign_in_never_sends_the_owner_off_the_console(monkeypatch):
    client = _client(monkeypatch, password="s3cret")
    response = client.post("/console/login", data={"password": "s3cret", "next": "https://evil.example/"}, follow_redirects=False)
    assert response.headers["location"] == "/console"


def test_owner_actions_are_listed_with_who_did_them(monkeypatch):
    client = _client(monkeypatch)
    client.app.state.conversations.hold_escalation(TENANT_A, FIRST)
    client.post("/console/release", data={"conversation_id": str(FIRST)})
    page = _plain(client.get("/console/settings"))
    assert "Released to the assistant" in page
    assert "Owner (sign-in off)" in page


def test_the_rate_card_restores_from_a_history_button(monkeypatch):
    client = _client(monkeypatch)
    draft = client.app.state.policies.draft(TENANT_A)
    form = {"deposit": "35", "reason": "Deposit up"}
    for index, row in enumerate(draft.rate_rows):
        form.update(
            {
                f"code-{index}": row.item_code,
                f"name-{index}": row.description,
                f"price-{index}": f"{row.unit_price:.2f}",
                f"unit-{index}": row.unit,
                f"role-{index}": row.role,
                f"applies-to-{index}": row.applies_to,
                f"job-types-{index}": ", ".join(row.job_types),
            }
        )
    published = client.post("/editor/publish", data=form, follow_redirects=False)
    assert published.status_code == 303
    assert published.headers["location"].startswith("/console/policy?published=")
    page = client.get("/console/policy").text
    assert "Restore water-policy-v1.0" in page
    assert "“Deposit up”" in html.unescape(page)
    restored = client.post(
        "/console/policy/rollback",
        data={"source_version": "water-policy-v1.0", "reason": "Back to 30"},
        follow_redirects=False,
    )
    assert restored.status_code == 303
    live = client.app.state.policies.published(TENANT_A)
    assert live.clause_policy.settings["deposit_percent"] == 30


def test_quotes_can_be_searched_and_filtered(monkeypatch):
    client = _client(monkeypatch)
    _issued(client.app, TENANT_A, FIRST, "QD-1042", "4250.00")
    _issued(client.app, TENANT_A, SECOND, "QD-1043", "7900.00")
    assert "QD-1043" not in client.get("/console/quotes", params={"q": "QD-1042"}).text
    assert "QD-1042" in client.get("/console/quotes", params={"status": "issued"}).text
    assert "No quote matches that search." in client.get("/console/quotes", params={"status": "expired"}).text
