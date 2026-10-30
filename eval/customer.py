"""The customer behind the model port.

Each call returns the next customer sentence. The facts in the prompt stay
fixed. The wording changes with the seed, so two runs of the same conversation
do not read the same way.
"""

from dataclasses import dataclass

from quotedesk.application.dto.agent import ModelReply

_FLAVOUR = (
    "I can tell you this",
    "Asseblief, let us get this done",
    "Quickly please, I am in a hurry",
)


@dataclass(frozen=True)
class CustomerPrompt:
    persona: str
    seed: int
    facts: tuple[tuple[str, str], ...]
    turn: int


class ScriptedCustomer:
    """A model-port adapter. complete() returns what the customer says next."""

    def complete(self, prompt: CustomerPrompt) -> ModelReply:
        flavour = _FLAVOUR[prompt.seed % len(_FLAVOUR)]
        opening = prompt.persona.split(";")[0].strip() or "A customer"
        parts = [f"{opening}. {flavour}."]
        for key, value in prompt.facts:
            if key == "customer_text":
                parts.append(value)
            elif value != "":
                parts.append(f"{key} {value}")
        if len(parts) == 1:
            parts.append(("Hello.", "Hi asseblief.", "Hey, are you there?")[prompt.seed % 3])
        return ModelReply(text=" ".join(parts))
