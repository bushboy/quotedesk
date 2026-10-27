from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

from quotedesk.domain.policy.rules import Decision, Outcome
from quotedesk.domain.services.confidence import ConfidenceBand
from quotedesk.domain.shared.errors import PolicyViolation
from quotedesk.domain.shared.money import Money

_LOW = "A fixed quote needs a higher confidence band."
_UNKNOWN = "That item is not on the rate card."
_QUANTITY = "A quantity must be greater than zero."


class RateCardItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    item_code: str
    description: str
    unit_price: Money


class RateCard(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    vat_inclusive: bool
    site_visit_fee: Money
    items: tuple[RateCardItem, ...]


class RequestedItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    item_code: str
    quantity: Decimal


class PriceFacts(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    items: tuple[RequestedItem, ...]
    discount_percent: Decimal


class PricedLine(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    item_code: str
    description: str
    quantity: Decimal
    unit_price: Money
    total: Money


class PricedQuote(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    price_type: Literal["fixed", "range", "none"]
    lines: tuple[PricedLine, ...]
    range_min: Money | None
    range_max: Money | None
    site_visit_fee: Money | None
    deposit: Money | None
    discount_percent: Decimal


def price(decision: Decision, facts: PriceFacts, rate_card: RateCard) -> PricedQuote:
    if decision.outcome == Outcome.FIXED_OFFER and decision.confidence_band == ConfidenceBand.LOW:
        raise PolicyViolation(code="policy.violation", sentence=_LOW)
    if decision.outcome == Outcome.ESCALATION:
        return _empty()
    if decision.outcome == Outcome.SITE_ASSESSMENT:
        return _empty(site_visit_fee=rate_card.site_visit_fee)
    if decision.outcome == Outcome.INDICATIVE_RANGE:
        priced = tuple(_item(rate_card, requested.item_code).unit_price for requested in facts.items)
        return _empty(
            price_type="range",
            range_min=min(priced, key=lambda amount: amount.amount),
            range_max=max(priced, key=lambda amount: amount.amount),
        )
    lines = tuple(_line(rate_card, requested) for requested in facts.items)
    return _empty(price_type="fixed", lines=lines)


def _line(rate_card: RateCard, requested: RequestedItem) -> PricedLine:
    if requested.quantity <= 0:
        raise PolicyViolation(code="policy.violation", sentence=_QUANTITY)
    item = _item(rate_card, requested.item_code)
    return PricedLine(
        item_code=item.item_code,
        description=item.description,
        quantity=requested.quantity,
        unit_price=item.unit_price,
        total=item.unit_price * requested.quantity,
    )


def _item(rate_card: RateCard, item_code: str) -> RateCardItem:
    for item in rate_card.items:
        if item.item_code == item_code:
            return item
    raise PolicyViolation(code="policy.violation", sentence=_UNKNOWN)


def _empty(
    *,
    price_type: Literal["fixed", "range", "none"] = "none",
    lines: tuple[PricedLine, ...] = (),
    range_min: Money | None = None,
    range_max: Money | None = None,
    site_visit_fee: Money | None = None,
) -> PricedQuote:
    return PricedQuote(
        price_type=price_type,
        lines=lines,
        range_min=range_min,
        range_max=range_max,
        site_visit_fee=site_visit_fee,
        deposit=None,
        discount_percent=Decimal("0"),
    )
