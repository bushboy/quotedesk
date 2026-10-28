import html
import re
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi.testclient import TestClient

from quotedesk.domain.policy.clauses import Condition
from quotedesk.domain.policy.rules import Outcome
from quotedesk.domain.quotes.quote import Quote, QuoteLine
from quotedesk.domain.shared.ids import QuoteId
from quotedesk.domain.shared.money import Money
from quotedesk.infrastructure.config import Settings
from quotedesk.infrastructure.main import create_app

TENANT_A = UUID("11111111-1111-4111-8111-111111111111")
CONVERSATION = UUID("33333333-3333-4333-8333-333333333333")
ISSUED_AT = datetime(2026, 10, 24, 0, 0, tzinfo=timezone.utc)
DEPOSIT = "A deposit percent is a whole number from 0 to 99."
EXCLUSION = Condition(
    clause_id="WATER-X1",
    clause_version="1",
    kind="exclusion",
    text="Excludes moving the old tank off site",
    if_not_true="Customer's responsibility; stated, not handled",
)


def _client(monkeypatch) -> TestClient:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    app = create_app(Settings(database_url="postgresql://quotedesk:quotedesk@127.0.0.1:1/quotedesk", model="script"))
    return TestClient(app)


def _text(response) -> str:
    return html.unescape(response.text)


def _published(client: TestClient):
    return client.app.state.policies.published(TENANT_A)


def _issued_quote() -> Quote:
    line = QuoteLine(
        item_code="TANK-5000",
        description="5000 L tank",
        quantity=Decimal("1"),
        unit_price=Money("4250.00"),
        total=Money("4250.00"),
    )
    quote = Quote.open(QuoteId("QD-1042"), date(2026, 11, 7))
    quote = quote.set_lines(1, (line,))
    quote = quote.set_clauses(1, (EXCLUSION,))
    return quote.issue(Outcome.FIXED_OFFER, version=1, at=ISSUED_AT)


def _publish_disabled(page: str) -> bool:
    button = re.search(r"<button[^>]*id=\"publish\"[^>]*>", page)
    assert button is not None
    return " disabled" in button.group(0)


def test_the_editor_starts_from_the_published_bundle(monkeypatch):
    client = _client(monkeypatch)
    bundle = _published(client)

    page = _text(client.get("/editor"))

    assert bundle.policy.version.value in page
    assert 'value="30"' in page
    assert _publish_disabled(page)
    assert "WhatsApp" not in page
    draft = client.app.state.policies.draft(TENANT_A)
    assert draft.deposit_percent == 30
    assert all(rule.enabled for rule in draft.rules)
    assert len(draft.rules) == len(bundle.policy.rules)


def test_a_deposit_of_100_is_refused_and_the_bundle_stays(monkeypatch):
    client = _client(monkeypatch)
    before = _published(client)

    response = client.post("/editor/publish", data={"deposit": "100", "reason": "Testing"})
    page = _text(response)

    assert response.status_code == 422
    assert DEPOSIT in page
    assert _publish_disabled(page)
    assert _published(client) == before
    assert _published(client).clause_policy.settings["deposit_percent"] == 30


def test_a_deposit_of_40_publishes_a_new_version(monkeypatch):
    client = _client(monkeypatch)
    client.app.state.unit.committed[(TENANT_A, CONVERSATION)] = _issued_quote()
    before = _published(client)
    draft_before = client.app.state.policies.draft(TENANT_A)

    response = client.post("/editor/publish", data={"deposit": "40", "reason": "Steel went up"})
    page = _text(response)

    after = _published(client)
    assert response.status_code == 200
    assert after.policy.version != before.policy.version
    assert f"Published {after.policy.version.value}" in page
    assert after.clause_policy.settings["deposit_percent"] == 40
    assert client.app.state.policies.get(TENANT_A, before.policy.version) == before
    issued = client.app.state.unit.committed[(TENANT_A, CONVERSATION)]
    assert issued.current.number == 1
    assert issued.current.clauses == (EXCLUSION,)
    draft = client.app.state.policies.draft(TENANT_A)
    assert draft == draft_before.model_copy(update={"deposit_percent": 40})


def test_a_blank_reason_is_refused(monkeypatch):
    client = _client(monkeypatch)
    before = _published(client)

    response = client.post("/editor/publish", data={"deposit": "40", "reason": "   "})

    assert response.status_code == 422
    assert "A publish needs a reason." in _text(response)
    assert _published(client) == before


def test_the_draft_check_answers_with_validate_policy_sentences(monkeypatch):
    client = _client(monkeypatch)
    before = _published(client)
    headers = {"Accept": "application/json"}

    wrong = client.post("/editor/draft", data={"deposit": "100"}, headers=headers)
    right = client.post("/editor/draft", data={"deposit": "40"}, headers=headers)

    assert wrong.json() == {"errors": [DEPOSIT]}
    assert right.json() == {"errors": []}
    assert client.app.state.policies.draft(TENANT_A).deposit_percent == 40
    assert _published(client) == before


def test_the_draft_check_without_script_keeps_the_reason(monkeypatch):
    client = _client(monkeypatch)

    page = _text(client.post("/editor/draft", data={"deposit": "40", "reason": "Steel went up"}))

    assert "Steel went up" in page
    assert not _publish_disabled(page)


def test_a_deposit_that_is_not_a_number_is_a_sentence(monkeypatch):
    client = _client(monkeypatch)

    response = client.post("/editor/publish", data={"deposit": "forty", "reason": "Steel went up"})

    assert response.status_code == 422
    assert "Type the deposit as a whole number, like 30." in _text(response)
    assert client.app.state.policies.draft(TENANT_A).deposit_percent == 30


def test_an_unknown_published_version_is_not_announced(monkeypatch):
    page = _text(_client(monkeypatch).get("/editor?published=made-up-policy-v9.9"))
    assert "Published made-up" not in page
