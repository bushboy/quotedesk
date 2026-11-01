"""MuseVoice reads the transcript and a score when the JSON has one. It does not call a live engine."""

from decimal import Decimal

from quotedesk.adapters.outbound.models.muse_voice import MuseVoice


class Host:
    def get(self, media_id: str) -> tuple[str, bytes] | None:
        if media_id != "media-voice":
            return None
        return "audio/ogg", b"ogg-bytes"


class Transport:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls = 0

    def post(self, url: str, body: dict) -> dict:
        self.calls += 1
        assert url.endswith("/audio/transcriptions")
        assert body["model"] == "muse-voice"
        assert body["mime"] == "audio/ogg"
        assert body["audio"] == b"ogg-bytes"
        return self.payload


def test_a_response_without_a_score_returns_no_score():
    voice = MuseVoice(Host(), Transport({"text": "Replace the 5000 L tank."}), "muse-voice", "https://muse.example")
    heard = voice.transcribe("media-voice")
    assert heard.text == "Replace the 5000 L tank."
    assert heard.confidence is None


def test_a_confidence_field_maps_onto_a_zero_to_one_score():
    voice = MuseVoice(Host(), Transport({"text": "Yes.", "confidence": "91"}), "muse-voice", "https://muse.example")
    heard = voice.transcribe("media-voice")
    assert heard.text == "Yes."
    assert heard.confidence == Decimal("0.91")


def test_an_unmapped_score_is_no_score():
    voice = MuseVoice(Host(), Transport({"text": "Yes.", "confidence": "sure"}), "muse-voice", "https://muse.example")
    assert voice.transcribe("media-voice").confidence is None
