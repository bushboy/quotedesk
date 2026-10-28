from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from quotedesk.domain.policy.rules import Outcome
from quotedesk.domain.shared.errors import InvalidTransition, PolicyViolation, StaleQuote
from quotedesk.domain.shared.ids import QuoteId
from quotedesk.domain.shared.money import Money
from tests.unit.domain.assertions import expect_domain, expect_validation


def _bind():
    global Approval, Condition, Quote, QuoteLine, QuoteState
    from quotedesk.domain.policy.clauses import Condition
    from quotedesk.domain.quotes.quote import Approval, Quote, QuoteLine, QuoteState

EXPIRY = date(2026, 11, 7)
AT = datetime(2026, 10, 29, 8, 0)
AT_LATER = datetime(2026, 10, 29, 9, 0)
FIXED = "An issued version cannot be changed."
ILLEGAL = "That state change is not allowed."
STALE = "That version is no longer the current quote."
QUOTE_FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "quotes" / "aquasure_5000l.json"
DECISION_FIELDS = {
    "outcome",
    "rule_id",
    "policy_version",
    "reasons",
    "confidence_band",
    "customer_template",
}
def legal_pairs():
    return (
        (QuoteState.DRAFT, QuoteState.ISSUED),
        (QuoteState.DRAFT, QuoteState.SITE_ASSESSMENT_OFFERED),
        (QuoteState.DRAFT, QuoteState.ESCALATED),
        (QuoteState.DRAFT, QuoteState.PENDING_APPROVAL),
        (QuoteState.PENDING_APPROVAL, QuoteState.ISSUED),
        (QuoteState.PENDING_APPROVAL, QuoteState.SITE_ASSESSMENT_OFFERED),
        (QuoteState.PENDING_APPROVAL, QuoteState.ESCALATED),
        (QuoteState.PENDING_APPROVAL, QuoteState.REJECTED),
        (QuoteState.PENDING_APPROVAL, QuoteState.REVISED),
        (QuoteState.ISSUED, QuoteState.WAITING_FOR_DEPOSIT),
        (QuoteState.ISSUED, QuoteState.EXPIRED),
        (QuoteState.ISSUED, QuoteState.REVISED),
        (QuoteState.ISSUED, QuoteState.PENDING_APPROVAL),
        (QuoteState.WAITING_FOR_DEPOSIT, QuoteState.DEPOSIT_PAID),
        (QuoteState.WAITING_FOR_DEPOSIT, QuoteState.EXPIRED),
        (QuoteState.WAITING_FOR_DEPOSIT, QuoteState.REVISED),
        (QuoteState.DEPOSIT_PAID, QuoteState.BOOKING_CONFIRMED),
        (QuoteState.DEPOSIT_PAID, QuoteState.EXPIRED),
        (QuoteState.SITE_ASSESSMENT_OFFERED, QuoteState.EXPIRED),
        (QuoteState.SITE_ASSESSMENT_OFFERED, QuoteState.REVISED),
        (QuoteState.SITE_ASSESSMENT_OFFERED, QuoteState.PENDING_APPROVAL),
        (QuoteState.ESCALATED, QuoteState.PENDING_APPROVAL),
        (QuoteState.ESCALATED, QuoteState.EXPIRED),
    )


def tank(unit: str = "4250.00") -> QuoteLine:
    price = Money(unit)
    return QuoteLine(
        item_code="TANK-5000",
        description="5000 L tank",
        quantity=Decimal("1"),
        unit_price=price,
        total=price * Decimal("1"),
    )


def size_clause(text: str = "Size is 5 000 L, as stated.") -> Condition:
    return Condition(
        clause_id="WATER-A1",
        clause_version="1",
        kind="assumption",
        text=text,
        if_not_true="We quote again for the actual size.",
        variation_item_code=None,
    )


def open_quote() -> Quote:
    return Quote.open(QuoteId("QD-1042"), EXPIRY)


def drafted() -> Quote:
    return open_quote().set_lines(1, (tank(),)).set_clauses(1, (size_clause(),))


