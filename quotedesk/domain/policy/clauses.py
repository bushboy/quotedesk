from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

ClauseKind = Literal["assumption", "exclusion", "validity", "payment", "schedule"]


class Condition(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    clause_id: str
    clause_version: str
    kind: ClauseKind
    text: str
    if_not_true: str
    variation_item_code: str | None = None


class ClauseTemplate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    clause_id: str
    clause_version: str
    kind: ClauseKind
    text: str
    if_not_true: str
    variation_item_code: str | None = None


class ClauseFacts(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    width_m: Decimal | None = None
    length_m: Decimal | None = None
    roof_covering: str | None = None


class ClausePolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    templates: tuple[ClauseTemplate, ...]
    settings: dict[str, int]
    rate_card_codes: tuple[str, ...]


class ClauseSelection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    conditions: tuple[Condition, ...]
    customer_template: str
