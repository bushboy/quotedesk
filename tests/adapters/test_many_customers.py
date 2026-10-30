"""Two customers do not share a quote, a card, or a price."""

import re
import time
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from quotedesk.application.dto.agent import ModelReply, ToolCall
from quotedesk.infrastructure.config import Settings
from quotedesk.infrastructure.db import engine
from quotedesk.infrastructure.main import create_app

URL = "postgresql://quotedesk:quotedesk@127.0.0.1:1/quotedesk"
LIVE = "postgresql+psycopg://quotedesk:quotedesk@127.0.0.1:5432/quotedesk"
_CARD = re.compile(r"/card/(QD-\d+)\?code=(\d+)")


class Caller:
    def complete(self, prompt):
        if prompt.tool_payloads:
            lines = []
            for item in prompt.tool_payloads:
                low = item.body.get("range_min")
                if item.name == "get_quote" and isinstance(low, dict) and low.get("amount"):
                    lines.append(f"The indicative range is R {low['amount']}.")
                if item.body.get("outcome") == "escalation":
                    lines.append(item.body.get("customer_template") or "")
                if item.body.get("url"):
                    lines.append(item.body["url"])
                if item.body.get("sentence"):
                    lines.append(item.body["sentence"])
            return ModelReply(text=" ".join(line for line in lines if line) or "Done.")
        latest = prompt.messages[-1]
        fact = {"source": "customer_text", "event_id": latest.provider_message_id}
        text = latest.body.casefold()
        if "deposit" in text:
            quote_id = _quoted(prompt)
            return ModelReply(
                text="",
                tool_calls=(
                    ToolCall(name="accept_quote", arguments={"quote_id": quote_id}),
                    ToolCall(
                        name="create_deposit_link",
                        arguments={"quote_id": quote_id, "idempotency_key": f"{quote_id}-pay"},
                    ),
                ),
            )
        if "monday" in text:
            return ModelReply(
                text="",
                tool_calls=(ToolCall(name="check_availability", arguments={"job_type": "borehole"}),),
            )
        if "pump" in text:
            return _record(fact, "pump", ())
        if "carport" in text:
            size = "6 x 9" if "6" in text else "3 x 5"
            return _record(
                fact,
                "carport",
                (
                    {"key": "item", "value": "Economy sheeting", **fact},
                    {"key": "size", "value": size, **fact},
                    {"key": "job_type", "value": "carport", **fact},
                    {"key": "required_fields", "value": "true", **fact},
                    {"key": "agreement", "value": "true", **fact},
                    {"key": "measurement", "value": "true", **fact},
                    {"key": "media_usable", "value": "true", **fact},
                    {"key": "rate_card", "value": "true", **fact},
                ),
            )
        litres = "10000" if "10000" in text else "5000"
        return _record(
            fact,
            "tank",
            (
                {"key": "size_litres", "value": litres, **fact},
                {"key": "job", "value": "replacement", **fact},
                {"key": "job_type", "value": "replacement", **fact},
            ),
        )


def _record(fact, job_id, facts):
    return ModelReply(
        text="",
        tool_calls=(
            ToolCall(
                name="update_case",
                arguments={"conversation_id": fact["event_id"], "job_id": job_id, "job_type": job_id, "facts": list(facts)},
            ),
            ToolCall(name="get_quote", arguments={"conversation_id": fact["event_id"]}),
        ),
    )


def _quoted(prompt) -> str:
    for message in reversed(prompt.messages):
        found = _CARD.search(message.body or "")
        if found:
            return found.group(1)
    raise AssertionError("The deposit turn had no quote.")


def _app(monkeypatch, tenant="aquasure"):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    app = create_app(Settings(database_url=URL, tenant=tenant, model="script", store="memory"))
    app.state.slot.model = Caller()
    return app


def _post(client, wa_id, body):
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "contacts": [{"wa_id": wa_id}],
                            "messages": [
                                {
                                    "from": wa_id,
                                    "id": f"wamid.{wa_id}.{int(time.time() * 1000)}",
                                    "timestamp": str(int(time.time())),
                                    "type": "text",
                                    "text": {"body": body},
                                }
                            ],
                        }
                    }
                ]
            }
        ],
    }
    assert client.post("/whatsapp/webhook", json=payload).status_code == 200


def _wait(client, wa_id, needle):
    deadline = time.monotonic() + 8
    rows = []
    while time.monotonic() < deadline:
        rows = client.get("/whatsapp/outbox", params={"wa_id": wa_id, "after": 0}).json()
        if rows and any(needle in row["body"] for row in rows):
            return rows
        time.sleep(0.2)
    return rows


