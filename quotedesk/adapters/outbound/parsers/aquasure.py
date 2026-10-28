from decimal import Decimal
from pathlib import Path

import yaml

from quotedesk.domain.policy.rules import Outcome, Policy, PolicyRule
from quotedesk.domain.shared.ids import PolicyVersionId, RuleId


def load_policy(path: Path) -> Policy:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    minimum = raw.get("range_minimum")
    return Policy(
        version=PolicyVersionId(raw["version"]),
        sam_score_threshold=Decimal(str(raw["sam_score_threshold"])),
        rate_card_codes=tuple(raw["rate_card_codes"]),
        range_minimum=None if minimum is None else Decimal(str(minimum)),
        rules=tuple(
            PolicyRule(
                rule_id=RuleId(rule["rule_id"]),
                priority=rule["priority"],
                outcome=Outcome(rule["outcome"]),
                customer_template=rule["customer_template"],
                reason=rule["reason"],
            )
            for rule in raw["rules"]
        ),
    )
