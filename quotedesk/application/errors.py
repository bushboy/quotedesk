class ApplicationError(Exception):
    def __init__(self, code: str, sentence: str) -> None:
        super().__init__(sentence)
        self.code = code
        self.sentence = sentence

    def __str__(self) -> str:
        return self.sentence


class TenantRequired(ApplicationError):
    def __init__(self) -> None:
        super().__init__(code="tenant.required", sentence="A use case needs a tenant.")


class CaseNotFound(ApplicationError):
    def __init__(self) -> None:
        super().__init__(code="case.not_found", sentence="That case is not on this tenant.")
