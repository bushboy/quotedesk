import html
from pathlib import Path

from fastapi.testclient import TestClient

from quotedesk.infrastructure.config import Settings
from quotedesk.infrastructure.main import create_app

_HEADLINES = {
    "waiting": "Preparing your quote",
    "fixed-offer": "Fixed quote",
    "range": "Price range",
    "site-visit": "Site visit needed",
    "hazard": "We can't price this yet",
    "pending-approval": "Waiting for the owner",
    "expired": "This quote has expired",
    "deposit-waiting": "Deposit needed to hold the date",
    "slot-held": "Date held",
    "error": "Something went wrong",
}


def _client(monkeypatch) -> TestClient:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    app = create_app(Settings(database_url="postgresql://quotedesk:quotedesk@127.0.0.1:1/quotedesk", store="memory"))
    return TestClient(app)


def test_quote_card_states_render_fixture_copy(monkeypatch):
    client = _client(monkeypatch)
    for state, headline in _HEADLINES.items():
        response = client.get(f"/dev/quote-card/{state}")
        page = html.unescape(response.text)
        assert response.status_code == 200
        assert headline in page
        assert "AquaSure Gauteng" in page

    waiting = client.get("/dev/quote-card/waiting").text
    assert "QD-1042" not in waiting
    assert "R " not in waiting

    fixed = client.get("/dev/quote-card/fixed-offer").text
    assert "R 4 250.00" in fixed
    assert "Rule WATER-F01" in fixed
    assert "7 November 2026" in fixed
    assert "Size is 5 000 L, as stated." in fixed
    assert "ISSUED · version 1 · 7 November 2026 · none" in fixed

    hazard = client.get("/dev/quote-card/hazard").text
    assert "R " not in hazard
    assert "Rule WATER-E03" in hazard

    error = client.get("/dev/quote-card/error").text
    assert "Refresh the page, or send us another message in the chat." in error
    assert "Traceback" not in error
    assert "Exception" not in error


def test_unknown_quote_card_state_is_not_the_error_card(monkeypatch):
    response = _client(monkeypatch).get("/dev/quote-card/no-such-state")
    assert response.status_code == 404
    assert response.text == "That preview does not exist."
    assert "Something went wrong" not in response.text


def test_quote_card_template_has_no_hardcoded_price():
    templates = Path("quotedesk/adapters/inbound/http/templates")
    for path in templates.glob("*.html"):
        text = path.read_text(encoding="utf-8")
        assert "R 4 250.00" not in text
        assert "WATER-F01" not in text
