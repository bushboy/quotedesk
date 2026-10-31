"""One Spark read of an image, then SAM 3.1 on the same bytes.

The turn calls for_image with a message id. The bytes stay in the host.
A known subject searches a fixed list of objects. Otherwise Spark names the
objects, and each name is one SAM concept prompt. SAM returns the mask score
that caps agreement.
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
_CARPORT_READ = (
    f"{_PLACE} This business builds carports and replaces sheeting. Describe the customer photo. "
    "Return a JSON object with summary, notes, blur, darkness, and wrong_subject. "
    "summary is one sentence. notes is a list of short sentences. "
    "The customer's message, when they wrote one, says what the photo is for. "
    "A garage or a house can be the place a carport will be mounted. "
    "A single garage, a double garage, an existing carport, or a house wall can show the size. "
    "Put that clue in notes. Give metres only when the photo shows them. Do not invent a price. "
    "blur, darkness, and wrong_subject are true or false."
)
# First a carport. Otherwise a garage or a house. Otherwise sheeting.
_CARPORT_STEPS = (("carport",), ("garage", "house"), ("sheeting",))
_CARPORT_CLUES = {
    "carport": ("single carport", "double carport"),
    "garage": ("single garage", "double garage"),
    "house": ("house wall",),
}
_TANK_READ = (
    f"{_PLACE} This business installs and replaces water tanks. Describe the customer photo. "
    "Return a JSON object with summary, notes, blur, darkness, and wrong_subject. "
    "summary is one sentence. notes is a list of short sentences. "
    "The customer's message, when they wrote one, says what the photo is for. "
    "An existing tank, a tank stand, or a leak on a tank can show a replacement and a size. "
    "A house or a downpipe can be where water will be collected. "
    "The space where a tank could sit can show the size and whether that place is suitable. "
    "Give litres only when the photo shows them. Do not invent a price. "
    "blur, darkness, and wrong_subject are true or false."
)
# First a tank, a stand, or a leak. Otherwise a house or a downpipe, then the space.
_TANK_STEPS = (("tank", "tank stand", "tank leak"), ("house", "downpipe"))
_TANK_CLUES = {
    "house": ("tank space",),
    "downpipe": ("tank space",),
}
_READS = {"carport": _CARPORT_READ, "tank": _TANK_READ}
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
        subject: str = "",
    ) -> None:
        self._host = host
        self._transport = transport
        self._model_id = model_id
        self._url = base_url.rstrip("/") + "/responses"
        self._segment_transport = segment_transport or transport
        self._sam_model_id = sam_model_id
        self._sam_url = (sam_base_url or base_url).rstrip("/") + "/responses"
        self._subject = subject
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
            extracted = self._transport.post(
                self._url, _extract_body(self._model_id, caption, mime, data, self._subject)
            )
            _log.info("Image analyser id=%s text=%s", provider_message_id, _logged(extracted))
            fields = _fields(_as_object(extracted))
        except Exception as exc:
            _log.warning("Image read failed for %s: %s", provider_message_id, exc)
            return None
        objects = tuple(dict.fromkeys(str(name) for name in fields["objects"] if str(name).strip()))
        try:
            scene = _SCENES.get(self._subject)
            if scene is not None:
                steps, clues, notes_for = scene
                masks, seen = self._focused_scene(provider_message_id, mime, data, steps, clues)
                objects = seen
                fields["notes"] = _merge(notes_for(seen, caption), fields["notes"])
            else:
                masks = self._segment(provider_message_id, objects, mime, data) if objects else ()
        except _SamUnavailable as exc:
            result = ExtractionResult(sam_error=True, sam_sentence=exc.sentence, masks=(), **fields)
        else:
            fields["objects"] = objects
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

    def _focused_scene(
        self,
        provider_message_id: str,
        mime: str,
        data: bytes,
        steps: tuple[tuple[str, ...], ...],
        clues: dict[str, tuple[str, ...]],
    ) -> tuple[tuple[RecordedMask, ...], tuple[str, ...]]:
        """The first step that returns a mask, then the size clues for those hits."""
        masks: list[RecordedMask] = []
        seen: list[str] = []
        for step in steps:
            hits = []
            for name in step:
                found = self._probe(provider_message_id, name, mime, data)
                if found:
                    hits.append(name)
                    masks.extend(found)
            if hits:
                seen.extend(hits)
                asked: set[str] = set()
                for name in hits:
                    for clue in clues.get(name, ()):
                        if clue in asked:
                            continue
                        asked.add(clue)
                        extra = self._probe(provider_message_id, clue, mime, data)
                        if extra:
                            seen.append(clue)
                            masks.extend(extra)
                break
        return tuple(masks), tuple(seen)

    def _probe(self, provider_message_id: str, name: str, mime: str, data: bytes) -> tuple[RecordedMask, ...]:
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
        return masks


def _extract_body(model_id: str, caption: str, mime: str, data: bytes, subject: str = "") -> dict[str, Any]:
    return {
        "model": model_id,
        "instructions": _READS.get(subject, _READ),
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
        "notes": _note_list(kept.get("notes")),
        "blur": bool(kept.get("blur")),
        "darkness": bool(kept.get("darkness")),
        "wrong_subject": bool(kept.get("wrong_subject")),
    }


def _note_list(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return ()
    return tuple(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))


def _merge(first: tuple[str, ...], second: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys((*first, *second)))


def _carport_notes(seen: tuple[str, ...], caption: str) -> tuple[str, ...]:
    """What the found objects can tell the agent. Metres stay out of these sentences."""
    found = set(seen)
    notes: list[str] = []
    if "carport" in found:
        notes.append("A carport is in the photo. Its extent is the size to confirm.")
    elif "garage" in found or "house" in found:
        place = " and a ".join(name for name in ("garage", "house") if name in found)
        notes.append(f"A {place} is in the photo. It is a place a carport can be mounted.")
        said = caption.strip()
        if said and said != "Customer photo.":
            notes.append(f"The customer said: {said}")
            notes.append("Use that message to decide whether this is where the carport will go.")
    elif "sheeting" in found:
        notes.append("Sheeting is in the photo. Name the closest sheet on the rate card and ask them to confirm it.")
    else:
        notes.append("The photo does not show a carport, a garage, a house, or sheeting.")
    if "single carport" in found:
        notes.append("The carport is a single bay. That bay is the width to confirm.")
    if "double carport" in found:
        notes.append("The carport is a double bay. Those two bays are the width to confirm.")
    if "single garage" in found:
        notes.append("A single garage is in the photo. That bay is the width to confirm.")
    if "double garage" in found:
        notes.append("A double garage is in the photo. Those two bays are the width to confirm.")
    if "house wall" in found:
        notes.append("A house wall is in the photo. The wall is the span to confirm.")
    return tuple(notes)


def _tank_notes(seen: tuple[str, ...], caption: str) -> tuple[str, ...]:
    """What the found objects can tell the agent. Litres stay out of these sentences."""
    found = set(seen)
    notes: list[str] = []
    has_tank = "tank" in found or "tank leak" in found
    has_stand = "tank stand" in found
    if has_tank or has_stand:
        if "tank" in found:
            notes.append("A tank is in the photo. It may be a replacement. That tank is the size to confirm.")
        if "tank stand" in found:
            notes.append(
                "A tank stand is in the photo. The stand is already there, so this may be a replacement. "
                "The stand is the space the next tank has to fit."
            )
        if "tank leak" in found:
            notes.append("A leak is on a tank in the photo. The tank is already there, so this may be a replacement.")
    elif "house" in found or "downpipe" in found:
        place = " and a ".join(name for name in ("house", "downpipe") if name in found)
        notes.append(f"A {place} is in the photo. It is a place water can be collected.")
        said = caption.strip()
        if said and said != "Customer photo.":
            notes.append(f"The customer said: {said}")
            notes.append("Use that message to decide whether this is where the tank will go.")
    else:
        notes.append("The photo does not show a tank, a tank stand, a leak, a house, or a downpipe.")
    if "tank space" in found:
        notes.append(
            "The open space is where a tank could sit. That space is the size and the suitability to confirm."
        )
    return tuple(notes)


_SCENES = {
    "carport": (_CARPORT_STEPS, _CARPORT_CLUES, _carport_notes),
    "tank": (_TANK_STEPS, _TANK_CLUES, _tank_notes),
}


