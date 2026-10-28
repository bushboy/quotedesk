import re
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

from quotedesk.domain.policy.clauses import Condition
from quotedesk.domain.shared.money import Money

_CENT = Decimal("0.01")
_AMOUNT = re.compile(
    r"\bR\s*(?:\d{1,3}(?:[ ,]\d{3})+|\d+)(?:\.\d{2})?|\b\d+(?:\.\d{2})?\s*rand\b",
    re.IGNORECASE,
)
_CIVIL = re.compile(
    r"\b(\d{1,2})\s+"
    r"(January|February|March|April|May|June|July|August|September|October|November|December)"
    r"(?:\s+(\d{4}))?\b",
    re.IGNORECASE,
)
_RELATIVE = re.compile(
    r"\b(?:this|next)\s+(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b"
    r"|\btoday\b|\btomorrow\b|\bnext week\b",
    re.IGNORECASE,
)
_INCLUDES = re.compile(r"\bincludes\s+([^.]*)", re.IGNORECASE)
_GUARANTEED = re.compile(r"\bguaranteed\b", re.IGNORECASE)
_RANGE = re.compile(r"\brange\b", re.IGNORECASE)
_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}
_ALIASES = (("council plans", "municipal building plan"),)

ScheduleStatus = Literal["none", "indicative", "held", "confirmed", "escalated"]
PriceKind = Literal["fixed", "range", "none"]


class TurnFacts(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    amounts: tuple[Money, ...] = ()
    civil_dates: tuple[date, ...] = ()
    clauses: tuple[Condition, ...] = ()
    schedule_status: ScheduleStatus = "none"
    price_kind: PriceKind = "fixed"
    card_link: str | None = None


class CheckResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    ok: bool
    code: str | None = None


def check_reply(reply: str, facts: TurnFacts) -> CheckResult:
    code = (
        _amounts(reply, facts.amounts)
        or _dates(reply, facts.civil_dates)
        or _inclusions(reply, facts.clauses)
        or _guarantee(reply, facts.schedule_status)
        or _range(reply, facts.price_kind)
        or _link(reply, facts.card_link)
    )
    if code is None:
        return CheckResult(ok=True, code=None)
    return CheckResult(ok=False, code=code)


def _amounts(reply: str, amounts: tuple[Money, ...]) -> str | None:
    allowed = {item.amount for item in amounts}
    for match in _AMOUNT.finditer(reply):
        if _parse_amount(match.group(0)) not in allowed:
            return "commitment.amount"
    return None


def _parse_amount(raw: str) -> Decimal:
    text = raw.lower().replace("rand", "").replace("r", "").replace(" ", "").replace(",", "")
    return Decimal(text).quantize(_CENT, rounding=ROUND_HALF_EVEN)


def _dates(reply: str, civil_dates: tuple[date, ...]) -> str | None:
    if _RELATIVE.search(reply):
        return "commitment.date"
    for match in _CIVIL.finditer(reply):
        day = int(match.group(1))
        month = _MONTHS[match.group(2).lower()]
        year = int(match.group(3)) if match.group(3) else None
        if not any(
            item.day == day and item.month == month and (year is None or item.year == year)
            for item in civil_dates
        ):
            return "commitment.date"
    return None


def _inclusions(reply: str, clauses: tuple[Condition, ...]) -> str | None:
    for match in _INCLUDES.finditer(reply):
        phrase = " ".join(match.group(1).strip().rstrip(".").split()).lower()
        if phrase == "":
            continue
        if _excluded(phrase, clauses) or not _included(phrase, clauses):
            return "commitment.inclusion"
    return None


def _excluded(phrase: str, clauses: tuple[Condition, ...]) -> bool:
    for claim, marker in _ALIASES:
        if phrase != claim:
            continue
        for clause in clauses:
            if clause.kind == "exclusion" and marker in clause.text.lower():
                return True
    return False


def _included(phrase: str, clauses: tuple[Condition, ...]) -> bool:
    return any(clause.kind != "exclusion" and phrase in clause.text.lower() for clause in clauses)


def _guarantee(reply: str, status: str) -> str | None:
    if status == "escalated" and _GUARANTEED.search(reply):
        return "commitment.guarantee"
    return None


def _range(reply: str, price_kind: str) -> str | None:
    if price_kind == "range" and _RANGE.search(reply) is None:
        return "commitment.range"
    return None


def _link(reply: str, card_link: str | None) -> str | None:
    if card_link is not None and card_link not in reply:
        return "commitment.link"
    return None
