from collections.abc import Callable
from pathlib import PurePath
from typing import TypeVar

_MACRO_EXTENSIONS = {".xlsm", ".docm", ".pptm"}
T = TypeVar("T")


class MacroRejected(Exception):
    code = "import.macro"
    sentence = "Macro-enabled files aren't accepted. Save a copy without macros and send that."

    def __init__(self) -> None:
        super().__init__(self.sentence)


def reject_macros_before_parse(filename: str, parse: Callable[[str], T]) -> T:
    extension = PurePath(filename).suffix.casefold()
    if extension in _MACRO_EXTENSIONS:
        raise MacroRejected()
    return parse(filename)
