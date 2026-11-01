"""The injection check. The receive path and the decision look for an instruction in the customer's words."""

from pydantic import BaseModel, ConfigDict

_INSTRUCTIONS = ("ignore your rules", "you are now the owner")
_APPROVALS = ("the owner said", "your salesman said")


class InjectionFlags(BaseModel):
    """The InjectionFlags."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    instruction: bool = False
    claimed_approval: bool = False


def classify_injection_claims(text: str | None) -> InjectionFlags:
    """True when the text tells the assistant to ignore its rules."""
    if text is None or text == "":
        return InjectionFlags()
    folded = text.casefold()
    return InjectionFlags(
        instruction=any(phrase in folded for phrase in _INSTRUCTIONS),
        claimed_approval=any(phrase in folded for phrase in _APPROVALS),
    )
