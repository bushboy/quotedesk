"""Muse Voice Transcribe.

The receive path calls this when an audio event has no transcript.
The adapter fetches the bytes from the media host and returns the text.
A missing file or an empty reply raises, and the receive path asks the customer to type.
A response with no confidence field returns no score. The bytes, the text, and the score are not logged.
"""

from decimal import Decimal

from quotedesk.application.ports.media import ImageHost, Transcript


class MuseVoice:
    """A voice-note transcript from Muse. The bytes are not logged."""

    def __init__(self, host: ImageHost, transport, model_id: str, base_url: str) -> None:
        self._host = host
        self._transport = transport
        self._model_id = model_id
        self._url = base_url.rstrip("/") + "/audio/transcriptions"

    def transcribe(self, media_id: str) -> Transcript:
        found = self._host.get(media_id)
        if found is None:
            raise ValueError("That voice note is not stored.")
        mime, data = found
        payload = self._transport.post(self._url, {"model": self._model_id, "mime": mime, "audio": data})
        text = payload.get("text") if isinstance(payload, dict) else None
        if not isinstance(text, str) or text.strip() == "":
            raise ValueError("The transcript was empty.")
        return Transcript(text.strip(), _confidence(payload))


def _confidence(payload: object) -> Decimal | None:
    """The score on the transcription JSON, mapped onto 0 to 1. A missing or unmapped score is none."""
    if not isinstance(payload, dict):
        return None
    raw = payload.get("confidence")
    if raw is None or isinstance(raw, bool):
        return None
    try:
        score = Decimal(str(raw))
    except Exception:
        return None
    if score < 0:
        return None
    if score <= 1:
        return score
    if score <= 100:
        return score / Decimal("100")
    return None
