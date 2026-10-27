from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict

from quotedesk.domain.services.confidence import (
    ConfidenceChecks,
    RecordedMask,
    SizeSource,
)


class JobKind(str, Enum):
    REPLACEMENT = "replacement"
    NEW_SYSTEM = "new_system"
    BOREHOLE = "borehole"
    UNKNOWN = "unknown"


class CaseFacts(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    checks: ConfidenceChecks
    job: JobKind = JobKind.UNKNOWN
    customer_text: str | None = None
    voice_transcript: str | None = None
    size_litres: int | None = None
    size_source: SizeSource | None = None
    existing_level_base: bool = False
    base_unconfirmed: bool = False
    new_tank_and_pump: bool = False
    sloped_ground: bool = False
    pipe_run_unknown: bool = False
    item_codes: tuple[str, ...] = ()


class ExtractionFacts(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stand_condition: Literal["sound", "leaning", "cracked", "sagging"] | None = None
    elevated: bool = False
    structure_damage: bool = False
    exposed_wiring: bool = False
    active_flooding: bool = False
    image_text: str | None = None


class SegmentationFacts(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    masks: tuple[RecordedMask, ...] = ()
    sam_error: bool = False
