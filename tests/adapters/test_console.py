import html
import re
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi.testclient import TestClient

from quotedesk.adapters.inbound.http.console import percent, quote_amount, rand
from quotedesk.application.dto.agent import HandoverNote
from quotedesk.application.dto.changes import ChangeRecord
from quotedesk.application.dto.inbound import InboundMessage
from quotedesk.application.dto.tool_outputs import RequestChangeResult
from quotedesk.domain.policy.rules import Outcome
from quotedesk.domain.quotes.quote import Quote, QuoteLine, QuoteState
from quotedesk.domain.shared.ids import QuoteId
from quotedesk.domain.shared.money import Money
from quotedesk.infrastructure.config import Settings
from quotedesk.infrastructure.main import create_app

TENANT_A = UUID("11111111-1111-4111-8111-111111111111")
FIRST = UUID("33333333-3333-4333-8333-333333333333")
SECOND = UUID("66666666-6666-4666-8666-666666666666")
ISSUED_AT = datetime(2026, 10, 24, 0, 0, tzinfo=timezone.utc)
EXPIRY = date(2026, 11, 7)


def pending_quote(quote_id: str) -> Quote:
    line = QuoteLine(
        item_code="TANK-5000",
        description="5000 L tank",
        quantity=Decimal("1"),
        unit_price=Money("4250.00"),
        total=Money("4250.00"),
    )
    quote = Quote.open(QuoteId(quote_id), EXPIRY)
    quote = quote.set_lines(1, (line,))
    quote = quote.issue(Outcome.FIXED_OFFER, version=1, at=ISSUED_AT)
    return quote.transition(1, QuoteState.PENDING_APPROVAL, at=ISSUED_AT)


def seed(app, quote_id: str, conversation: UUID) -> Quote:
    quote = pending_quote(quote_id)
    current = quote.current
    app.state.unit.committed[(TENANT_A, conversation)] = quote
    app.state.unit.changes[(TENANT_A, f"change-{quote_id}")] = ChangeRecord(
        tenant_id=TENANT_A,
        idempotency_key=f"change-{quote_id}",
        requested_discount_percent=Decimal("10"),
        result=RequestChangeResult(
            quote_id=quote.quote_id,
            version=current.number,
            state=current.state,
            discount_percent=Decimal("0"),
            lines=current.lines,
            clauses=current.clauses,
        ),
    )
    return quote


def _client(monkeypatch) -> TestClient:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    app = create_app(Settings(database_url="postgresql://quotedesk:quotedesk@127.0.0.1:1/quotedesk", model="script", store="memory"))
    return TestClient(app)


def _text(response) -> str:
    return html.unescape(response.text)


