from datetime import date

from pydantic import ValidationError as PydanticValidationError

from quotedesk.domain.shared.errors import (
    DomainError,
    InvalidTransition,
    PolicyViolation,
    StaleQuote,
    ValidationError,
)
from quotedesk.domain.shared.ids import QuoteId
from quotedesk.domain.shared.money import Money
from quotedesk.domain.shared.windows import DateWindow
from tests.unit.domain.assertions import expect_validation


def test_errors_carry_code_and_sentence():
    cases = [
        (
            ValidationError,
            "money.float",
            "A price must be a decimal amount, not a floating-point number.",
        ),
        (PolicyViolation, "policy.violation", "The policy refuses this."),
        (InvalidTransition, "quote.invalid_transition", "That state change is not allowed."),
        (StaleQuote, "quote.stale", "This quote version is no longer current."),
    ]
    for error_type, code, sentence in cases:
        error = error_type(code=code, sentence=sentence)
        assert type(error) is error_type
        assert isinstance(error, DomainError)
        assert not isinstance(error, ValueError)
        assert not isinstance(error, PydanticValidationError)
        assert error.code == code
        assert error.sentence == sentence
        assert str(error) == sentence


def test_money_and_id_failures_use_typed_errors():
    expect_validation(
        lambda: Money(0.1),
        "money.float",
        "A price must be a decimal amount, not a floating-point number.",
    )
    expect_validation(lambda: QuoteId("QD-123"), "quote_id.invalid", "A quote id looks like QD-0001.")
    expect_validation(
        lambda: DateWindow(start=date(2026, 11, 7), end=date(2026, 11, 6)),
        "date_window.unordered",
        "A window's end is on or after its start.",
    )
