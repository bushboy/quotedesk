"""The macro gate. The rate-card import rejects a macro-enabled workbook before it parses."""

from collections.abc import Callable
from pathlib import PurePath
from typing import TypeVar

_MACRO_EXTENSIONS = {".xlsm", ".docm", ".pptm"}
T = TypeVar("T")


class MacroRejected(Exception):
    """The MacroRejected."""
    code = "import.macro"
    sentence = "Macro-enabled files aren't accepted. Save a copy without macros and send that."

    def __init__(self) -> None:
        super().__init__(self.sentence)


def reject_macros_before_parse(filename: str, parse: Callable[[str], T]) -> T:
    """Refuse a macro-enabled workbook before the parser reads it."""
    extension = PurePath(filename).suffix.casefold()
    if extension in _MACRO_EXTENSIONS:
        raise MacroRejected()
    return parse(filename)
