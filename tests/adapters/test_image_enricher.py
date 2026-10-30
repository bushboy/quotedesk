import base64
import json
import socket
import time
from pathlib import Path

from fastapi.testclient import TestClient

from quotedesk.adapters.outbound.models.image_context import ImageEnricher
from quotedesk.adapters.outbound.models.spark import SparkTurn
from quotedesk.infrastructure.config import Settings, get_settings
from quotedesk.infrastructure.main import create_app

_ROOT = Path(__file__).resolve().parents[1]
_URL = "postgresql://quotedesk:quotedesk@127.0.0.1:1/quotedesk"
_FILE = "That file is too large or of a type I can't read. Please send a shorter one, or type the details."
_CAPTION = "By the gate"
_WA = "15550002222"


def _refuse_socket(monkeypatch) -> None:
    def refuse(*_args, **_kwargs):
        raise AssertionError("This test must not open a socket.")

    monkeypatch.setattr(socket, "socket", refuse)


def _app(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    return create_app(Settings(database_url=_URL, store="memory"))


def _payload(message: dict) -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "WABA-1",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "contacts": [{"wa_id": _WA}],
                            "messages": [message],
                        },
                    }
                ],
            }
        ],
    }


def _image(message_id: str, media_id: str, caption: str | None, mime: str, blob_is_now: str) -> dict:
    image: dict = {"id": media_id, "mime_type": mime}
    if caption is not None:
        image["caption"] = caption
    return {
        "from": _WA,
        "id": message_id,
        "timestamp": blob_is_now,
        "type": "image",
        "image": image,
    }


class _Host:
    def __init__(self, blobs: dict[str, tuple[str, bytes]]) -> None:
        self.blobs = blobs
        self.reads: list[str] = []

    def get(self, media_id: str) -> tuple[str, bytes] | None:
        self.reads.append(media_id)
        return self.blobs.get(media_id)


class _Transport:
    def __init__(self, responses: list[dict]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, dict]] = []

    def post(self, url: str, body: dict) -> dict:
        self.calls.append((url, body))
        return self._responses.pop(0)


def test_webhook_keeps_the_media_id_and_the_size(monkeypatch):
    app = _app(monkeypatch)
    client = TestClient(app)
    blob = b"\xff\xd8" + b"\x00" * 180 + b"\xff\xd9"
    hosted = client.post("/sim/media", content=blob, headers={"content-type": "image/jpeg"}).json()
    now = str(int(time.time()))
    image = client.post(
        "/whatsapp/webhook",
        json=_payload(_image("wamid.IMG", hosted["id"], _CAPTION, "image/jpeg", now)),
    )
    text = client.post(
        "/whatsapp/webhook",
        json=_payload(
            {
                "from": _WA,
                "id": "wamid.TEXT",
                "timestamp": now,
                "type": "text",
                "text": {"body": "How much?"},
            }
        ),
    )
    assert image.status_code == text.status_code == 200
    stored = app.state.conversations.messages(app.state.tenant_id, app.state.conversation_id)
    photo, words = stored
    assert photo.media_id == hosted["id"]
    assert photo.body == _CAPTION
    assert photo.size_bytes == len(blob)
    assert words.media_id is None
    assert words.body == "How much?"


def test_a_real_jpeg_is_accepted_and_webp_is_refused(monkeypatch):
    app = _app(monkeypatch)
    assert app.state.limits.max_bytes == 5 * 1024 * 1024
    client = TestClient(app)
    jpeg = b"\xff\xd8" + b"\x00" * 180 + b"\xff\xd9"
    hosted = client.post("/sim/media", content=jpeg, headers={"content-type": "image/jpeg"}).json()
    now = str(int(time.time()))
    assert (
        client.post(
            "/whatsapp/webhook",
            json=_payload(_image("wamid.JPEG", hosted["id"], _CAPTION, "image/jpeg", now)),
        ).status_code
        == 200
    )
    empty_id = app.state.sim_media.put("image/jpeg", b"")
    webp = client.post("/sim/media", content=b"RIFF", headers={"content-type": "image/webp"}).json()
    client.post("/whatsapp/webhook", json=_payload(_image("wamid.EMPTY", empty_id, None, "image/jpeg", now)))
    client.post(
        "/whatsapp/webhook",
        json=_payload(_image("wamid.WEBP", webp["id"], None, "image/webp", now)),
    )
    stored = app.state.conversations.messages(app.state.tenant_id, app.state.conversation_id)
    assert [message.provider_message_id for message in stored] == ["wamid.JPEG"]
    assert stored[0].size_bytes == len(jpeg)
    rows = client.get("/whatsapp/outbox", params={"wa_id": _WA}).json()
    assert [row["body"] for row in rows].count(_FILE) == 2


