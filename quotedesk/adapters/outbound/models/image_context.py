"""One Spark read of an image, then SAM 3.1 on the same bytes.

The turn calls for_image with a message id. The bytes stay in the host.
Spark names the objects. Each name is one SAM concept prompt. SAM returns
the mask score that caps agreement.
"""

import base64
import json
import logging
from typing import Any

from quotedesk.adapters.outbound.models.meta.sam_geometry import SamGeometryError, masks_from_geometry
from quotedesk.adapters.outbound.models.spark import Transport
from quotedesk.application.dto.agent import ExtractionResult
from quotedesk.application.ports.media import ImageHost
from quotedesk.domain.services.confidence import RecordedMask

_DROPPED = ("size_litres", "unit_price", "outcome")
_UNREADABLE = "The segmenter did not return a result."
_PLACE = (
    "You work for a quoting assistant at a South African business. "
    "Sizes are metres. Do not use feet, inches, or US or UK product names."
)
_READ = (
    f"{_PLACE} Describe the customer photo. "
    "Return a JSON object with summary, objects, blur, darkness, and wrong_subject. "
    "summary is one sentence. objects is a list of names. "
    "blur, darkness, and wrong_subject are true or false."
)
_log = logging.getLogger(__name__)


class _SamUnavailable(Exception):
    def __init__(self, sentence: str) -> None:
        super().__init__(sentence)
        self.sentence = sentence


class ImageEnricher:
    def __init__(
        self,
        *,
        host: ImageHost,
        transport: Transport,
        model_id: str,
        base_url: str,
        segment_transport: Transport | None = None,
        sam_model_id: str = "sam-3.1",
        sam_base_url: str | None = None,
    ) -> None:
        self._host = host
        self._transport = transport
        self._model_id = model_id
        self._url = base_url.rstrip("/") + "/responses"
        self._segment_transport = segment_transport or transport
        self._sam_model_id = sam_model_id
        self._sam_url = (sam_base_url or base_url).rstrip("/") + "/responses"
        self._notes: dict[str, tuple[str | None, str]] = {}
        self._cache: dict[str, ExtractionResult] = {}

    def note(self, provider_message_id: str, media_id: str | None, caption: str) -> None:
        self._notes[provider_message_id] = (media_id, caption)

    def for_image(self, provider_message_id: str) -> ExtractionResult | None:
        cached = self._cache.get(provider_message_id)
        if cached is not None:
            return cached
        media_id, caption = self._notes.get(provider_message_id, (None, ""))
        if not media_id:
            return None
        found = self._host.get(media_id)
        if found is None:
            return None
        mime, data = found
        try:
            extracted = self._transport.post(self._url, _extract_body(self._model_id, caption, mime, data))
            _log.info("Image analyser id=%s text=%s", provider_message_id, _logged(extracted))
            fields = _fields(_as_object(extracted))
        except Exception as exc:
            _log.warning("Image read failed for %s: %s", provider_message_id, exc)
            return None
        objects = tuple(dict.fromkeys(str(name) for name in fields["objects"] if str(name).strip()))
        try:
            masks = self._segment(provider_message_id, objects, mime, data) if objects else ()
        except _SamUnavailable as exc:
            result = ExtractionResult(sam_error=True, sam_sentence=exc.sentence, masks=(), **fields)
        else:
            result = ExtractionResult(masks=masks, **fields)
        self._cache[provider_message_id] = result
        _log.info(
            "Image extraction id=%s summary=%s objects=%s sam_error=%s",
            provider_message_id,
            result.summary,
            ", ".join(result.objects),
            result.sam_error,
        )
        return result

    def _segment(
        self, provider_message_id: str, objects: tuple[str, ...], mime: str, data: bytes
    ) -> tuple[RecordedMask, ...]:
        found: list[RecordedMask] = []
        for name in objects:
            body = _sam_body(self._sam_model_id, name, mime, data)
            try:
                payload = self._segment_transport.post(self._sam_url, body)
            except Exception as exc:
                _log.warning("SAM call failed for %s label=%s: %s", provider_message_id, name, exc)
                raise _SamUnavailable(str(exc)) from exc
            failure = _sam_failure(payload)
            if failure is not None:
                _log.warning("SAM call failed for %s label=%s: %s", provider_message_id, name, failure)
                raise _SamUnavailable(failure)
            try:
                masks = masks_from_geometry(_output_text(payload), name)
            except SamGeometryError as exc:
                _log.warning("SAM geometry unreadable for %s label=%s", provider_message_id, name)
                raise _SamUnavailable(_UNREADABLE) from exc
            score = masks[0].score if masks else None
            _log.info("SAM id=%s label=%s model=%s score=%s", provider_message_id, name, self._sam_model_id, score)
            found.extend(masks)
        return tuple(found)


