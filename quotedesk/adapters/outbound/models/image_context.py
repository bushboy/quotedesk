"""One Spark read of an image, then SAM on the same bytes.

The turn calls for_image with a message id. The bytes stay in the host.
"""

import base64
import json
import logging
from typing import Any

from quotedesk.adapters.outbound.models.baseten.sam_parser import SamFailure, parse_sam_response
from quotedesk.adapters.outbound.models.spark import Transport
from quotedesk.application.dto.agent import ExtractionResult
from quotedesk.application.ports.media import ImageHost
from quotedesk.domain.services.confidence import RecordedMask

_DROPPED = ("size_litres", "unit_price", "outcome")
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
_SEGMENT = (
    f"{_PLACE} Segment the named objects in the customer photo. "
    "This is image segmentation, not text, market, or audience segmentation. "
    "Return a JSON object with masks. Each mask has label, score, and caption."
)
_log = logging.getLogger(__name__)


class ImageEnricher:
    def __init__(self, *, host: ImageHost, transport: Transport, model_id: str, base_url: str) -> None:
        self._host = host
        self._transport = transport
        self._model_id = model_id
        self._url = base_url.rstrip("/") + "/responses"
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
        objects = tuple(str(name) for name in fields["objects"])
        parsed: dict[str, Any] = {"masks": []}
        if objects:
            try:
                segmented = self._transport.post(self._url, _segment_body(self._model_id, objects, mime, data))
                _log.info("Image analyser segments id=%s text=%s", provider_message_id, _logged(segmented))
                parsed = _as_object(segmented)
            except Exception as exc:
                parsed = {"error": {"code": "sam.unavailable", "sentence": str(exc)}}
        result = _with_masks(fields, parsed)
        self._cache[provider_message_id] = result
        _log.info(
            "Image extraction id=%s summary=%s objects=%s sam_error=%s",
            provider_message_id,
            result.summary,
            ", ".join(result.objects),
            result.sam_error,
        )
        return result


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


def _segment_body(model_id: str, objects: tuple[str, ...], mime: str, data: bytes) -> dict[str, Any]:
    return {
        "model": model_id,
        "instructions": _SEGMENT,
        "input": [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "Segment: " + ", ".join(objects)},
                    *_image_part(mime, data),
                ],
            }
        ],
    }


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


def _with_masks(fields: dict[str, Any], payload: dict[str, Any]) -> ExtractionResult:
    parsed = parse_sam_response(payload)
    if isinstance(parsed, SamFailure):
        return ExtractionResult(sam_error=True, sam_sentence=parsed.sentence, masks=(), **fields)
    return ExtractionResult(
        masks=tuple(RecordedMask(label=mask.label, score=mask.score) for mask in parsed.masks),
        notes=tuple(mask.caption.strip() for mask in parsed.masks if mask.caption.strip()),
        **fields,
    )
