import hashlib
import hmac
import json
import time
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient

from quotedesk.adapters.inbound.http.whatsapp import inbound_messages
from quotedesk.infrastructure.config import Settings
from quotedesk.infrastructure.demo import CONVERSATION, TENANT_A
from quotedesk.infrastructure.main import create_app

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "whatsapp" / "text_message.json"
URL = "postgresql://quotedesk:quotedesk@127.0.0.1:1/quotedesk"
CONVERSATION_ID = UUID("33333333-3333-4333-8333-333333333333")


def _app(monkeypatch, **settings):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    return create_app(Settings(database_url=URL, **settings))


def _payload(message: dict | None = None) -> dict:
    body = json.loads(FIXTURE.read_text(encoding="utf-8"))
    if message is not None:
        body["entry"][0]["changes"][0]["value"]["messages"] = [message]
    return body


def test_verify_handshake_echoes_the_challenge_only_for_the_configured_token(monkeypatch):
    client = TestClient(_app(monkeypatch, whatsapp_verify_token="s3cret"))
    good = client.get("/whatsapp/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "s3cret", "hub.challenge": "42"})
    bad = client.get("/whatsapp/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "nope", "hub.challenge": "42"})
    assert (good.status_code, good.text) == (200, "42")
    assert bad.status_code == 403

    unconfigured = TestClient(_app(monkeypatch))
    assert unconfigured.get("/whatsapp/webhook", params={"hub.mode": "subscribe", "hub.challenge": "42"}).status_code == 403


def test_signature_is_required_when_an_app_secret_is_set(monkeypatch):
    app = _app(monkeypatch, whatsapp_app_secret="app-secret")
    client = TestClient(app)
    raw = json.dumps(_payload()).encode()
    assert client.post("/whatsapp/webhook", content=raw, headers={"content-type": "application/json"}).status_code == 403
    signature = "sha256=" + hmac.new(b"app-secret", raw, hashlib.sha256).hexdigest()
    signed = client.post(
        "/whatsapp/webhook",
        content=raw,
        headers={"content-type": "application/json", "x-hub-signature-256": signature},
    )
    assert (signed.status_code, signed.text) == (200, "")


def test_status_updates_are_accepted_and_store_nothing(monkeypatch):
    app = _app(monkeypatch)
    body = _payload()
    value = body["entry"][0]["changes"][0]["value"]
    del value["messages"]
    value["statuses"] = [{"id": "wamid.OUT1", "status": "delivered", "timestamp": "1761710000", "recipient_id": "15550002222"}]
    response = TestClient(app).post("/whatsapp/webhook", json=body)
    assert (response.status_code, response.text) == (200, "")
    assert app.state.conversations.get(TENANT_A, CONVERSATION) is None


def test_media_messages_carry_the_caption_and_a_bare_mime_type():
    image = {
        "from": "15550002222",
        "id": "wamid.IMG1",
        "timestamp": "1761710000",
        "type": "image",
        "image": {"id": "media-1", "mime_type": "image/JPEG", "caption": "Old tank on its base"},
    }
    voice = {
        "from": "15550002222",
        "id": "wamid.VOICE1",
        "timestamp": "1761710001",
        "type": "audio",
        "audio": {"id": "media-2", "mime_type": "audio/ogg; codecs=opus", "voice": True},
    }
    body = _payload(image)
    body["entry"][0]["changes"][0]["value"]["messages"].append(voice)
    first, second = inbound_messages(body, CONVERSATION_ID)
    assert (first.kind, first.body, first.mime) == ("image", "Old tank on its base", "image/jpeg")
    assert (second.kind, second.body, second.mime) == ("audio", None, "audio/ogg")


def test_simulated_media_round_trips(monkeypatch):
    client = TestClient(_app(monkeypatch))
    uploaded = client.post("/sim/media", content=b"\x89PNG", headers={"content-type": "image/png"}).json()
    assert uploaded["mime_type"] == "image/png"
    fetched = client.get(uploaded["url"])
    assert (fetched.status_code, fetched.content, fetched.headers["content-type"]) == (200, b"\x89PNG", "image/png")


def test_running_app_replies_after_the_quiet_window(monkeypatch):
    app = _app(monkeypatch)
    message = {
        "from": "15550002222",
        "id": "wamid.LIVE1",
        "timestamp": str(int(time.time())),
        "type": "text",
        "text": {"body": "Please replace the 5000 L tank. It sits on a level base."},
    }
    with TestClient(app) as client:
        assert client.post("/whatsapp/webhook", json=_payload(message)).status_code == 200
        assert client.get("/whatsapp/outbox", params={"wa_id": "15550002222"}).json() == []
        rows = []
        deadline = time.monotonic() + 6
        while not rows and time.monotonic() < deadline:
            time.sleep(0.2)
            rows = client.get("/whatsapp/outbox", params={"wa_id": "15550002222", "after": 0}).json()
    assert len(rows) == 1
    assert "R 4 250" in rows[0]["body"]
    assert "/card/QD-1042?code=1042" in rows[0]["body"]
