from pydantic import BaseModel, ConfigDict

from quotedesk.domain.policy.clauses import ClausePolicy
from quotedesk.domain.policy.rules import Policy
from quotedesk.domain.services.price import RateCard


class PublishedPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    policy: Policy
    rate_card: RateCard
    clause_policy: ClausePolicy
