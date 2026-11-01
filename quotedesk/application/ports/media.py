"""The media ports. The image adapter reads bytes, and the voice adapter writes a transcript."""

from decimal import Decimal
from typing import NamedTuple, Protocol


class ImageHost(Protocol):
    """Where an image's bytes live. The turn never sees them."""

    def get(self, media_id: str) -> tuple[str, bytes] | None: ...


class Transcript(NamedTuple):
    """The words in a voice note, and the engine score when the response included one."""

    text: str
    confidence: Decimal | None = None


class VoiceTranscriber(Protocol):
    """Turns a voice note into text. The turn calls it when an audio event has no transcript."""

    def transcribe(self, media_id: str) -> Transcript: ...
