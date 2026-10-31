"""The sheeting a customer named, as one rate-card item."""

from quotedesk.domain.policy.playbook import FactOption

_UNSURE = frozenset(
    {
        "unknown",
        "not sure",
        "no idea",
        "i don't know",
        "i dont know",
        "don't know",
        "dont know",
    }
)


class SheetChoice:
    def __init__(self, code: str, label: str, value: str) -> None:
        self.code = code
        self.label = label
        self.value = value


def sheet_choice(
    raw: str,
    options: tuple[FactOption, ...] = (),
    descriptions: tuple[tuple[str, str], ...] = (),
) -> SheetChoice | None:
    """The rate-card item named by a sheet code, a finish, or a card description."""
    pieces = [piece.strip() for piece in raw.split(",") if piece.strip()]
    if len(pieces) != 1:
        return None
    named = " ".join(pieces[0].casefold().split())
    if named in _UNSURE:
        return None
    for option in options:
        names = {option.value.strip().casefold(), option.label.strip().casefold()}
        names.update(code.strip().casefold() for code in option.item_codes)
        names.discard("")
        if named in names:
            code = option.item_codes[0] if option.item_codes else option.value
            return SheetChoice(code=code, label=option.label or code, value=option.value or code)
    for code, description in descriptions:
        if named in {code.strip().casefold(), description.strip().casefold()} and code.strip():
            return SheetChoice(code=code.strip(), label=description.strip() or code.strip(), value=code.strip())
    return None


def chosen_sheet(
    values: dict[str, str],
    options: tuple[FactOption, ...] = (),
    descriptions: tuple[tuple[str, str], ...] = (),
) -> SheetChoice | None:
    for key in ("sheet", "finish", "item_codes"):
        found = sheet_choice(values.get(key) or "", options, descriptions)
        if found is not None:
            return found
    return None
