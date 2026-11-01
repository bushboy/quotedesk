"""Rand amounts and times written the way a person says them."""

from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

_SAST = timezone(timedelta(hours=2))
_ONES = (
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen",
)
_TENS = ("", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety")
_SCALES = ((1_000_000_000, "billion"), (1_000_000, "million"), (1_000, "thousand"))


def number_words(value: int) -> str:
    """A whole number in words, British style: 1050 is "one thousand and fifty"."""
    if value < 0:
        return "minus " + number_words(-value)
    if value < 1000:
        return _below_thousand(value, joined=False)
    parts: list[str] = []
    rest = value
    for size, name in _SCALES:
        if rest >= size:
            parts.append(f"{number_words(rest // size)} {name}")
            rest %= size
    if rest:
        parts.append(_below_thousand(rest, joined=True))
    return " ".join(parts)


def _below_thousand(value: int, *, joined: bool) -> str:
    if value < 20:
        words = _ONES[value]
        return f"and {words}" if joined and value < 100 else words
    if value < 100:
        tens, ones = divmod(value, 10)
        words = _TENS[tens] + (f"-{_ONES[ones]}" if ones else "")
        return f"and {words}" if joined else words
    hundreds, rest = divmod(value, 100)
    words = f"{_ONES[hundreds]} hundred"
    if rest:
        words += f" and {_below_thousand(rest, joined=False)}"
    return words


def rand_words(amount: Decimal) -> str:
    """R 16 650.50 is "sixteen thousand six hundred and fifty rand and fifty cents"."""
    cents_total = int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    rands, cents = divmod(abs(cents_total), 100)
    words = f"{number_words(rands)} rand"
    if cents:
        words += f" and {number_words(cents)} {'cent' if cents == 1 else 'cents'}"
    return ("minus " + words) if cents_total < 0 else words


def spoken_time(at: datetime) -> str:
    """A time of day in SAST, like 9:40."""
    local = at.astimezone(_SAST) if at.tzinfo is not None else at
    return f"{local.hour}:{local.minute:02d}"


def plural(count: int, one: str, many: str) -> str:
    return f"{count} {one if count == 1 else many}"
