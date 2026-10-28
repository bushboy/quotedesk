from __future__ import annotations

from datetime import date

import pytest

from quotedesk.domain.policy.clauses import Condition
from quotedesk.domain.shared.money import Money

TOOL_AMOUNT = Money("4250.00")
CARD = "https://card.example/QD-1042"
INSTALLATION = Condition(
    clause_id="GEN-I1",
    clause_version="1",
    kind="assumption",
    text="Includes installation.",
    if_not_true="Re-quote.",
)
COUNCIL = Condition(
    clause_id="CARPORT-X1",
    clause_version="1",
    kind="exclusion",
    text="Excludes municipal building plan approval, where required",
    if_not_true="Customer's responsibility; stated, not handled",
)


def _bind():
    global TurnFacts, check_reply
    from quotedesk.domain.services.commitments import TurnFacts, check_reply


@pytest.fixture(autouse=True)
def _implemented():
    _bind()


def test_reply_rand_amount_must_come_from_a_tool():
    present = TurnFacts(amounts=(TOOL_AMOUNT,))
    for reply in (
        "The total is R 4 250.",
        "The total is R4250.",
        "The total is R 4,250.",
        "The total is 4250 rand.",
        "The total is R 4 250.00.",
    ):
        result = check_reply(reply, present)
        assert result.ok is True
        assert result.code is None

    missing = check_reply("The total is R 4 250.", TurnFacts())
    assert missing.ok is False
    assert missing.code == "commitment.amount"

    second = check_reply("R 4 250 or R 3 000", present)
    assert second.ok is False
    assert second.code == "commitment.amount"


def test_reply_date_must_come_from_a_tool():
    passed = check_reply(
        "We can do 7 November.",
        TurnFacts(civil_dates=(date(2026, 11, 7),)),
    )
    assert passed.ok is True
    assert passed.code is None

    failed = check_reply("We can do this Saturday.", TurnFacts())
    assert failed.ok is False
    assert failed.code == "commitment.date"


def test_reply_inclusion_must_be_a_clause():
    passed = check_reply("This includes installation.", TurnFacts(clauses=(INSTALLATION,)))
    assert passed.ok is True
    assert passed.code is None

    failed = check_reply("This includes council plans.", TurnFacts(clauses=(COUNCIL,)))
    assert failed.ok is False
    assert failed.code == "commitment.inclusion"


def test_reply_guarantee_is_refused():
    result = check_reply(
        "Your installation date is guaranteed.",
        TurnFacts(schedule_status="escalated"),
    )
    assert result.ok is False
    assert result.code == "commitment.guarantee"


def test_reply_may_summarise_and_link():
    result = check_reply(
        "The range is R 8 500 to R 12 400. Your card: https://card.example/QD-1042",
        TurnFacts(
            amounts=(Money("8500.00"), Money("12400.00")),
            price_kind="range",
            card_link=CARD,
        ),
    )
    assert result.ok is True
    assert result.code is None
