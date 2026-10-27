import pytest

from tests.unit.domain.assertions import expect_validation
from quotedesk.domain.shared.ids import PolicyVersionId, QuoteId, RuleId

QUOTE_SENTENCE = "A quote id looks like QD-0001."
POLICY_SENTENCE = "A policy version id looks like water-policy-v1.2."
RULE_SENTENCE = "A rule id looks like WATER-F01."


def test_quote_id_pattern():
    for value in ("QD-0001", "QD-12345678"):
        parsed = QuoteId(value)
        assert parsed.value == value
        assert QuoteId(value=value) == parsed

    for value in ("QD-123", "QD-123456789", "qd-0001", "QD-", "QD-0001 "):
        expect_validation(lambda value=value: QuoteId(value), "quote_id.invalid", QUOTE_SENTENCE)

    quote = QuoteId("QD-0001")
    with pytest.raises(Exception):
        quote.value = "QD-0002"
    assert quote.value == "QD-0001"


def test_policy_version_id():
    for value in ("water-policy-v1.2", "fab-policy-v1.1"):
        parsed = PolicyVersionId(value)
        assert parsed.value == value
        assert PolicyVersionId(value=value) == parsed

    for value in ("water-policy-1.2", "v1.2", "", "Water-policy-v1.2"):
        expect_validation(
            lambda value=value: PolicyVersionId(value),
            "policy_version_id.invalid",
            POLICY_SENTENCE,
        )


def test_rule_id():
    for value in ("WATER-F01", "FAB-L02", "WATER-E03", "FAB-B01"):
        parsed = RuleId(value)
        assert parsed.value == value
        assert RuleId(value=value) == parsed

    for value in ("F01", "water-f01", "WATER-F1", "WATER-F001"):
        expect_validation(lambda value=value: RuleId(value), "rule_id.invalid", RULE_SENTENCE)
