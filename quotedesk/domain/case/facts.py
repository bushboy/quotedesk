from decimal import Decimal
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
    installation_damaged: bool = False
    simple_swap: bool | None = None
    base_unconfirmed: bool = False
    new_tank_and_pump: bool = False
    sloped_ground: bool = False
    pipe_run_unknown: bool = False
    item_codes: tuple[str, ...] = ()
    width_m: Decimal | None = None
    length_m: Decimal | None = None
    finish: str | None = None
    opening: Literal["existing", "new", "widened"] | None = None
    above_ground_floor: bool = False
    multi_unit: bool = False
    standard_band: bool = False
    budget: Decimal | None = None
    job_type: Literal["carport", "window", "door", "shutter"] | None = None


class ExtractionFacts(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stand_condition: Literal["sound", "leaning", "cracked", "sagging"] | None = None
    elevated: bool = False
    structure_damage: bool = False
    exposed_wiring: bool = False
    active_flooding: bool = False
    image_text: str | None = None
    lintel_cracked: bool = False
    glass_broken: bool = False
    hairline_mark: bool = False
    possible_asbestos: bool = False


class SegmentationFacts(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    masks: tuple[RecordedMask, ...] = ()
    sam_error: bool = False
