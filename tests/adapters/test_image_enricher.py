import base64
import json
import socket
import time
from decimal import Decimal
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


def _sam_response(score: str, *, extra: str = "") -> dict:
    line = (
        f"<0f>0<|box;x1=10;y1=12;x2=40;y2=50;w=80;h=60;c={score}|>"
        f"<|mask;x=0;y=0;c={score};data=4,4,!abcd|>{extra}"
    )
    return {"output": [{"type": "message", "content": [{"type": "output_text", "text": line}]}]}


def test_spark_extraction_reads_the_bytes_once(monkeypatch):
    _refuse_socket(monkeypatch)
    recorded = json.loads((_ROOT / "fixtures" / "extraction" / "tank-on-base.json").read_text(encoding="utf-8"))
    recorded = {**recorded, "unit_price": "4250.00", "size_litres": "5000", "outcome": "fixed_offer"}
    blob = b"\xff\xd8\xff\xd9"
    host = _Host({"media-1": ("image/jpeg", blob)})
    transport = _Transport([recorded, _sam_response("0.91")])
    enricher = ImageEnricher(
        host=host,
        transport=transport,
        model_id="muse-spark-1.3",
        base_url="https://api.meta.ai/v1",
        sam_model_id="sam-3.1",
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
    url, segment = transport.calls[1]
    assert url == "https://api.meta.ai/v1/responses"
    assert segment["model"] == "sam-3.1"
    assert "instructions" not in segment
    assert segment["metadata"] == {"include_confidence": "true", "mask_encoding": "one_bit"}
    prompt = segment["input"][0]["content"][0]
    assert prompt == {"type": "input_text", "text": "tank"}
    assert base64.b64encode(blob).decode("ascii") in json.dumps(segment)
    assert result is not None and again == result
    assert result.summary == "A tank on a level base."
    assert result.objects == ("tank",)
    assert result.notes == ()
    assert result.sam_error is False
    assert result.masks[0].label == "tank"
    assert result.masks[0].score == Decimal("0.91")
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


def test_each_object_is_one_sam_call(monkeypatch):
    _refuse_socket(monkeypatch)
    recorded = {
        "summary": "A tank on a base.",
        "objects": ["tank", "base", "tank"],
        "blur": False,
        "darkness": False,
        "wrong_subject": False,
    }
    host = _Host({"media-1": ("image/jpeg", b"\xff\xd8\xff\xd9")})
    transport = _Transport([recorded, _sam_response("0.91"), _sam_response("0.40")])
    enricher = ImageEnricher(
        host=host,
        transport=transport,
        model_id="muse-spark-1.3",
        base_url="https://api.meta.ai/v1",
    )
    enricher.note("wamid.IMG", "media-1", _CAPTION)
    result = enricher.for_image("wamid.IMG")
    prompts = [body["input"][0]["content"][0]["text"] for _, body in transport.calls[1:]]
    assert prompts == ["tank", "base"]
    assert result is not None
    assert [(mask.label, mask.score) for mask in result.masks] == [
        ("tank", Decimal("0.91")),
        ("base", Decimal("0.40")),
    ]


def test_no_sam_match_keeps_the_summary(monkeypatch):
    _refuse_socket(monkeypatch)
    recorded = json.loads((_ROOT / "fixtures" / "extraction" / "tank-on-base.json").read_text(encoding="utf-8"))
    empty = {"output": [{"type": "message", "content": [{"type": "output_text", "text": ""}]}]}
    host = _Host({"media-1": ("image/jpeg", b"\xff\xd8\xff\xd9")})
    transport = _Transport([recorded, empty])
    enricher = ImageEnricher(
        host=host,
        transport=transport,
        model_id="muse-spark-1.3",
        base_url="https://api.meta.ai/v1",
    )
    enricher.note("wamid.IMG", "media-1", _CAPTION)
    result = enricher.for_image("wamid.IMG")
    assert result is not None
    assert result.sam_error is False
    assert result.masks == ()
    assert result.summary == "A tank on a level base."


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
    assert result.sam_sentence == "The segmenter did not return a result."
    assert result.masks == ()
    assert result.summary == "A tank on a level base."


def _empty_sam() -> dict:
    return {"output": [{"type": "message", "content": [{"type": "output_text", "text": ""}]}]}


def _carport_enricher(transport: _Transport) -> ImageEnricher:
    return ImageEnricher(
        host=_Host({"media-1": ("image/jpeg", b"\xff\xd8\xff\xd9")}),
        transport=transport,
        model_id="muse-spark-1.3",
        base_url="https://api.meta.ai/v1",
        sam_model_id="sam-3.1",
        subject="carport",
    )


def _prompts(transport: _Transport) -> list[str]:
    return [body["input"][0]["content"][0]["text"] for _, body in transport.calls[1:]]


def test_a_carport_photo_stops_before_the_garage(monkeypatch):
    _refuse_socket(monkeypatch)
    recorded = {"summary": "An existing carport.", "notes": ["About 6 m long."], "objects": ["tree"]}
    transport = _Transport([recorded, _sam_response("0.88"), _empty_sam(), _sam_response("0.70")])
    enricher = _carport_enricher(transport)
    enricher.note("wamid.IMG", "media-1", "This is the one we want to resheet.")
    result = enricher.for_image("wamid.IMG")
    assert _prompts(transport) == ["carport", "single carport", "double carport"]
    assert "carports and replaces sheeting" in transport.calls[0][1]["instructions"]
    assert result is not None
    assert result.objects == ("carport", "double carport")
    assert result.objects[0] == "carport"
    assert "tree" not in result.objects
    assert "A carport is in the photo." in result.notes[0]
    assert "The carport is a double bay." in " ".join(result.notes)
    assert "About 6 m long." in result.notes
    assert result.masks[0].label == "carport"


def test_a_garage_uses_the_customer_message_and_the_bays(monkeypatch):
    _refuse_socket(monkeypatch)
    recorded = {"summary": "A house with a garage.", "objects": ["sky"]}
    transport = _Transport(
        [recorded, _empty_sam(), _sam_response("0.80"), _empty_sam(), _empty_sam(), _sam_response("0.77")]
    )
    enricher = _carport_enricher(transport)
    enricher.note("wamid.IMG", "media-1", "The carport goes in front of this garage.")
    result = enricher.for_image("wamid.IMG")
    assert _prompts(transport) == ["carport", "garage", "house", "single garage", "double garage"]
    assert result is not None
    assert result.objects == ("garage", "double garage")
    text = " ".join(result.notes)
    assert "A garage is in the photo." in text
    assert "The customer said: The carport goes in front of this garage." in text
    assert "where the carport will go" in text
    assert "Those two bays are the width to confirm." in text
    assert "sky" not in result.objects


def test_a_house_wall_is_the_span_when_there_is_no_carport(monkeypatch):
    _refuse_socket(monkeypatch)
    recorded = {"summary": "The side of a house.", "objects": []}
    transport = _Transport([recorded, _empty_sam(), _empty_sam(), _sam_response("0.66"), _sam_response("0.64")])
    enricher = _carport_enricher(transport)
    enricher.note("wamid.IMG", "media-1", "")
    result = enricher.for_image("wamid.IMG")
    assert _prompts(transport) == ["carport", "garage", "house", "house wall"]
    assert result is not None
    assert result.objects == ("house", "house wall")
    assert "The wall is the span to confirm." in " ".join(result.notes)
    assert "The customer said:" not in " ".join(result.notes)


def test_sheeting_is_the_last_object(monkeypatch):
    _refuse_socket(monkeypatch)
    recorded = {"summary": "A stack of roof sheets.", "objects": ["sheets"]}
    transport = _Transport([recorded, _empty_sam(), _empty_sam(), _empty_sam(), _sam_response("0.73")])
    enricher = _carport_enricher(transport)
    enricher.note("wamid.IMG", "media-1", "Which of these should we use?")
    result = enricher.for_image("wamid.IMG")
    assert _prompts(transport) == ["carport", "garage", "house", "sheeting"]
    assert result is not None
    assert result.objects == ("sheeting",)
    assert "closest sheet" in " ".join(result.notes)


def _tank_enricher(transport: _Transport) -> ImageEnricher:
    return ImageEnricher(
        host=_Host({"media-1": ("image/jpeg", b"\xff\xd8\xff\xd9")}),
        transport=transport,
        model_id="muse-spark-1.3",
        base_url="https://api.meta.ai/v1",
        sam_model_id="sam-3.1",
        subject="tank",
    )


def test_a_tank_photo_stops_before_the_house(monkeypatch):
    _refuse_socket(monkeypatch)
    recorded = {"summary": "A green tank.", "notes": ["Looks like 5000 L."], "objects": ["tree"]}
    transport = _Transport([recorded, _sam_response("0.90"), _empty_sam(), _empty_sam()])
    enricher = _tank_enricher(transport)
    enricher.note("wamid.IMG", "media-1", "Replace this one.")
    result = enricher.for_image("wamid.IMG")
    assert _prompts(transport) == ["tank", "tank stand", "tank leak"]
    assert "installs and replaces water tanks" in transport.calls[0][1]["instructions"]
    assert result is not None
    assert result.objects == ("tank",)
    assert "tree" not in result.objects
    assert "It may be a replacement." in result.notes[0]
    assert "That tank is the size to confirm." in result.notes[0]
    assert "Looks like 5000 L." in result.notes
    assert result.masks[0].label == "tank"


def test_a_stand_is_the_space_the_next_tank_has_to_fit(monkeypatch):
    _refuse_socket(monkeypatch)
    recorded = {"summary": "An empty steel stand.", "objects": ["sky"]}
    transport = _Transport([recorded, _empty_sam(), _sam_response("0.81"), _empty_sam()])
    enricher = _tank_enricher(transport)
    enricher.note("wamid.IMG", "media-1", "")
    result = enricher.for_image("wamid.IMG")
    assert _prompts(transport) == ["tank", "tank stand", "tank leak"]
    assert result is not None
    assert result.objects == ("tank stand",)
    text = " ".join(result.notes)
    assert "The stand is already there" in text
    assert "the space the next tank has to fit" in text
    assert "downpipe" not in result.objects


def test_a_leak_on_a_tank_is_an_existing_tank(monkeypatch):
    _refuse_socket(monkeypatch)
    recorded = {"summary": "Water running down a tank.", "objects": []}
    transport = _Transport([recorded, _empty_sam(), _empty_sam(), _sam_response("0.74")])
    enricher = _tank_enricher(transport)
    enricher.note("wamid.IMG", "media-1", "It is leaking.")
    result = enricher.for_image("wamid.IMG")
    assert _prompts(transport) == ["tank", "tank stand", "tank leak"]
    assert result is not None
    assert result.objects == ("tank leak",)
    assert "A leak is on a tank" in " ".join(result.notes)
    assert "may be a replacement" in " ".join(result.notes)


def test_a_downpipe_uses_the_message_and_the_space(monkeypatch):
    _refuse_socket(monkeypatch)
    recorded = {"summary": "The corner of a house.", "objects": ["gutter"]}
    transport = _Transport(
        [
            recorded,
            _empty_sam(),
            _empty_sam(),
            _empty_sam(),
            _empty_sam(),
            _sam_response("0.70"),
            _sam_response("0.63"),
        ]
    )
    enricher = _tank_enricher(transport)
    enricher.note("wamid.IMG", "media-1", "The tank goes under this downpipe.")
    result = enricher.for_image("wamid.IMG")
    assert _prompts(transport) == ["tank", "tank stand", "tank leak", "house", "downpipe", "tank space"]
    assert result is not None
    assert result.objects == ("downpipe", "tank space")
    text = " ".join(result.notes)
    assert "A downpipe is in the photo." in text
    assert "water can be collected" in text
    assert "The customer said: The tank goes under this downpipe." in text
    assert "where the tank will go" in text
    assert "the size and the suitability to confirm" in text
    assert "gutter" not in result.objects


def test_a_house_and_a_downpipe_share_one_space_probe(monkeypatch):
    _refuse_socket(monkeypatch)
    recorded = {"summary": "A house wall and a downpipe.", "objects": []}
    transport = _Transport(
        [
            recorded,
            _empty_sam(),
            _empty_sam(),
            _empty_sam(),
            _sam_response("0.68"),
            _sam_response("0.67"),
            _empty_sam(),
        ]
    )
    enricher = _tank_enricher(transport)
    enricher.note("wamid.IMG", "media-1", "")
    result = enricher.for_image("wamid.IMG")
    assert _prompts(transport) == ["tank", "tank stand", "tank leak", "house", "downpipe", "tank space"]
    assert result is not None
    assert result.objects == ("house", "downpipe")
    assert "The customer said:" not in " ".join(result.notes)
    assert "A house and a downpipe is in the photo." in " ".join(result.notes)


def test_a_photo_with_none_of_the_tank_objects_says_so(monkeypatch):
    _refuse_socket(monkeypatch)
    recorded = {"summary": "A garden path.", "objects": ["path"]}
    transport = _Transport([recorded, _empty_sam(), _empty_sam(), _empty_sam(), _empty_sam(), _empty_sam()])
    enricher = _tank_enricher(transport)
    enricher.note("wamid.IMG", "media-1", "What do you think?")
    result = enricher.for_image("wamid.IMG")
    assert _prompts(transport) == ["tank", "tank stand", "tank leak", "house", "downpipe"]
    assert result is not None
    assert result.objects == ()
    assert "does not show a tank" in " ".join(result.notes)
    assert result.summary == "A garden path."


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
        "SAM_MODEL_ID",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MODEL", "spark")
    monkeypatch.setenv("META_API_KEY", "test-key")
    monkeypatch.setenv("SPARK_MODEL_ID", "muse-spark-1.3")
    app = create_app(get_settings())
    assert isinstance(app.state.slot.model, SparkTurn)
    enricher = app.state.turn.enricher
    assert isinstance(enricher, ImageEnricher)
    assert enricher._sam_model_id == "sam-3.1"
    assert enricher._subject == "tank"
    monkeypatch.setenv("TENANT", "frameworks")
    framed = create_app(get_settings())
    assert framed.state.turn.enricher._subject == "carport"
    assert enricher._sam_url == "https://api.meta.ai/v1/responses"
    assert enricher._model_id == "muse-spark-1.3"
