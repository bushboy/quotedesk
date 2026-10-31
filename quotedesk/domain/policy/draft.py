from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from quotedesk.domain.policy.playbook import BusinessPlaybook
from quotedesk.domain.policy.when import When


class PolicyError(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str
    sentence: str
    clause_id: str | None = None


class DraftRateRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    item_code: str
    unit_price: Decimal
    vat_inclusive: bool
    description: str = ""
    unit: str = "each"
    role: str = "product"
    applies_to: Literal["both", "swap", "new"] = "both"
    job_types: tuple[str, ...] = ()
    when: When | None = None


class DraftClause(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    clause_id: str
    text: str
    variation_item_code: str | None = None


class RequiredFact(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    question: str | None = None


class DraftRule(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    rule_id: str
    enabled: bool
    customer_template: str | None = None
    reason: str | None = None
    when: When | None = None


class PolicyDraft(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    deposit_percent: int
    discount_cap_percent: int
    validity_days: int
    vat_inclusive: bool
    rate_rows: tuple[DraftRateRow, ...]
    clauses: tuple[DraftClause, ...]
    required_facts: tuple[RequiredFact, ...]
    rules: tuple[DraftRule, ...]
    settings: tuple[str, ...]
    playbook: BusinessPlaybook = Field(default_factory=BusinessPlaybook)
