from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict

from quotedesk.domain.policy.clauses import Condition
from quotedesk.domain.policy.rules import Outcome
from quotedesk.domain.quotes.quote import QuoteLine, QuoteState
from quotedesk.domain.shared.ids import PolicyVersionId, QuoteId, RuleId
from quotedesk.domain.shared.money import Money


class GetQuoteResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    quote_id: QuoteId
    version: int
    state: QuoteState
    policy_version: PolicyVersionId
    rule_id: RuleId
    outcome: Outcome
    customer_template: str
    lines: tuple[QuoteLine, ...]
    clauses: tuple[Condition, ...]
    price_type: Literal["fixed", "range", "none"]
    total: Money | None
    range_min: Money | None
    range_max: Money | None
    site_visit_fee: Money | None
    deposit: Money | None
    schedule_status: Literal["none"]
    expiry: date