def _plain(page: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", page))


def _queue(page: str) -> str:
    return page.split('id="queue"', 1)[1]


def _activity(page: str) -> str:
    return page.split('id="activity"', 1)[1].split('id="approvals"', 1)[0]


def test_console_lists_the_pending_ask(monkeypatch):
    client = _client(monkeypatch)
    seed(client.app, "QD-1042", FIRST)

    response = client.get("/console")
    page = _text(response)

    assert response.status_code == 200
    queue = _queue(page)
    assert "QD-1042" in queue
    assert "Version 1" in queue
    assert "10%" in queue
    assert "5%" in queue
    assert "R 4 250.00" in queue
    assert "disabled" not in queue.split("</form>")[0]
    assert "WhatsApp" not in page
    assert "Meta" not in page


def test_approve_issues_the_next_version_and_leaves_the_queue(monkeypatch):
    client = _client(monkeypatch)
    seed(client.app, "QD-1042", FIRST)

    response = client.post("/console/approve", data={"quote_id": "QD-1042", "version": "1"})
    page = _text(response)

    assert response.status_code == 200
    assert "QD-1042 approved" in page
    assert "Version 2 · Issued · R 3 825.00" in _plain(page)
    assert "There is nothing waiting." in page
    stored = client.app.state.unit.committed[(TENANT_A, FIRST)]
    assert stored.current.number == 2
    assert stored.current.state is QuoteState.ISSUED
    assert client.app.state.unit.audits[-1].action == "quote.approved"

    again = _text(client.get("/console"))
    assert "QD-1042" not in _queue(again)
    assert "There is nothing waiting." in again
    assert "QD-1042" in _activity(again)


def test_approval_expires_seven_days_after_the_app_clock(monkeypatch):
    client = _client(monkeypatch)
    seed(client.app, "QD-1042", FIRST)
    before = client.app.state.clock.now()

    client.post("/console/approve", data={"quote_id": "QD-1042", "version": "1"})

    approvals = [a for v in client.app.state.unit.committed[(TENANT_A, FIRST)].versions for a in v.approvals]
    assert len(approvals) == 1
    days = (approvals[0].expires_at - before).total_seconds() / 86400
    assert 6.99 < days < 7.01


def test_reject_keeps_the_price_on_a_second_pending_quote(monkeypatch):
    client = _client(monkeypatch)
    seed(client.app, "QD-1042", FIRST)
    seed(client.app, "QD-2042", SECOND)

    page = _text(client.post("/console/reject", data={"quote_id": "QD-2042", "version": "1"}))

    assert "QD-2042 rejected" in page
    assert "Version 1 · Issued · R 4 250.00" in _plain(page)
    queue = _queue(page)
    assert "QD-1042" in queue
    assert "QD-2042" not in queue
    assert client.app.state.unit.committed[(TENANT_A, SECOND)].current.state is QuoteState.ISSUED


def test_an_empty_queue_says_nothing_is_waiting(monkeypatch):
    page = _text(_client(monkeypatch).get("/console"))
    assert "There is nothing waiting." in page
    assert "Approve" not in _queue(page)


def test_the_form_cannot_set_the_total_or_the_percent(monkeypatch):
    client = _client(monkeypatch)
    seed(client.app, "QD-1042", FIRST)

    page = _text(
        client.post(
            "/console/approve",
            data={"quote_id": "QD-1042", "version": "1", "total": "1.00", "discount_percent": "99"},
        )
    )

    assert "R 3 825.00" in page


def test_a_second_approve_is_a_sentence_not_a_500(monkeypatch):
    client = _client(monkeypatch)
    seed(client.app, "QD-1042", FIRST)
    client.post("/console/approve", data={"quote_id": "QD-1042", "version": "1"})

    response = client.post("/console/approve", data={"quote_id": "QD-1042", "version": "1"})

    assert response.status_code == 409
    assert "That quote is not waiting for approval." in _text(response)
    assert client.app.state.unit.committed[(TENANT_A, FIRST)].current.number == 2


def test_a_stale_version_is_refused(monkeypatch):
    client = _client(monkeypatch)
    seed(client.app, "QD-1042", FIRST)

    response = client.post("/console/approve", data={"quote_id": "QD-1042", "version": "2"})

    assert response.status_code == 409
    assert "That version is no longer the current quote." in _text(response)
    assert "QD-1042" in _queue(_text(response))


def test_malformed_posts_read_as_sentences(monkeypatch):
    client = _client(monkeypatch)

    bad_id = client.post("/console/approve", data={"quote_id": "<script>", "version": "1"})
    assert bad_id.status_code == 409
    assert "A quote id looks like QD-0001." in _text(bad_id)
    assert "&lt;script&gt;" not in bad_id.text

    bad_version = client.post("/console/reject", data={"quote_id": "QD-1042", "version": "one"})
    assert bad_version.status_code == 400
    assert "That version is not a number." in _text(bad_version)

    missing = client.post("/console/approve", data={"quote_id": "QD-9999", "version": "1"})
    assert missing.status_code == 409
    assert "That quote is not on this tenant." in _text(missing)


def test_an_unknown_result_key_shows_no_outcome(monkeypatch):
    page = _text(_client(monkeypatch).get("/console?done=nope&action=approved"))
    assert "approved" not in page.split('id="outcome"', 1)[1].split('id="queue"', 1)[0]


def test_money_and_percent_are_formatted_from_decimals():
    assert rand(Money("4250.00")) == "R 4 250.00"
    assert rand(Money("1234567.5")) == "R 1 234 567.50"
    assert rand(Money("0")) == "R 0.00"
    assert percent(Decimal("10")) == "10"
    assert percent(Decimal("12.50")) == "12.5"


def test_activity_lists_contacts_and_quotes_that_went_out(monkeypatch):
    client = _client(monkeypatch)
    seed(client.app, "QD-1042", FIRST)
    at = datetime(2026, 10, 28, 12, 5, tzinfo=timezone.utc)
    for n, body in enumerate(("Hi, I need a 5000 L tank", "Can you do 10% off?")):
        client.app.state.conversations.remember(
            TENANT_A,
            InboundMessage(
                conversation_id=FIRST,
                provider_message_id=f"wamid.{n}",
                wa_id="27821234567",
                at=at.replace(minute=n),
                kind="text",
                body=body,
            ),
        )

    activity = _plain(_activity(_text(client.get("/console"))))

    assert "+27821234567" in activity
    assert "Can you do 10% off?" in activity
    assert "2 messages" in activity
    assert "28 Oct 14:01" in activity
    assert "QD-1042" in activity
    assert "Pending approval" in activity
    assert "R 4 250.00" in activity


def test_a_range_quote_shows_the_range_not_zero(monkeypatch):
    client = _client(monkeypatch)
    quote = Quote.open(QuoteId("QD-2000"), EXPIRY)
    quote = quote.set_terms(
        1,
        price_type="range",
        range_min=Money("12600.00"),
        range_max=Money("18200.00"),
        deposit=Money("3780.00"),
        site_visit_fee=None,
    )
    quote = quote.issue(Outcome.INDICATIVE_RANGE, version=1, at=ISSUED_AT)
    quote = quote.transition(1, QuoteState.WAITING_FOR_DEPOSIT, at=ISSUED_AT)
    client.app.state.unit.committed[(TENANT_A, FIRST)] = quote

    quotes = _plain(_activity(_text(client.get("/console")))).split("Quotes sent", 1)[1]

    assert "QD-2000" in quotes
    assert "Waiting for deposit" in quotes
    assert "R 12 600.00 to R 18 200.00" in quotes
    assert "Deposit R 3 780.00" in quotes
    assert "R 0.00" not in quotes
    same = quote.current.model_copy(update={"range_max": Money("12600.00")})
    assert quote_amount(same) == "R 12 600.00"


def test_activity_reads_contacts_the_store_has_saved(monkeypatch):
    client = _client(monkeypatch)
    at = datetime(2026, 10, 28, 12, 1, tzinfo=timezone.utc)
    saved = InboundMessage(
        conversation_id=FIRST,
        provider_message_id="wamid.saved",
        wa_id="27821234567",
        at=at,
        kind="text",
        body="Can you do 10% off?",
    )

    class Saved:
        def heard(self, tenant_id):
            assert tenant_id == TENANT_A
            return (saved,)

    client.app.state.conversations = Saved()
    activity = _plain(_activity(_text(client.get("/console"))))
    assert "+27821234567" in activity
    assert "Can you do 10% off?" in activity
    assert "1 message" in activity


def test_a_quote_shows_the_contact_it_was_sent_to(monkeypatch):
    client = _client(monkeypatch)
    seed(client.app, "QD-1042", FIRST)
    client.app.state.conversations.bind(TENANT_A, "27821234567", FIRST)
    client.app.state.conversations.rename(TENANT_A, "27821234567", "Lerato")
    client.app.state.conversations.remember(
        TENANT_A,
        InboundMessage(
            conversation_id=FIRST,
            provider_message_id="wamid.named",
            wa_id="27821234567",
            at=datetime(2026, 10, 28, 12, 1, tzinfo=timezone.utc),
            kind="text",
            body="Please quote a 5000 L tank",
        ),
    )

    activity = _plain(_activity(_text(client.get("/console"))))
    contacts = activity.split("Quotes sent", 1)[0]
    quotes = activity.split("Quotes sent", 1)[1]
    assert "Lerato" in contacts
    assert "+27821234567" in contacts
    assert "QD-1042" in quotes
    assert "Lerato · +27821234567" in quotes


def test_a_sent_quote_shows_the_message_the_customer_received(monkeypatch):
    client = _client(monkeypatch)
    quote = Quote.open(QuoteId("QD-2000"), EXPIRY)
    quote = quote.set_terms(
        1,
        price_type="range",
        range_min=Money("12600.00"),
        range_max=Money("12600.00"),
        deposit=Money("3780.00"),
        site_visit_fee=None,
    )
    quote = quote.issue(Outcome.INDICATIVE_RANGE, version=1, at=ISSUED_AT)
    quote = quote.transition(1, QuoteState.WAITING_FOR_DEPOSIT, at=ISSUED_AT)
    client.app.state.unit.committed[(TENANT_A, FIRST)] = quote
    client.app.state.conversations.record_reply(
        TENANT_A,
        FIRST,
        ISSUED_AT,
        "The indicative range is R 12600.00. /card/QD-2000?code=6233",
    )
    client.app.state.conversations.record_reply(
        TENANT_A,
        FIRST,
        ISSUED_AT,
        "I'll accept that quote and get your deposit link ready. https://sandbox.payfast.example/deposit/QD-2000",
    )

    page = _text(client.get("/console"))
    quotes = _plain(_activity(page)).split("Quotes sent", 1)[1]

    assert "The indicative range is R 12600.00. /card/QD-2000?code=6233" in quotes
    assert 'class="money">Quote <span class="amount">R 12 600.00</span>' in page
    assert 'class="money">Deposit <span class="amount">R 3 780.00</span>' in page
    assert "deposit link" not in quotes


def test_activity_is_empty_before_anyone_writes(monkeypatch):
    activity = _activity(_text(_client(monkeypatch).get("/console")))
    assert "No customer has been in touch yet." in activity
    assert "No quote has gone out yet." in activity


def test_the_console_is_one_page_with_no_tabs(monkeypatch):
    page = _text(_client(monkeypatch).get("/console"))
    assert "<nav" not in page
    assert 'id="policy"' in page
    assert 'action="/editor/publish"' in page


def test_the_owner_can_release_a_held_conversation(monkeypatch):
    client = _client(monkeypatch)
    client.app.state.conversations.hold_escalation(TENANT_A, FIRST)
    client.app.state.handovers.append(
        TENANT_A,
        HandoverNote(conversation_id=FIRST, reason="The turn produced no reply.", brief="replacement", at=ISSUED_AT),
    )
    page = _text(client.get("/console"))
    assert 'action="/console/release"' in page
    assert str(FIRST) in page
    response = client.post("/console/release", data={"conversation_id": str(FIRST)}, follow_redirects=False)
    assert response.status_code == 303
    assert not client.app.state.conversations.escalation_held(TENANT_A, FIRST)
