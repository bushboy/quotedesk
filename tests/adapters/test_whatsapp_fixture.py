import json
from pathlib import Path

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "whatsapp" / "text_message.json"


def test_text_fixture_has_one_customer_message():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    messages = [
        message
        for entry in payload["entry"]
        for change in entry["changes"]
        for message in change["value"]["messages"]
    ]
    assert len(messages) == 1
    message = messages[0]
    assert message["type"] == "text"
    body = message["text"]["body"]
    assert body == "The tank in the yard is leaking."
