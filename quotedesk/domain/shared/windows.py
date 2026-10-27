from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict

from quotedesk.domain.shared.errors import ValidationError

_NOT_A_DATE = "A window is made of calendar dates."
_UNORDERED = "A window's end is on or after its start."


def _civil_date(value: Any) -> date:
    if type(value) is date:
        return value
    raise ValidationError(code="date_window.not_a_date", sentence=_NOT_A_DATE)


class DateWindow(BaseModel):
    model_config = ConfigDict(frozen=True)

    start: date
    end: date

    def __init__(self, **data: Any) -> None:
        start = _civil_date(data.get("start"))
        end = _civil_date(data.get("end"))
        if end < start:
            raise ValidationError(code="date_window.unordered", sentence=_UNORDERED)
        super().__init__(start=start, end=end)

    def contains(self, day: Any) -> bool:
        civil = _civil_date(day)
        return self.start <= civil <= self.end
