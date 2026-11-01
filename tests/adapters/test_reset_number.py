from datetime import datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient

from quotedesk.application.dto.agent import HandoverNote
from quotedesk.infrastructure.config import Settings
from quotedesk.infrastructure.main import create_app

_URL = "postgresql://quotedesk:quotedesk@127.0.0.1:1/quotedesk"
_ONE = "15550002222"
_TWO = "15550003333"


def _payload(wa_id: str, body: str, message_id: str) -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "contacts": [{"wa_id": wa_id, "profile": {"name": wa_id}}],
                            "messages": [
                                {
                                    "from": wa_id,
                                    "id": message_id,
                                    "timestamp": "1710000000",
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


def test_reset_session_clears_only_that_number(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    app = create_app(Settings(database_url=_URL, store="memory"))
    client = TestClient(app)
    tenant = app.state.tenant_id
    client.post("/whatsapp/webhook", json=_payload(_ONE, "hello from one", "wamid.ONE"))
    client.post("/whatsapp/webhook", json=_payload(_TWO, "hello from two", "wamid.TWO"))
    gone = app.state.conversations.find(tenant, _ONE)
    kept = app.state.conversations.find(tenant, _TWO)
    assert gone is not None and kept is not None and gone != kept
    app.state.handovers.append(
        tenant,
        HandoverNote(conversation_id=gone, reason="price", brief="Needs a person.", at=datetime.now(timezone.utc)),
    )
    app.state.handovers.append(
        tenant,
        HandoverNote(conversation_id=kept, reason="price", brief="Leave this one.", at=datetime.now(timezone.utc)),
    )
    app.state.unit.committed[(tenant, gone)] = object()
    app.state.outbox.append("reply for one", _ONE)
    app.state.outbox.append("reply for two", _TWO)

    page = client.get("/chat").text
    assert "Reset session" in page
    assert "/sim/reset-number?wa_id=" in page
    assert client.post("/sim/reset-number", params={"wa_id": "not-a-number"}).status_code == 400
    assert client.post("/sim/reset-number", params={"wa_id": _ONE}).status_code == 204

    assert app.state.conversations.find(tenant, _ONE) is None
    assert app.state.conversations.find(tenant, _TWO) == kept
    assert client.get("/whatsapp/history", params={"wa_id": _ONE}).json() == []
    assert client.get("/whatsapp/history", params={"wa_id": _TWO}).json()
    assert client.get("/whatsapp/outbox", params={"wa_id": _ONE}).json() == []
    assert client.get("/whatsapp/outbox", params={"wa_id": _TWO}).json()
    assert app.state.cases.get(tenant, gone) is None
    assert app.state.cases.get(tenant, kept) is not None
    assert [note.conversation_id for note in app.state.handovers.list(tenant)] == [kept]
    assert (tenant, gone) not in app.state.unit.committed
    assert app.state.conversation_id != gone


def test_a_second_session_for_the_same_number_is_cleared_too(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    app = create_app(Settings(database_url=_URL, store="memory"))
    client = TestClient(app)
    tenant = app.state.tenant_id
    client.post("/whatsapp/webhook", json=_payload(_ONE, "first session", "wamid.FIRST"))
    first = app.state.conversations.find(tenant, _ONE)
    later = uuid4()
    app.state.conversations.bind(tenant, _ONE, later)
    assert client.post("/sim/reset-number", params={"wa_id": _ONE}).status_code == 204
    assert app.state.conversations.find(tenant, _ONE) is None
    assert app.state.conversations.get(tenant, first) is None
    assert app.state.cases.get(tenant, first) is None
