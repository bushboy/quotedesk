from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict

from quotedesk.domain.services.confidence import ConfidenceBand
from quotedesk.domain.shared.ids import PolicyVersionId, RuleId


class Outcome(str, Enum):
    ESCALATION = "escalation"
    SITE_ASSESSMENT = "site_assessment"
    FIXED_OFFER = "fixed_offer"
    INDICATIVE_RANGE = "indicative_range"


class PolicyRule(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    rule_id: RuleId
    priority: int
    outcome: Outcome
    customer_template: str
    reason: str


class Policy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: PolicyVersionId
    rules: tuple[PolicyRule, ...]
    rate_card_codes: tuple[str, ...]
    sam_score_threshold: Decimal
    range_minimum: Decimal | None = None


class Decision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    outcome: Outcome
    rule_id: RuleId
    policy_version: PolicyVersionId
    reasons: tuple[str, ...]
    confidence_band: ConfidenceBand
    customer_template: str
