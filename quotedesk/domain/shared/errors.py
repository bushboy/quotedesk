class DomainError(Exception):
    def __init__(self, code: str, sentence: str) -> None:
        super().__init__(sentence)
        self.code = code
        self.sentence = sentence

    def __str__(self) -> str:
        return self.sentence


class ValidationError(DomainError):
    pass


class PolicyViolation(DomainError):
    pass


class InvalidTransition(DomainError):
    pass


class StaleQuote(DomainError):
    pass
