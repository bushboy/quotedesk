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

PriceUnit = Literal["each", "per m²", "per metre"]
PriceRole = Literal["product", "frame", "hardware", "installation", "delivery", "inspection"]


class RateCardItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    item_code: str
    description: str
    unit_price: Money
    unit: PriceUnit = "each"
    role: PriceRole = "product"


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
    width_m: Decimal | None = None
    length_m: Decimal | None = None
    roles: tuple[PriceRole, ...] = ()


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
    facts = _composed(facts, rate_card)
    if decision.outcome == Outcome.INDICATIVE_RANGE:
        if not facts.items:
            return _empty()
        priced = tuple(_extended(rate_card, requested) for requested in facts.items)
        return _empty(
            price_type="range",
            range_min=min(priced, key=lambda amount: amount.amount),
            range_max=max(priced, key=lambda amount: amount.amount),
        )
    lines = tuple(_line(rate_card, requested) for requested in facts.items)
    return _empty(price_type="fixed", lines=lines)


def _composed(facts: PriceFacts, rate_card: RateCard) -> PriceFacts:
    """Requested products, plus one line for each role the job adds, measured by the item's unit."""
    chosen: list[RequestedItem] = []
    seen: set[str] = set()
    for requested in facts.items:
        item = _find(rate_card, requested.item_code)
        quantity = requested.quantity if item is None else _quantity(item, facts, requested.quantity)
        chosen.append(RequestedItem(item_code=requested.item_code, quantity=quantity))
        seen.add(requested.item_code)
    for role in facts.roles:
        if role == "product":
            continue
        for item in rate_card.items:
            if item.role == role and item.item_code not in seen:
                chosen.append(RequestedItem(item_code=item.item_code, quantity=_quantity(item, facts, Decimal("1"))))
                seen.add(item.item_code)
    return facts.model_copy(update={"items": tuple(chosen)})


def _quantity(item: RateCardItem, facts: PriceFacts, requested: Decimal) -> Decimal:
    if item.unit == "per m²" and facts.width_m is not None and facts.length_m is not None:
        return facts.width_m * facts.length_m
    if item.unit == "per metre" and facts.length_m is not None:
        return facts.length_m
    return requested


def _extended(rate_card: RateCard, requested: RequestedItem) -> Money:
    if requested.quantity <= 0:
        raise PolicyViolation(code="policy.violation", sentence=_QUANTITY)
    return _item(rate_card, requested.item_code).unit_price * requested.quantity


def _find(rate_card: RateCard, item_code: str) -> RateCardItem | None:
    for item in rate_card.items:
        if item.item_code == item_code:
            return item
    return None


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
