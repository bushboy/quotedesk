"""The picture port. A renderer returns image bytes. The turn never sees the model URL."""

from typing import NamedTuple, Protocol


class PictureRequest(NamedTuple):
    """What to draw. A photo means edit that photo. No photo means generate the scene."""

    prompt: str
    photo: bytes | None = None


class PictureDrawer(Protocol):
    """Draws one picture. A failure raises. The bytes are not logged."""

    def draw(self, request: PictureRequest) -> bytes: ...
