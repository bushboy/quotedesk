"""The confidence band. The quote path uses the rate card and the confirmed facts."""

from decimal import Decimal
from enum import Enum
from typing import Mapping, Sequence

from pydantic import BaseModel, ConfigDict


class ConfidenceBand(str, Enum):
    """The ConfidenceBand."""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ConfidenceChecks(BaseModel):
    """The ConfidenceChecks."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    required_fields: bool
    agreement: bool
    measurement: bool
    media_usable: bool
    rate_card: bool


class SizeSource(str, Enum):
    """The SizeSource."""
    PHOTO_INFERRED = "photo_inferred"
    CUSTOMER_STATED = "customer_stated"
    REFERENCE_OBJECT = "reference_object"


class SizeFact(BaseModel):
    """The SizeFact."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    litres: int
    source: SizeSource


class MediaUsability(BaseModel):
    """The MediaUsability."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    has_media: bool
    blur: bool = False
    darkness: bool = False
    unintelligible_audio: bool = False
    wrong_subject: bool = False


class RecordedMask(BaseModel):
    """The RecordedMask."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    label: str
    score: Decimal


def derive_confidence(checks: ConfidenceChecks) -> ConfidenceBand:
    """Whether the customer has confirmed the facts a price needs.

    Agreement, measurement, and media usability describe a photo. They guide
    what to ask next, and they do not change this band. Confirmed required
    facts are high. A required fact that is still open is medium, so the
    conversation keeps asking. An item code that is not on the rate card is low.
    """
    if not checks.rate_card:
        return ConfidenceBand.LOW
    if checks.required_fields:
        return ConfidenceBand.HIGH
    return ConfidenceBand.MEDIUM


def required_fields_complete(values: Mapping[str, object], required: Sequence[str]) -> bool:
    """True when every required fact the price uses is confirmed."""
    for key in required:
        if key not in values or not _present(values[key]):
            return False
    return True


def _present(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    return True


def cross_model_agreement(
    *,
    has_image: bool,
    has_video: bool,
    spark_objects: Sequence[str],
    sam_error: bool,
    masks: Sequence[RecordedMask],
    threshold: Decimal,
) -> bool:
    """True when SAM and Spark name the same object. The quote path does not read it."""
    if not has_image and not has_video:
        return True
    if sam_error or len(masks) == 0:
        return False
    for name in spark_objects:
        if not any(mask.label == name and mask.score >= threshold for mask in masks):
            return False
    return True


def measurement_acceptable(sizes: Sequence[SizeFact]) -> bool:
    """True when a stated size and an inferred size agree. The quote path does not read it."""
    if not sizes:
        return True
    accepted = [size for size in sizes if size.source is not SizeSource.PHOTO_INFERRED]
    inferred = [size for size in sizes if size.source is SizeSource.PHOTO_INFERRED]
    if inferred and not accepted:
        return False
    return len({size.litres for size in sizes}) == 1


def media_is_usable(media: MediaUsability) -> bool:
    """True when the photo is clear enough to read."""
    if not media.has_media:
        return True
    return not (media.blur or media.darkness or media.unintelligible_audio or media.wrong_subject)


def rate_card_match(item_codes: Sequence[str], rate_card_codes: set[str]) -> bool:
    """True when every item code is on the rate card."""
    return all(code in rate_card_codes for code in item_codes)
