import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

_BASE = datetime(2026, 10, 24, 0, 0, tzinfo=timezone.utc)
_FIXTURE = Path("tests/fixtures/whatsapp/text_message.json")


class RunReport:
    def __init__(self, outbox: tuple, case, responses: tuple[tuple[int, str], ...], trail: tuple) -> None:
        self.outbox = outbox
        self.case = case
        self.responses = responses
        self.trail = trail


def run(app, scenario_path: str) -> RunReport:
    fixture = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    client = TestClient(app)
    responses: list[tuple[int, str]] = []
    events = _load(Path(scenario_path))
    for event in events:
        response = client.post("/whatsapp/webhook", json=_payload(fixture, event))
        responses.append((response.status_code, response.text))
        turn = getattr(app.state, "run_turn", None)
        if turn is not None:
            turn()
    first = client.get("/whatsapp/outbox")
    second = client.get("/whatsapp/outbox")
    if first.json() != second.json():
        raise RuntimeError("An outbox read removed rows.")
    wa_id = events[-1]["from"] if events else ""
    conversation_id = app.state.conversations.find(app.state.tenant_id, wa_id) or app.state.conversation_id
    case = app.state.cases.get(app.state.tenant_id, conversation_id)
    trail = app.state.conversations.trail(app.state.tenant_id, conversation_id)
    return RunReport(outbox=tuple(first.json()), case=case, responses=tuple(responses), trail=trail)


def _load(path: Path) -> tuple[dict[str, str], ...]:
    events: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if line.lstrip().startswith("- "):
            current = {}
            events.append(current)
            line = line.lstrip()[2:]
        if current is None or ":" not in line:
            continue
        key, value = line.strip().split(":", 1)
        current[key.strip()] = value.strip().strip('"')
    return tuple(events)


def _payload(fixture: dict, event: dict[str, str]) -> dict:
    body = json.loads(json.dumps(fixture))
    value = body["entry"][0]["changes"][0]["value"]
    message = value["messages"][0]
    message["id"] = event["id"]
    message["from"] = event["from"]
    message["text"] = {"body": event["text"]}
    message["type"] = "text"
    message["timestamp"] = str(int((_BASE + timedelta(seconds=int(event["at"]))).timestamp()))
    value["contacts"][0]["wa_id"] = event["from"]
    return body
