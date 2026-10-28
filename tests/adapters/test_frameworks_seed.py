from decimal import Decimal
from pathlib import Path

from quotedesk.adapters.outbound.parsers.aquasure import load_policy
from tests.unit.domain.fabricator_policy import fabricator_policy

SEED = Path("seeds/frameworks.yaml")


def test_frameworks_seed_matches_fixtures() -> None:
    loaded = load_policy(SEED)
    current = fabricator_policy()
    assert loaded.version == current.version
    assert loaded.sam_score_threshold == current.sam_score_threshold
    assert loaded.rate_card_codes == current.rate_card_codes
    assert loaded.range_minimum == Decimal("850.00")
    assert [rule.rule_id for rule in loaded.rules] == [rule.rule_id for rule in current.rules]
    assert [rule.outcome for rule in loaded.rules] == [rule.outcome for rule in current.rules]
    assert [rule.customer_template for rule in loaded.rules] == [rule.customer_template for rule in current.rules]
