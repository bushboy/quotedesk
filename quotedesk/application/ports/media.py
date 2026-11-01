"""The media ports. The image adapter reads bytes, and the voice adapter writes a transcript."""

from typing import Protocol


class ImageHost(Protocol):
    """Where an image's bytes live. The turn never sees them."""

    def get(self, media_id: str) -> tuple[str, bytes] | None: ...


class VoiceTranscriber(Protocol):
    """Turns a voice note into text. The turn calls it when an audio event has no transcript."""

    def transcribe(self, media_id: str) -> str: ...
