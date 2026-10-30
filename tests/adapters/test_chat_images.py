import time

from fastapi.testclient import TestClient

from quotedesk.infrastructure.config import Settings
from quotedesk.infrastructure.main import create_app

_URL = "postgresql://quotedesk:quotedesk@127.0.0.1:1/quotedesk"
_WA = "15550002222"
_CAPTION = "By the gate"


def _payload(message: dict) -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "contacts": [{"wa_id": _WA}],
                            "messages": [message],
                        }
                    }
                ]
            }
        ],
    }


def test_several_files_are_several_messages(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    app = create_app(Settings(database_url=_URL))
    client = TestClient(app)
    html = client.get("/chat").text
    assert 'id="file" accept="image/*,video/*" multiple' in html
    assert 'id="client"' in html
    assert 'value="15550002222" selected' in html
    for number in ("15550003333", "15550004444", "15550005555", "15550006666"):
        assert f'value="{number}"' in html
    picked = client.get("/chat", params={"wa_id": "15550004444"}).text
    assert 'value="15550004444" selected' in picked
    assert "index === 0 ? caption" in html
    first = client.post("/sim/media", content=b"\xff\xd8\xffone", headers={"content-type": "image/jpeg"}).json()
    second = client.post("/sim/media", content=b"\xff\xd8\xfftwo", headers={"content-type": "image/jpeg"}).json()
    assert client.get(first["url"]).content == b"\xff\xd8\xffone"
    assert client.get(second["url"]).content == b"\xff\xd8\xfftwo"
    now = str(int(time.time()))
    client.post(
        "/whatsapp/webhook",
        json=_payload(
            {
                "from": _WA,
                "id": "wamid.ONE",
                "timestamp": now,
                "type": "image",
                "image": {"id": first["id"], "mime_type": "image/jpeg", "caption": _CAPTION},
            }
        ),
    )
    client.post(
        "/whatsapp/webhook",
        json=_payload(
            {
                "from": _WA,
                "id": "wamid.TWO",
                "timestamp": now,
                "type": "image",
                "image": {"id": second["id"], "mime_type": "image/jpeg"},
            }
        ),
    )
    stored = app.state.conversations.messages(app.state.tenant_id, app.state.conversation_id)
    assert stored[0].kind == "image"
    assert stored[0].body == _CAPTION
    assert stored[0].media_id == first["id"]
    assert stored[1].kind == "image"
    assert stored[1].body is None
    assert stored[1].media_id == second["id"]
