from decimal import Decimal
from typing import Mapping

from pydantic import BaseModel, ConfigDict


class SamMask(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    label: str
    score: Decimal
    caption: str


class SamSuccess(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    masks: tuple[SamMask, ...]


class SamFailure(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str
    sentence: str


def parse_sam_response(payload: Mapping[str, object]) -> SamSuccess | SamFailure:
    error = payload.get("error")
    if error is not None:
        if not isinstance(error, dict):
            raise TypeError("A recorded SAM error must be an object.")
        return SamFailure(code=str(error["code"]), sentence=str(error["sentence"]))
    raw_masks = payload.get("masks", [])
    if not isinstance(raw_masks, list):
        raise TypeError("A recorded SAM mask list must be a list.")
    masks = []
    for item in raw_masks:
        if not isinstance(item, dict):
            raise TypeError("A recorded SAM mask must be an object.")
        masks.append(
            SamMask(
                label=str(item["label"]),
                score=Decimal(str(item["score"])),
                caption=str(item["caption"]),
            )
        )
    return SamSuccess(masks=tuple(masks))
