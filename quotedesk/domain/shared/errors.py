"""The domain errors. Domain services raise these when a value or a transition is not allowed."""

class DomainError(Exception):
    """Raised when Domai fails."""
    def __init__(self, code: str, sentence: str) -> None:
        super().__init__(sentence)
        self.code = code
        self.sentence = sentence

    def __str__(self) -> str:
        return self.sentence


class ValidationError(DomainError):
    """Raised when Validatio fails."""
    pass


class PolicyViolation(DomainError):
    """The PolicyViolation."""
    pass


class InvalidTransition(DomainError):
    """The InvalidTransition."""
    pass


class StaleQuote(DomainError):
    """The StaleQuote."""
    pass