def issued() -> Quote:
    return drafted().issue(Outcome.FIXED_OFFER, version=1, at=AT)


def arrive(state: QuoteState) -> Quote:
    quote = open_quote()
    if state is QuoteState.DRAFT:
        return quote
    if state is QuoteState.ISSUED:
        return quote.transition(1, QuoteState.ISSUED, at=AT)
    if state is QuoteState.SITE_ASSESSMENT_OFFERED:
        return quote.transition(1, QuoteState.SITE_ASSESSMENT_OFFERED, at=AT)
    if state is QuoteState.ESCALATED:
        return quote.transition(1, QuoteState.ESCALATED, at=AT)
    if state is QuoteState.PENDING_APPROVAL:
        return quote.transition(1, QuoteState.PENDING_APPROVAL, at=AT)
    if state is QuoteState.REJECTED:
        return arrive(QuoteState.PENDING_APPROVAL).transition(1, QuoteState.REJECTED, at=AT)
    if state is QuoteState.WAITING_FOR_DEPOSIT:
        return arrive(QuoteState.ISSUED).transition(1, QuoteState.WAITING_FOR_DEPOSIT, at=AT)
    if state is QuoteState.DEPOSIT_PAID:
        return arrive(QuoteState.WAITING_FOR_DEPOSIT).transition(1, QuoteState.DEPOSIT_PAID, at=AT)
    if state is QuoteState.EXPIRED:
        return arrive(QuoteState.ISSUED).transition(1, QuoteState.EXPIRED, at=AT)
    if state is QuoteState.REVISED:
        return arrive(QuoteState.ISSUED).transition(1, QuoteState.REVISED, at=AT)
    raise AssertionError(state)


def revised() -> Quote:
    return issued().revise(
        Outcome.FIXED_OFFER,
        line_items=(tank("100.00"),),
        clauses=(),
        expiry=EXPIRY,
        at=AT_LATER,
    )


def test_issued_version_is_immutable():
    _bind()
    quote = issued()
    expect_domain(
        lambda: quote.set_lines(1, (tank("1.00"),)),
        PolicyViolation,
        "policy.violation",
        FIXED,
    )
    expect_domain(
        lambda: quote.set_clauses(1, (size_clause("Changed."),)),
        PolicyViolation,
        "policy.violation",
        FIXED,
    )
    expect_domain(
        lambda: quote.set_expiry(1, date(2026, 12, 1)),
        PolicyViolation,
        "policy.violation",
        FIXED,
    )
    line = quote.current.lines[0]
    assert line.unit_price == Money("4250.00")
    assert line.total == Money("4250.00")
    assert quote.current.clauses[0].text == "Size is 5 000 L, as stated."
    assert quote.current.expiry == EXPIRY


def test_new_version_revises_the_previous():
    _bind()
    quote = revised()
    previous = quote.version(1)
    assert previous.state == QuoteState.REVISED
    assert previous.lines[0].item_code == "TANK-5000"
    assert previous.lines[0].unit_price == Money("4250.00")
    assert previous.lines[0].total == Money("4250.00")
    assert quote.current.number == 2
    assert quote.current.state == QuoteState.ISSUED
    assert quote.current.lines[0].unit_price == Money("100.00")


def test_illegal_transitions():
    _bind()
    cases = (
        (QuoteState.ISSUED, QuoteState.DRAFT),
        (QuoteState.EXPIRED, QuoteState.BOOKING_CONFIRMED),
        (QuoteState.REJECTED, QuoteState.ISSUED),
        (QuoteState.ESCALATED, QuoteState.ISSUED),
    )
    for source, target in cases:
        quote = arrive(source)
        before = quote.current.state
        expect_domain(
            lambda quote=quote, target=target: quote.transition(quote.current.number, target, at=AT),
            InvalidTransition,
            "quote.invalid_transition",
            ILLEGAL,
        )
        assert quote.current.state == before


def test_every_legal_transition():
    _bind()
    pairs = legal_pairs()
    assert len(pairs) == 23
    for source, target in pairs:
        quote = arrive(source)
        moved = quote.transition(quote.current.number, target, at=AT)
        assert moved.current.state == target
        assert moved.current.number == quote.current.number