def _extract_body(model_id: str, caption: str, mime: str, data: bytes) -> dict[str, Any]:
    return {
        "model": model_id,
        "instructions": _READ,
        "input": [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": caption or "Customer photo."},
                    *_image_part(mime, data),
                ],
            }
        ],
    }


def _sam_body(model_id: str, name: str, mime: str, data: bytes) -> dict[str, Any]:
    return {
        "model": model_id,
        "input": [
            {
                "type": "message",
                "role": "user",
                "content": [
                    {"type": "input_text", "text": name},
                    *_image_part(mime, data),
                ],
            }
        ],
        "metadata": {"include_confidence": "true", "mask_encoding": "one_bit"},
    }


def _sam_failure(payload: dict[str, Any]) -> str | None:
    error = payload.get("error")
    if not error:
        return None
    if isinstance(error, dict):
        return str(error.get("sentence") or error.get("message") or _UNREADABLE)
    return _UNREADABLE


def _image_part(mime: str, data: bytes) -> list[dict[str, str]]:
    encoded = base64.b64encode(data).decode("ascii")
    return [{"type": "input_image", "image_url": f"data:{mime};base64,{encoded}"}]


def _logged(payload: dict[str, Any]) -> str:
    text = _output_text(payload)
    if text:
        return text
    return json.dumps(_without_images(payload), default=str, ensure_ascii=False)


def _output_text(payload: dict[str, Any]) -> str:
    texts: list[str] = []
    for item in payload.get("output") or []:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for part in item.get("content") or []:
            if isinstance(part, dict) and part.get("type") == "output_text":
                texts.append(str(part.get("text") or ""))
    return "".join(texts).strip()


def _without_images(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            if isinstance(item, str) and item.startswith("data:image"):
                cleaned[key] = "[image]"
            else:
                cleaned[key] = _without_images(item)
        return cleaned
    if isinstance(value, list):
        return [_without_images(item) for item in value]
    if isinstance(value, str) and value.startswith("data:image"):
        return "[image]"
    return value


def _as_object(payload: dict[str, Any]) -> dict[str, Any]:
    raw = _output_text(payload)
    if raw:
        loaded = _json_object(raw)
        if loaded is not None:
            return loaded
        if "summary" not in payload and "masks" not in payload:
            return {"summary": raw, "objects": []}
    if any(key in payload for key in ("summary", "error", "masks")):
        return payload
    return payload


def _json_object(raw: str) -> dict[str, Any] | None:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if "```" in text:
            text = text[: text.rfind("```")]
        text = text.strip()
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError:
        return None
    return loaded if isinstance(loaded, dict) else None


def _fields(payload: dict[str, Any]) -> dict[str, Any]:
    kept = {key: value for key, value in payload.items() if key not in _DROPPED}
    objects = kept.get("objects") or []
    return {
        "summary": str(kept.get("summary") or ""),
        "objects": tuple(objects) if isinstance(objects, list) else (),
        "blur": bool(kept.get("blur")),
        "darkness": bool(kept.get("darkness")),
        "wrong_subject": bool(kept.get("wrong_subject")),
    }


