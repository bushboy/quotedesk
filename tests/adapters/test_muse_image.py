"""Muse Image. The test transport never calls Meta."""

import base64
import logging

import pytest

from quotedesk.adapters.outbound.models.muse_image import MuseImage
from quotedesk.application.ports.pictures import PictureRequest

_PNG = base64.b64encode(b"\x89PNG").decode("ascii")


class Transport:
    def __init__(self, payload=None, error=None) -> None:
        self.calls: list[tuple[str, dict]] = []
        self._payload = {"data": [{"b64_json": _PNG}]} if payload is None else payload
        self._error = error

    def post(self, url, body):
        self.calls.append((url, body))
        if self._error is not None:
            raise self._error
        return self._payload


def test_an_edit_posts_the_photo_and_a_generation_posts_none():
    transport = Transport()
    drawer = MuseImage("secret-key", "https://api.meta.ai/v1/", transport)
    assert drawer.draw(PictureRequest("against a plain wall", None)) == b"\x89PNG"
    assert drawer.draw(PictureRequest("on this garage", b"photo-bytes")) == b"\x89PNG"
    generated, edited = transport.calls
    assert generated[0] == "https://api.meta.ai/v1/images/generations"
    assert "images" not in generated[1]
    assert edited[0] == "https://api.meta.ai/v1/images/edits"
    assert edited[1]["images"] == [{"image_url": "data:image/jpeg;base64," + base64.b64encode(b"photo-bytes").decode()}]
    for _, body in transport.calls:
        assert body["model"] == "muse-image-1.0"
        assert body["size"] == "1536x1024"
        assert body["output_format"] == "png"
        assert body["reasoning_strength"] == "high"
        assert body["response_format"] == "b64_json"
        tools = body["tool_enablement"]
        assert tools["enable_web_search"] is False
        assert tools["enable_image_search"] is False
        assert "secret-key" not in str(body)


def test_the_picture_model_is_the_one_passed_in():
    transport = Transport()
    drawer = MuseImage("secret-key", "https://api.meta.ai/v1", transport, "other-picture-model")
    drawer.draw(PictureRequest("against a plain wall", None))
    assert transport.calls[0][1]["model"] == "other-picture-model"


def test_a_failed_call_does_not_log_the_prompt_or_the_key():
    transport = Transport(error=RuntimeError("down"))
    drawer = MuseImage("secret-key", "https://api.meta.ai/v1", transport)
    log = logging.getLogger("quotedesk.adapters.outbound.models.muse_image")
    lines: list[str] = []

    class Grab(logging.Handler):
        def emit(self, record) -> None:
            lines.append(record.getMessage())

    handler = Grab()
    log.addHandler(handler)
    try:
        with pytest.raises(RuntimeError):
            drawer.draw(PictureRequest("a secret prompt", b"photo-bytes"))
    finally:
        log.removeHandler(handler)
    text = "\n".join(lines)
    assert "secret-key" not in text
    assert "a secret prompt" not in text
    assert "photo-bytes" not in text
    assert text == "Muse Image call failed RuntimeError"


def test_an_empty_picture_fails_without_the_payload():
    drawer = MuseImage("secret-key", "https://api.meta.ai/v1", Transport(payload={}))
    with pytest.raises(ValueError, match="The picture was empty."):
        drawer.draw(PictureRequest("against a plain wall", None))