def test_stale_version_is_rejected():
    _bind()
    quote = revised()
    expect_domain(
        lambda: quote.transition(1, QuoteState.EXPIRED, at=AT),
        StaleQuote,
        "quote.stale",
        STALE,
    )
    assert quote.version(1).state == QuoteState.REVISED
    moved = quote.transition(2, QuoteState.WAITING_FOR_DEPOSIT, at=AT)
    assert moved.current.number == 2
    assert moved.current.state == QuoteState.WAITING_FOR_DEPOSIT


def test_approval_is_bound_to_one_version():
    _bind()
    quote = revised()
    expires = datetime(2026, 11, 7, 0, 0)
    expect_domain(
        lambda: quote.apply_approval(2, Approval(applies_to_version=1, expires_at=expires), at=expires),
        PolicyViolation,
        "policy.violation",
        "An approval applies to one version.",
    )
    expect_domain(
        lambda: quote.apply_approval(
            2,
            Approval(applies_to_version=2, expires_at=expires),
            at=datetime(2026, 11, 7, 0, 0, 1),
        ),
        PolicyViolation,
        "policy.violation",
        "An approval after expiry does not apply.",
    )
    assert quote.current.approvals == ()
    kept = quote.apply_approval(2, Approval(applies_to_version=2, expires_at=expires), at=expires)
    stored = kept.current.approvals
    assert len(stored) == 1
    assert stored[0].applies_to_version == 2
    assert stored[0].expires_at == expires
    assert quote.current.approvals == ()


def test_outcome_picks_the_issued_state():
    _bind()
    cases = (
        (Outcome.FIXED_OFFER, QuoteState.ISSUED),
        (Outcome.INDICATIVE_RANGE, QuoteState.ISSUED),
        (Outcome.SITE_ASSESSMENT, QuoteState.SITE_ASSESSMENT_OFFERED),
        (Outcome.ESCALATION, QuoteState.ESCALATED),
    )
    for outcome, state in cases:
        quote = open_quote().issue(outcome, version=1, at=AT)
        assert quote.current.state == state
        assert quote.current.number == 1


def test_quote_id_is_assigned_not_chosen_by_the_caller():
    _bind()
    quote = open_quote()
    assert quote.quote_id == QuoteId("QD-1042")
    assert quote.quote_id.value == "QD-1042"
    expect_validation(lambda: QuoteId("QD-1"), "quote_id.invalid", "A quote id looks like QD-0001.")


def _no_float(value: object) -> None:
    assert type(value) is not float
    if isinstance(value, dict):
        for item in value.values():
            _no_float(item)
    elif isinstance(value, list):
        for item in value:
            _no_float(item)


def test_fixture_quote_5000l_replacement():
    payload = json.loads(QUOTE_FIXTURE.read_text(encoding="utf-8"))
    _no_float(payload)
    assert payload["quote_id"] == "QD-1042"
    assert payload["version"] == 1
    assert type(payload["version"]) is int
    assert payload["state"] == "ISSUED"
    assert payload["expiry"] == "2026-11-07"
    assert set(payload["decision"]) == DECISION_FIELDS
    assert payload["decision"]["outcome"] == "fixed_offer"
    assert payload["decision"]["rule_id"] == "WATER-F01"
    assert payload["decision"]["policy_version"] == "water-policy-v1.0"
    lines = payload["line_items"]
    assert len(lines) == 1
    line = lines[0]
    assert line["item_code"] == "TANK-5000"
    assert line["quantity"] == "1"
    assert type(line["unit_price"]) is str
    assert type(line["total"]) is str
    assert Money(line["unit_price"]) == Money("4250.00")
    assert Money(line["total"]) == Money("4250.00")
    assert [item["clause_id"] for item in payload["clauses"]] == ["WATER-A1", "GEN-V1", "GEN-S1"]
    assert "range_min" not in payload
    assert "site_visit_fee" not in payload
    assert "deposit" not in payload
    assert "discount" not in payload
