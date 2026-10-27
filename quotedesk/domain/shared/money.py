import re
from decimal import Decimal, ROUND_HALF_EVEN
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from quotedesk.domain.shared.errors import ValidationError

_CENT = Decimal("0.01")
_AMOUNT = re.compile(r"\d+(?:\.\d+)?")
_NEGATIVE_AMOUNT = re.compile(r"-\d+(?:\.\d+)?")
_SENTENCES = {
    "money.float": "A price must be a decimal amount, not a floating-point number.",
    "money.negative": "A price cannot be negative.",
    "money.blank": "A price is required.",
    "money.currency": "Prices are in ZAR.",
    "money.invalid": "That amount cannot be used as a price.",
}


def _reject(code: str) -> None:
    raise ValidationError(code=code, sentence=_SENTENCES[code])


def _amount(value: Any) -> Decimal:
    if isinstance(value, bool):
        _reject("money.invalid")
    if isinstance(value, float):
        _reject("money.float")
    if value is None:
        _reject("money.blank")
    if isinstance(value, str):
        if value.strip() == "":
            _reject("money.blank")
        if _NEGATIVE_AMOUNT.fullmatch(value):
            _reject("money.negative")
        if _AMOUNT.fullmatch(value) is None:
            _reject("money.invalid")
        parsed = Decimal(value)
    elif isinstance(value, int):
        if value < 0:
            _reject("money.negative")
        parsed = Decimal(value)
    elif isinstance(value, Decimal):
        if not value.is_finite():
            _reject("money.invalid")
        if value < 0:
            _reject("money.negative")
        parsed = value
    else:
        _reject("money.invalid")
    return parsed.quantize(_CENT, rounding=ROUND_HALF_EVEN)


def _currency(currency: str) -> None:
    if currency != "ZAR":
        _reject("money.currency")


class Money(BaseModel):
    model_config = ConfigDict(frozen=True)

    amount: Decimal
    currency: Literal["ZAR"] = "ZAR"

    def __init__(self, value: Any = None, /, **data: Any) -> None:
        if value is None and "amount" in data:
            value = data["amount"]
        _currency(data.get("currency", "ZAR"))
        super().__init__(amount=_amount(value), currency="ZAR")

    @classmethod
    def parse(cls, value: Any, *, currency: str = "ZAR") -> "Money":
        return cls(value, currency=currency)

    def __add__(self, other: Any) -> "Money":
        if not isinstance(other, Money):
            _reject("money.invalid")
        return Money(self.amount + other.amount)

    def __mul__(self, quantity: Any) -> "Money":
        return Money(_amount(self.amount * _quantity(quantity)))

    def __rmul__(self, quantity: Any) -> "Money":
        return self.__mul__(quantity)


def _quantity(quantity: Any) -> Decimal:
    if isinstance(quantity, Money) or isinstance(quantity, bool):
        _reject("money.invalid")
    if isinstance(quantity, float):
        _reject("money.float")
    if isinstance(quantity, int):
        if quantity < 0:
            _reject("money.negative")
        return Decimal(quantity)
    if isinstance(quantity, Decimal):
        if not quantity.is_finite():
            _reject("money.invalid")
        if quantity < 0:
            _reject("money.negative")
        return quantity
    _reject("money.invalid")
