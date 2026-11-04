"""Muse Image. An edit keeps the customer's photo. A generation draws the scene.

The bytes, the prompt, and the key are not logged.
"""

import base64
import logging
from typing import Any

_log = logging.getLogger(__name__)

_MODEL = "muse-image-1.0"


class MuseImage:
    """Draws one carport picture. Tests pass a transport and do not call Meta."""

    def __init__(self, api_key: str, base_url: str, transport=None, model_id: str = _MODEL) -> None:
        self._transport = transport if transport is not None else MetaTransport(api_key)
        self._base = base_url.rstrip("/")
        self._model_id = model_id

    def draw(self, request) -> bytes:
        photo = request.photo
        url = self._base + ("/images/edits" if photo is not None else "/images/generations")
        body = {
            "model": self._model_id,
            "prompt": request.prompt,
            "n": 1,
            "size": "1536x1024",
            "output_format": "png",
            "reasoning_strength": "high",
            "response_format": "b64_json",
            "tool_enablement": {
                "enable_web_search": False,
                "enable_image_search": False,
                "enable_shell": False,
            },
        }
        if photo is not None:
            encoded = base64.b64encode(photo).decode("ascii")
            body["images"] = [{"image_url": f"data:image/jpeg;base64,{encoded}"}]
        try:
            payload = self._transport.post(url, body)
        except Exception as exc:
            _log.error("Muse Image call failed %s", type(exc).__name__)
            raise
        return _bytes(payload)


class MetaTransport:
    """Posts one image request to the given URL. The body and the key are not logged."""

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    def post(self, url: str, body: dict[str, Any]) -> dict[str, Any]:
        from openai import APIStatusError, OpenAI

        base, path = _split(url)
        client = OpenAI(api_key=self._api_key, base_url=base)
        try:
            payload = client.post(path, cast_to=object, body=body)
        except APIStatusError as exc:
            _log.error("Muse Image call failed status=%s", exc.status_code)
            raise
        except Exception as exc:
            _log.error("Muse Image call failed %s", type(exc).__name__)
            raise
        if isinstance(payload, dict):
            return payload
        raise TypeError("The picture response was not a JSON object.")


def _split(url: str) -> tuple[str, str]:
    marker = "/v1/"
    index = url.find(marker)
    if index == -1:
        raise ValueError("The picture URL is not on the Meta base.")
    cut = index + len("/v1")
    return url[:cut], url[cut:]


def _bytes(payload: object) -> bytes:
    if not isinstance(payload, dict):
        raise ValueError("The picture was empty.")
    rows = payload.get("data")
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
        raise ValueError("The picture was empty.")
    raw = rows[0].get("b64_json")
    if not isinstance(raw, str) or raw.strip() == "":
        raise ValueError("The picture was empty.")
    try:
        data = base64.b64decode(raw, validate=True)
    except Exception as exc:
        raise ValueError("The picture was empty.") from exc
    if not data:
        raise ValueError("The picture was empty.")
    return data
