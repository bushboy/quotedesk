"""A condition over typed facts. One function evaluates every rule."""

from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, ConfigDict

_OPS = ("all", "any", "equals", "in", "greater_than", "is_missing", "is_unknown")


class When(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    op: str
    fact: str = ""
    value: str = ""
    values: tuple[str, ...] = ()
    of: tuple["When", ...] = ()

    def model_post_init(self, _context: object) -> None:
        if self.op not in _OPS:
            raise ValueError(f"A condition operator is one of {', '.join(_OPS)}.")


class FactView(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    values: dict[str, str] = {}
    numbers: dict[str, Decimal] = {}
    missing: tuple[str, ...] = ()
    unknown: tuple[str, ...] = ()


def matches(condition: When, facts: FactView) -> bool:
    """True when the facts satisfy the condition. Unknown operators do not match."""
    if condition.op == "all":
        return all(matches(part, facts) for part in condition.of)
    if condition.op == "any":
        return any(matches(part, facts) for part in condition.of)
    if condition.op == "is_missing":
        return condition.fact in facts.missing
    if condition.op == "is_unknown":
        return condition.fact in facts.unknown
    if condition.fact in facts.missing or condition.fact in facts.unknown:
        return False
    if condition.op == "equals":
        return _equals(facts, condition.fact, condition.value)
    if condition.op == "in":
        return any(_equals(facts, condition.fact, value) for value in condition.values)
    if condition.op == "greater_than":
        return _greater(facts, condition.fact, condition.value)
    return False


def eq(fact: str, value: str) -> When:
    return When(op="equals", fact=fact, value=value)


def one_of(fact: str, values: tuple[str, ...]) -> When:
    return When(op="in", fact=fact, values=values)


def missing(fact: str) -> When:
    return When(op="is_missing", fact=fact)


def unknown(fact: str) -> When:
    return When(op="is_unknown", fact=fact)


def above(fact: str, value: str) -> When:
    return When(op="greater_than", fact=fact, value=value)


def all_of(*parts: When) -> When:
    return When(op="all", of=parts)


def any_of(*parts: When) -> When:
    return When(op="any", of=parts)


def summarise(condition: When | None) -> str:
    """A short reading of a condition, for the rate-card editor."""
    if condition is None:
        return ""
    if condition.op == "equals":
        return f"{condition.fact} is {condition.value}"
    if condition.op == "in":
        return f"{condition.fact} is one of {', '.join(condition.values)}"
    if condition.op == "greater_than":
        return f"{condition.fact} is greater than {condition.value}"
    if condition.op == "is_missing":
        return f"{condition.fact} is missing"
    if condition.op == "is_unknown":
        return f"{condition.fact} is unknown"
    if condition.op == "all":
        return "; ".join(part for part in (summarise(item) for item in condition.of) if part)
    if condition.op == "any":
        return " or ".join(part for part in (summarise(item) for item in condition.of) if part)
    return ""


def published_when(rule_id: str) -> When | None:
    """The condition the current AquaSure and FrameWorks rules already mean."""
    return _PUBLISHED.get(rule_id)


def _equals(facts: FactView, fact: str, value: str) -> bool:
    if fact in facts.numbers:
        try:
            return facts.numbers[fact] == Decimal(value)
        except InvalidOperation:
            return False
    return facts.values.get(fact) == value


def _greater(facts: FactView, fact: str, value: str) -> bool:
    left = facts.numbers.get(fact)
    if left is None:
        return False
    if value.startswith("fact:"):
        right = facts.numbers.get(value.removeprefix("fact:"))
    else:
        try:
            right = Decimal(value)
        except InvalidOperation:
            return False
    if right is None:
        return False
    return left > right


_INJECTION = eq("injection", "true")
_LOW = eq("confidence", "low")
_READY = one_of("confidence", ("medium", "high"))
_NOT_SIMPLE = eq("simple_swap", "false")
_SIMPLE_OR_UNSAID = any_of(missing("simple_swap"), eq("simple_swap", "true"))
_SIZED = all_of(
    eq("size_known", "true"),
    one_of("job", ("replacement", "new_system")),
    _SIMPLE_OR_UNSAID,
)
_NEW_TANK = all_of(
    eq("job", "new_system"),
    one_of("size_litres", ("2500", "5000", "10000")),
)
_PUMP = all_of(eq("job", "pump"), one_of("pump", ("PUMP-STD", "PUMP-PRESSURE")))
_FIXED = all_of(
    _SIMPLE_OR_UNSAID,
    eq("confidence", "high"),
    eq("job", "replacement"),
    eq("size_known", "true"),
    eq("size_source", "customer_stated"),
    eq("existing_level_base", "true"),
    eq("items_chosen", "true"),
    eq("rate_card_match", "true"),
)
_NOT_FIXED = any_of(
    _NOT_SIMPLE,
    one_of("confidence", ("low", "medium")),
    one_of("job", ("new_system", "borehole", "unknown")),
    eq("size_known", "false"),
    missing("size_source"),
    one_of("size_source", ("photo_inferred", "reference_object")),
    eq("existing_level_base", "false"),
    eq("items_chosen", "false"),
    eq("rate_card_match", "false"),
)
_NOT_SIZED = any_of(
    eq("size_known", "false"),
    one_of("job", ("borehole", "unknown")),
    _NOT_SIMPLE,
)
_DAMAGED = any_of(
    eq("installation_damaged", "true"),
    one_of("stand_condition", ("leaning", "cracked", "sagging")),
    eq("structure_damage", "true"),
    eq("stand_hazard_mentioned", "true"),
)

_PUBLISHED = {
    "WATER-E01": _INJECTION,
    "WATER-E02": all_of(_DAMAGED, _NOT_FIXED, _NOT_SIZED),
    "WATER-E03": any_of(eq("exposed_wiring", "true"), eq("active_flooding", "true")),
    "WATER-S01": eq("job", "borehole"),
    "WATER-S02": any_of(
        all_of(eq("elevated", "true"), eq("structure_damage", "false")),
        eq("sloped_ground", "true"),
        eq("pipe_run_unknown", "true"),
    ),
    "WATER-F01": _FIXED,
    "WATER-F02": _NEW_TANK,
    "WATER-F03": _PUMP,
    "WATER-R01": all_of(_READY, eq("new_tank_and_pump", "true"), eq("base_unconfirmed", "true")),
    "WATER-R02": _SIZED,
    "WATER-L01": _LOW,
    "WATER-L02": _READY,
    "FAB-E01": _INJECTION,
    "FAB-E02": any_of(eq("lintel_cracked", "true"), eq("glass_broken", "true")),
    "FAB-E03": eq("possible_asbestos", "true"),
    "FAB-S01": eq("opening", "widened"),
    "FAB-S02": any_of(eq("above_ground_floor", "true"), eq("multi_unit", "true")),
    "FAB-F01": all_of(
        eq("confidence", "high"),
        eq("opening", "existing"),
        eq("width_known", "true"),
        eq("length_known", "true"),
        one_of("size_source", ("customer_stated", "reference_object")),
        eq("standard_band", "true"),
        eq("finish_chosen", "true"),
    ),
    "FAB-F02": all_of(
        _READY,
        eq("width_known", "true"),
        eq("length_known", "true"),
        any_of(eq("items_chosen", "true"), eq("finish_chosen", "true")),
    ),
    "FAB-R01": all_of(
        _READY,
        eq("width_m", "6.0"),
        eq("length_m", "7.0"),
        missing("finish"),
        eq("items_chosen", "false"),
    ),
    "FAB-R02": all_of(
        _READY,
        eq("width_known", "true"),
        eq("length_known", "true"),
        missing("finish"),
        eq("items_chosen", "false"),
    ),
    "FAB-B01": all_of(eq("budget_known", "true"), eq("range_known", "true"), above("range_minimum", "fact:budget")),
    "FAB-L01": _LOW,
    "FAB-L02": _READY,
}
