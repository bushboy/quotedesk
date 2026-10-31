"""SAM 3.1 image lines to one score per prompted object.

The wire format is special-token text: a frame marker, then a box and a mask
for each match. This keeps the confidence. It does not decode the mask raster.
"""

import re
from decimal import Decimal, InvalidOperation

from quotedesk.domain.services.confidence import RecordedMask

_LINE = re.compile(r"<(\d+)f>(.*)\Z")
_RECORD = re.compile(r"\d+<\|box;([^|]*)\|><\|mask;([^|]*)\|>")
_UNREADABLE = "The segmenter did not return a result."


class SamGeometryError(ValueError):
    def __init__(self) -> None:
        super().__init__(_UNREADABLE)


def masks_from_geometry(text: str, label: str) -> tuple[RecordedMask, ...]:
    """The best confidence for `label`, or no mask when SAM found nothing."""
    raw = text.strip()
    if not raw:
        return ()
    best: Decimal | None = None
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        for score in _line_scores(stripped):
            if best is None or score > best:
                best = score
    if best is None:
        return ()
    return (RecordedMask(label=label, score=best),)


def _line_scores(line: str) -> list[Decimal]:
    matched = _LINE.fullmatch(line)
    if matched is None:
        raise SamGeometryError()
    body = matched.group(2)
    if body == "":
        return []
    records = _records(body)
    if records is None:
        raise SamGeometryError()
    scores: list[Decimal] = []
    for box, mask in records:
        score = _confidence(box, mask)
        if score is None:
            raise SamGeometryError()
        scores.append(score)
    return scores


def _records(body: str) -> list[tuple[str, str]] | None:
    matches = list(_RECORD.finditer(body))
    if not matches:
        return None
    cursor = 0
    found: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        gap = body[cursor : match.start()]
        if gap != ("" if index == 0 else ","):
            return None
        cursor = match.end()
        found.append((match.group(1), match.group(2)))
    if cursor != len(body):
        return None
    return found


def _confidence(box: str, mask: str) -> Decimal | None:
    box_fields = _pairs(box)
    mask_fields = _pairs(mask)
    raw = _first(box_fields, "c", "score") or _first(mask_fields, "c", "score")
    if raw is None:
        return None
    try:
        score = Decimal(raw)
    except InvalidOperation:
        return None
    if score < 0 or score > 1:
        return None
    return score


def _first(fields: dict[str, str], *keys: str) -> str | None:
    for key in keys:
        if key in fields:
            return fields[key]
    return None


def _pairs(body: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for part in body.split(";"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        fields[key.strip()] = value.strip()
    return fields