def test_spark_extraction_reads_the_bytes_once(monkeypatch):
    _refuse_socket(monkeypatch)
    recorded = json.loads((_ROOT / "fixtures" / "extraction" / "tank-on-base.json").read_text(encoding="utf-8"))
    recorded = {**recorded, "unit_price": "4250.00", "size_litres": "5000", "outcome": "fixed_offer"}
    masks = json.loads((_ROOT / "fixtures" / "sam" / "tank_success.json").read_text(encoding="utf-8"))
    blob = b"\xff\xd8\xff\xd9"
    host = _Host({"media-1": ("image/jpeg", blob)})
    transport = _Transport([recorded, masks])
    enricher = ImageEnricher(
        host=host,
        transport=transport,
        model_id="muse-spark-1.3",
        base_url="https://api.meta.ai/v1",
    )
    enricher.note("wamid.IMG", "media-1", _CAPTION)
    result = enricher.for_image("wamid.IMG")
    again = enricher.for_image("wamid.IMG")
    extracts = [body for _, body in transport.calls if _CAPTION in json.dumps(body)]
    assert len(extracts) == 1
    assert len(transport.calls) == 2
    dumped = json.dumps(extracts[0])
    assert _CAPTION in dumped
    assert "South Africa" in extracts[0]["instructions"]
    assert "metres" in extracts[0]["instructions"]
    assert "unit_price" not in dumped
    assert base64.b64encode(blob).decode("ascii") in dumped
    segment = transport.calls[1][1]
    assert "image segmentation" in segment["instructions"]
    assert "South Africa" in segment["instructions"]
    assert base64.b64encode(blob).decode("ascii") in json.dumps(segment)
    assert result is not None and again == result
    assert result.summary == "A tank on a level base."
    assert result.objects == ("tank",)
    assert result.notes == ("A tank on a level base.",)
    assert host.reads == ["media-1"]
    assert len(transport.calls) == 2


def test_a_description_in_the_envelope_is_kept(monkeypatch):
    _refuse_socket(monkeypatch)
    prose = "A one-car carport with translucent sheeting, about 3 m by 6 m."
    envelope = {
        "error": None,
        "output": [{"type": "message", "content": [{"type": "output_text", "text": prose}]}],
    }
    host = _Host({"media-1": ("image/jpeg", b"\xff\xd8\xff\xd9")})
    transport = _Transport([envelope])
    enricher = ImageEnricher(
        host=host,
        transport=transport,
        model_id="muse-spark-1.3",
        base_url="https://api.meta.ai/v1",
    )
    enricher.note("wamid.IMG", "media-1", _CAPTION)
    result = enricher.for_image("wamid.IMG")
    assert result is not None
    assert result.summary == prose
    assert result.objects == ()
    assert len(transport.calls) == 1


def test_sam_failure_keeps_the_summary(monkeypatch):
    _refuse_socket(monkeypatch)
    recorded = json.loads((_ROOT / "fixtures" / "extraction" / "tank-on-base.json").read_text(encoding="utf-8"))
    failure = json.loads((_ROOT / "fixtures" / "sam" / "error.json").read_text(encoding="utf-8"))
    host = _Host({"media-1": ("image/jpeg", b"\xff\xd8\xff\xd9")})
    transport = _Transport([recorded, failure])
    enricher = ImageEnricher(
        host=host,
        transport=transport,
        model_id="muse-spark-1.3",
        base_url="https://api.meta.ai/v1",
    )
    enricher.note("wamid.IMG", "media-1", _CAPTION)
    result = enricher.for_image("wamid.IMG")
    assert result is not None
    assert result.sam_error is True
    assert result.masks == ()
    assert result.summary == "A tank on a level base."


def test_install_uses_spark_for_images(monkeypatch):
    _refuse_socket(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", _URL)
    monkeypatch.setenv("STORE", "memory")
    for name in (
        "MODEL",
        "META_API_KEY",
        "META_BASE_URL",
        "SPARK_MODEL_ID",
        "AGENT_PROVIDER",
        "IMAGE_PROVIDER",
        "BASETEN_API_KEY",
        "BASETEN_BASE_URL",
        "BASETEN_MODEL_ID",
        "BASETEN_IMAGE_MODEL_ID",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MODEL", "spark")
    monkeypatch.setenv("META_API_KEY", "test-key")
    monkeypatch.setenv("SPARK_MODEL_ID", "muse-spark-1.3")
    app = create_app(get_settings())
    assert isinstance(app.state.slot.model, SparkTurn)
    assert isinstance(app.state.turn.enricher, ImageEnricher)
