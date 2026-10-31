from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel, ConfigDict

from quotedesk.domain.policy.rules import Decision, Outcome
from quotedesk.domain.policy.when import FactView, When, matches
from quotedesk.domain.services.confidence import ConfidenceBand
from quotedesk.domain.shared.errors import PolicyViolation
from quotedesk.domain.shared.money import Money

_LOW = "A fixed quote needs a higher confidence band."
_UNKNOWN = "That item is not on the rate card."
_QUANTITY = "A quantity must be greater than zero."

PriceUnit = Literal["each", "per m²", "per metre"]
PriceRole = Literal["product", "frame", "hardware", "installation", "delivery", "inspection"]
AppliesTo = Literal["both", "swap", "new"]
WorkKind = Literal["swap", "new"]


class RateCardItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    item_code: str
    description: str
    unit_price: Money
    unit: PriceUnit = "each"
    role: PriceRole = "product"
    applies_to: AppliesTo = "both"
    job_types: tuple[str, ...] = ()
    when: When | None = None


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
    work: WorkKind | None = None
    job_type: str = ""
    values: dict[str, str] = {}


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
    included: tuple[str, ...] = ()


def price(decision: Decision, facts: PriceFacts, rate_card: RateCard) -> PricedQuote:
    if decision.outcome == Outcome.FIXED_OFFER and decision.confidence_band == ConfidenceBand.LOW:
        raise PolicyViolation(code="policy.violation", sentence=_LOW)
    if decision.outcome == Outcome.ESCALATION:
        return _empty()
    if decision.outcome == Outcome.SITE_ASSESSMENT:
        return _empty(site_visit_fee=rate_card.site_visit_fee)
    composed = _composed(facts, rate_card)
    if decision.outcome == Outcome.INDICATIVE_RANGE:
        return _range(facts, composed, rate_card)
    lines = tuple(_line(rate_card, requested) for requested in composed.items)
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
            if item.role == role and item.item_code not in seen and _selected(item, facts):
                chosen.append(RequestedItem(item_code=item.item_code, quantity=_quantity(item, facts, Decimal("1"))))
                seen.add(item.item_code)
    return facts.model_copy(update={"items": tuple(chosen)})


def _selected(item: RateCardItem, facts: PriceFacts) -> bool:
    """A non-product row joins the quote when the role, the work, the job, and the condition agree."""
    if item.job_types and facts.job_type not in item.job_types:
        return False
    if not _applies(item, facts.work):
        return False
    return _when_holds(item.when, facts.values)


def _when_holds(condition: When | None, values: dict[str, str]) -> bool:
    if condition is None:
        return True
    named = _mentioned(condition)
    missing: list[str] = []
    unknown: list[str] = []
    text: dict[str, str] = {}
    numbers: dict[str, Decimal] = {}
    for key in named:
        raw = values.get(key)
        if raw is None or str(raw).strip() == "":
            missing.append(key)
            continue
        if str(raw).strip().casefold() == "unknown":
            unknown.append(key)
            continue
        canon = _yes_no(str(raw).strip())
        text[key] = canon
        try:
            numbers[key] = Decimal(canon)
        except InvalidOperation:
            pass
    view = FactView(values=text, numbers=numbers, missing=tuple(missing), unknown=tuple(unknown))
    return matches(_canon_when(condition), view)


def _mentioned(condition: When) -> tuple[str, ...]:
    names = [condition.fact] if condition.fact else []
    for part in condition.of:
        names.extend(_mentioned(part))
    return tuple(dict.fromkeys(names))


def _canon_when(condition: When) -> When:
    return When(
        op=condition.op,
        fact=condition.fact,
        value=_yes_no(condition.value) if condition.value else "",
        values=tuple(_yes_no(item) for item in condition.values),
        of=tuple(_canon_when(part) for part in condition.of),
    )


def _yes_no(value: str) -> str:
    folded = value.strip().casefold()
    if folded in ("yes", "true", "y"):
        return "true"
    if folded in ("no", "false", "n"):
        return "false"
    return value.strip()


def _applies(item: RateCardItem, work: WorkKind | None) -> bool:
    if item.applies_to == "both":
        return True
    return work is not None and item.applies_to == work


def _range(requested: PriceFacts, composed: PriceFacts, rate_card: RateCard) -> PricedQuote:
    """The product span, with infrastructure added to both ends."""
    chosen = {item.item_code for item in requested.items}
    products = tuple(item for item in composed.items if item.item_code in chosen)
    shared = tuple(item for item in composed.items if item.item_code not in chosen)
    if not products:
        return _empty()
    priced = tuple(_extended(rate_card, item) for item in products)
    low = min(priced, key=lambda amount: amount.amount)
    high = max(priced, key=lambda amount: amount.amount)
    extra = _sum(rate_card, shared)
    if extra is not None:
        low = low + extra
        high = high + extra
    included = tuple(_item(rate_card, item.item_code).description for item in shared)
    return _empty(price_type="range", range_min=low, range_max=high, included=included)


def _sum(rate_card: RateCard, items: tuple[RequestedItem, ...]) -> Money | None:
    total: Money | None = None
    for requested in items:
        amount = _extended(rate_card, requested)
        total = amount if total is None else total + amount
    return total


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
    included: tuple[str, ...] = (),
) -> PricedQuote:
    return PricedQuote(
        price_type=price_type,
        lines=lines,
        range_min=range_min,
        range_max=range_max,
        site_visit_fee=site_visit_fee,
        deposit=None,
        discount_percent=Decimal("0"),
        included=included,
    )
