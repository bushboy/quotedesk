import hashlib
import hmac
import json
from pathlib import Path

from fastapi.testclient import TestClient

from quotedesk.infrastructure.config import Settings
from quotedesk.infrastructure.main import create_app

_DOWN = "postgresql://quotedesk:quotedesk@127.0.0.1:1/quotedesk"
_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "whatsapp" / "text_message.json"


def _down(monkeypatch, **settings):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    return create_app(Settings(database_url=_DOWN, **settings))


def test_a_down_store_refuses_the_webhook_and_writes_nothing(monkeypatch):
    app = _down(monkeypatch, whatsapp_app_secret="app-secret")
    client = TestClient(app)
    raw = _FIXTURE.read_bytes()
    unsigned = client.post("/whatsapp/webhook", content=raw, headers={"content-type": "application/json"})
    assert unsigned.status_code == 403
    assert client.post(
        "/whatsapp/webhook",
        content=b"not-json",
        headers={
            "content-type": "application/json",
            "x-hub-signature-256": "sha256=" + hmac.new(b"app-secret", b"not-json", hashlib.sha256).hexdigest(),
        },
    ).status_code == 400
    signature = "sha256=" + hmac.new(b"app-secret", raw, hashlib.sha256).hexdigest()
    refused = client.post(
        "/whatsapp/webhook",
        content=raw,
        headers={"content-type": "application/json", "x-hub-signature-256": signature},
    )
    assert refused.status_code == 503
    assert not hasattr(app.state, "conversations")
    assert client.get("/chat").status_code == 503
    assert client.get("/console").status_code == 503
    home = client.get("/", follow_redirects=False)
    assert home.status_code == 307
    assert home.headers["location"] == "/chat"
    assert client.post("/sim/reset").status_code == 503
    app.state.run_turn()
    assert json.loads(raw)["entry"][0]["changes"][0]["value"]["messages"]
