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
            fields = _fields(_as_object(extracted))
        except Exception:
            _log.warning("Image read failed for %s", provider_message_id)
            return None
        objects = tuple(str(name) for name in fields["objects"])
        try:
            segmented = self._transport.post(self._url, _segment_body(self._model_id, objects))
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
    encoded = base64.b64encode(data).decode("ascii")
    return {
        "model": model_id,
        "input": [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": caption},
                    {"type": "input_image", "image_url": f"data:{mime};base64,{encoded}"},
                ],
            }
        ],
    }


def _segment_body(model_id: str, objects: tuple[str, ...]) -> dict[str, Any]:
    return {
        "model": model_id,
        "input": [{"role": "user", "content": "Segment: " + ", ".join(objects)}],
    }


def _as_object(payload: dict[str, Any]) -> dict[str, Any]:
    if any(key in payload for key in ("summary", "error", "masks")):
        return payload
    texts: list[str] = []
    for item in payload.get("output") or []:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for part in item.get("content") or []:
            if isinstance(part, dict) and part.get("type") == "output_text":
                texts.append(str(part.get("text") or ""))
    raw = "".join(texts).strip()
    if not raw:
        return payload
    loaded = json.loads(raw)
    return loaded if isinstance(loaded, dict) else payload


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
        **fields,
    )
