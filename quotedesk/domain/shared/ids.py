import re
from typing import Any

from pydantic import BaseModel, ConfigDict

from quotedesk.domain.shared.errors import ValidationError

_QUOTE = re.compile(r"QD-\d{4,8}")
_POLICY = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*-policy-v\d+\.\d+")
_RULE = re.compile(r"(?:WATER|FAB)-[A-Z]\d{2}")


def _identifier(value: Any, pattern: re.Pattern[str], code: str, sentence: str) -> str:
    if isinstance(value, str) and pattern.fullmatch(value):
        return value
    raise ValidationError(code=code, sentence=sentence)


class QuoteId(BaseModel):
    model_config = ConfigDict(frozen=True)

    value: str

    def __init__(self, value: Any = None, /, **data: Any) -> None:
        if value is None:
            value = data.get("value")
        super().__init__(
            value=_identifier(
                value,
                _QUOTE,
                "quote_id.invalid",
                "A quote id looks like QD-0001.",
            )
        )


class PolicyVersionId(BaseModel):
    model_config = ConfigDict(frozen=True)

    value: str

    def __init__(self, value: Any = None, /, **data: Any) -> None:
        if value is None:
            value = data.get("value")
        super().__init__(
            value=_identifier(
                value,
                _POLICY,
                "policy_version_id.invalid",
                "A policy version id looks like water-policy-v1.2.",
            )
        )


class RuleId(BaseModel):
    model_config = ConfigDict(frozen=True)

    value: str

    def __init__(self, value: Any = None, /, **data: Any) -> None:
        if value is None:
            value = data.get("value")
        super().__init__(
            value=_identifier(
                value,
                _RULE,
                "rule_id.invalid",
                "A rule id looks like WATER-F01.",
            )
        )