def _card(client, body):
    found = _CARD.search(body)
    assert found is not None
    page = client.get(f"/card/{found.group(1)}", params={"code": found.group(2)})
    assert page.status_code == 200
    return found.group(1), found.group(2), page.text


def test_two_customers_get_their_own_quotes(monkeypatch):
    app = _app(monkeypatch)
    with TestClient(app) as client:
        _post(client, "15551110001", "Please quote a 5000 L replacement.")
        _post(client, "15551110002", "Please quote a 10000 L replacement.")
        _post(client, "15551110003", "The pump needs repair. It is not a tank.")
        _post(client, "15551110004", "Can I book the inspection for Monday? It is a borehole.")
        small = _wait(client, "15551110001", "4250.00")
        large = _wait(client, "15551110002", "7900.00")
        handed = _wait(client, "15551110003", "contact you")
        booked = _wait(client, "15551110004", "working days")
        assert small and large and handed and booked
        small_id, small_code, small_page = _card(client, small[-1]["body"])
        large_id, large_code, large_page = _card(client, large[-1]["body"])
        assert small_id != large_id
        assert "R 4 250.00" in small_page
        assert "R 7 900.00" in large_page
        assert "Deposit R 1 275.00" in small_page
        assert "R 4 250.00" not in large_page
        assert client.get(f"/card/{large_id}", params={"code": small_code}).status_code == 404
        assert client.get(f"/card/{small_id}", params={"code": large_code}).status_code == 404
        quote = app.state.quotes.get_by_id(app.state.tenant_id, _quote_id(small_id))
        assert quote.current.expiry > date.today()
        assert "no template" not in booked[-1]["body"].casefold()
        assert "borehole" in booked[-1]["body"].casefold()
        console = client.get("/console").text
        assert "The quote needs a person." in console
        _post(client, "15551110001", "Yes please go ahead, how do I pay the deposit?")
        paid = _wait(client, "15551110001", "sandbox.payfast.example/deposit/")
        assert paid
        assert small_id in paid[-1]["body"]

    frameworks = _app(monkeypatch, "frameworks")
    with TestClient(frameworks) as client:
        _post(client, "15552220001", "Economy sheeting carport 3 x 5")
        _post(client, "15552220002", "Economy sheeting carport 6 x 9")
        narrow = _wait(client, "15552220001", "2700.00")
        wide = _wait(client, "15552220002", "9720.00")
        assert narrow and wide
        _, _, narrow_page = _card(client, narrow[-1]["body"])
        _, _, wide_page = _card(client, wide[-1]["body"])
        assert "R 2 700.00" in narrow_page
        assert "R 9 720.00" in wide_page


def test_a_restart_still_opens_the_card(monkeypatch):
    try:
        with engine(LIVE).connect():
            pass
    except OperationalError:
        pytest.skip("PostgreSQL is not listening on 127.0.0.1:5432.")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    app = create_app(Settings(database_url=LIVE, model="script"))
    app.state.slot.model = Caller()
    wa_id = "15553330001"
    quote_id = None
    try:
        with TestClient(app) as client:
            _post(client, wa_id, "Please quote a 5000 L replacement.")
            rows = _wait(client, wa_id, "/card/QD-")
            assert rows
            quote_id, code, page = _card(client, rows[-1]["body"])
            assert "Deposit R " in page
            amount = _shown_amount(page)
        restarted = create_app(Settings(database_url=LIVE, model="script"))
        with TestClient(restarted) as client:
            again = client.get(f"/card/{quote_id}", params={"code": code})
            assert again.status_code == 200
            assert amount in again.text
            assert "Deposit R " in again.text
            assert client.get(f"/card/{quote_id}", params={"code": "0000"}).status_code == 404
    finally:
        _forget_customer(wa_id, quote_id)


def _shown_amount(page: str) -> str:
    found = re.search(r"R [\d ]+\.\d{2}", page)
    assert found is not None
    return found.group(0)


def _forget_customer(wa_id: str, quote_id: str | None) -> None:
    from uuid import UUID

    from quotedesk.adapters.outbound.persistence.records import bind_tenant

    tenant = UUID("11111111-1111-4111-8111-111111111111")
    with engine(LIVE).begin() as connection:
        bind_tenant(connection, tenant)
        if quote_id is not None:
            connection.execute(text("DELETE FROM quote WHERE quote_id = :quote_id"), {"quote_id": quote_id})
            connection.execute(
                text("DELETE FROM verification_code WHERE quote_id = :quote_id"),
                {"quote_id": quote_id},
            )
        connection.execute(text("DELETE FROM sender_bind WHERE wa_id = :wa_id"), {"wa_id": wa_id})


def _quote_id(value):
    from quotedesk.domain.shared.ids import QuoteId

    return QuoteId(value)
