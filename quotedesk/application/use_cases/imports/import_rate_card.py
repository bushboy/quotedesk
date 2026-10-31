import csv
import re
from collections.abc import Callable, Mapping, Sequence
from decimal import ROUND_HALF_EVEN, Decimal
from io import BytesIO, StringIO
from pathlib import PurePath
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from quotedesk.application.dto.tenant import TenantContext
from quotedesk.application.errors import TenantRequired
from quotedesk.application.ports.runtime import UnitOfWork
from quotedesk.domain.policy.draft import DraftRateRow, PolicyDraft
from quotedesk.domain.shared.errors import PolicyViolation, ValidationError

_LIMIT = 2_000_000
_EMPTY = "That file is empty."
_OVERSIZE = "That file is too large."
_UNSUPPORTED = "That file type isn't imported yet."
_NO_DRAFT = "There is no draft to update."
_CODE = re.compile(r"^[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*$")
_CENTS = Decimal("0.01")


@runtime_checkable
class ColumnLabeller(Protocol):
    def label(self, headers: Sequence[str]) -> Mapping[str, str]: ...


class ImportedRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    item_code: str
    unit_price: Decimal | None
    unit: str
    applies_to: str = "both"
    flags: tuple[str, ...]
    status: Literal["ready", "needs_review"]
    cell: str


class ImportResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    rows: tuple[ImportedRow, ...]
    unmapped_text: tuple[str, ...]


class ImportRateCardInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    filename: str
    body: bytes
    expected_unit: str
    labeller: ColumnLabeller


class ImportRateCard:
    def __init__(self, policies, unit_of_work: UnitOfWork, reject_macros: Callable) -> None:
        self._policies = policies
        self._unit = unit_of_work
        self._reject = reject_macros

    def execute(self, context: TenantContext | None, data: ImportRateCardInput) -> ImportResult:
        if context is None:
            raise TenantRequired()

        def parse(filename: str) -> ImportResult:
            return self._import(context, data, filename)

        return self._reject(data.filename, parse)

    def _import(self, context: TenantContext, data: ImportRateCardInput, filename: str) -> ImportResult:
        if data.body == b"":
            raise ValidationError(code="import.empty", sentence=_EMPTY)
        if len(data.body) > _LIMIT:
            raise ValidationError(code="import.oversize", sentence=_OVERSIZE)
        suffix = PurePath(filename).suffix.casefold()
        if suffix == ".xlsx":
            grid = _xlsx(data.body)
        elif suffix == ".csv":
            grid = _csv(data.body)
        else:
            raise ValidationError(code="import.unsupported", sentence=_UNSUPPORTED)
        result = _interpret(grid, data.expected_unit, data.labeller)
        draft = self._policies.draft(context.tenant_id)
        if draft is None:
            raise PolicyViolation(code="policy.violation", sentence=_NO_DRAFT)
        updated = _replace_rows(draft, result.rows)
        try:
            self._policies.save_draft(context.tenant_id, updated)
            self._unit.commit()
        except Exception:
            self._unit.rollback()
            raise
        return result


def _replace_rows(draft: PolicyDraft, rows: tuple[ImportedRow, ...]) -> PolicyDraft:
    names = {row.item_code: row.description for row in draft.rate_rows}
    rate_rows = tuple(
        DraftRateRow(
            item_code=row.item_code,
            unit_price=row.unit_price,
            vat_inclusive=draft.vat_inclusive,
            description=names.get(row.item_code, ""),
            unit=row.unit or "each",
            applies_to=row.applies_to if row.applies_to in ("both", "swap", "new") else "both",
        )
        for row in rows
        if row.unit_price is not None
    )
    return draft.model_copy(update={"rate_rows": rate_rows})


def _interpret(grid: list[list[tuple[object, str]]], expected_unit: str, labeller: ColumnLabeller) -> ImportResult:
    if not grid:
        return ImportResult(rows=(), unmapped_text=())
    headers = tuple("" if value is None else str(value) for value, _coordinate in grid[0])
    labeller.label(headers)
    columns = {_header(text): index for index, text in enumerate(headers)}
    found: list[ImportedRow] = []
    unmapped: list[str] = []
    for row in grid[1:]:
        if _blank(row):
            continue
        code = _text(_value(row, columns.get("item_code")))
        if code is not None and _CODE.fullmatch(code) is not None:
            found.append(_item(row, columns, code, expected_unit))
            continue
        for value, _coordinate in row:
            if isinstance(value, str) and value != "":
                unmapped.append(value)
            elif value is not None and not isinstance(value, str):
                unmapped.append(str(value))
    counts: dict[str, int] = {}
    for row in found:
        counts[row.item_code] = counts.get(row.item_code, 0) + 1
    rows = tuple(_with_conflict(row) if counts[row.item_code] > 1 else row for row in found)
    return ImportResult(rows=rows, unmapped_text=tuple(unmapped))


def _item(
    row: list[tuple[object, str]],
    columns: dict[str, int],
    code: str,
    expected_unit: str,
) -> ImportedRow:
    price_value, price_cell = _at(row, columns.get("unit_price"))
    unit_value, _unit_cell = _at(row, columns.get("unit"))
    applies_index = columns.get("applies_to")
    if applies_index is None:
        applies_index = columns.get("applies to")
    applies_value, _applies_cell = _at(row, applies_index)
    price = _price(price_value)
    unit = _text(unit_value) or ""
    applies = (_text(applies_value) or "both").casefold()
    if applies not in ("both", "swap", "new"):
        applies = "both"
    flags: list[str] = []
    if price is None:
        flags.append("missing_price")
    if unit == "":
        flags.append("blank_unit")
    elif unit.casefold() == "each" and expected_unit.strip().casefold() == "m2":
        flags.append("unit_mismatch")
    return ImportedRow(
        item_code=code,
        unit_price=price,
        unit=unit,
        applies_to=applies,
        flags=tuple(flags),
        status="ready" if not flags else "needs_review",
        cell=price_cell,
    )


def _with_conflict(row: ImportedRow) -> ImportedRow:
    flags = row.flags if "conflict" in row.flags else row.flags + ("conflict",)
    return row.model_copy(update={"flags": flags, "status": "needs_review"})


def _xlsx(body: bytes) -> list[list[tuple[object, str]]]:
    import openpyxl

    book = openpyxl.load_workbook(BytesIO(body), data_only=True)
    try:
        sheet = book.active
        if sheet is None:
            return []
        return [[(cell.value, cell.coordinate) for cell in row] for row in sheet.iter_rows()]
    finally:
        book.close()


def _csv(body: bytes) -> list[list[tuple[object, str]]]:
    text = body.decode("utf-8-sig")
    grid: list[list[tuple[object, str]]] = []
    for row_number, row in enumerate(csv.reader(StringIO(text)), start=1):
        grid.append([(None if value == "" else value, f"{_letters(index)}{row_number}") for index, value in enumerate(row)])
    return grid


def _header(value: str) -> str:
    return value.strip().casefold()


def _blank(row: list[tuple[object, str]]) -> bool:
    return all(_text(value) is None for value, _coordinate in row)


def _text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if text == "":
        return None
    return text


def _value(row: list[tuple[object, str]], index: int | None) -> object:
    return _at(row, index)[0]


def _at(row: list[tuple[object, str]], index: int | None) -> tuple[object, str]:
    if index is None or index >= len(row):
        return None, ""
    return row[index]


def _price(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        text = value.strip()
        if text == "":
            return None
        amount = Decimal(text)
    elif isinstance(value, Decimal):
        amount = value
    elif isinstance(value, int):
        amount = Decimal(value)
    elif isinstance(value, float):
        amount = Decimal(str(value))
    else:
        return None
    return amount.quantize(_CENTS, rounding=ROUND_HALF_EVEN)


def _letters(index: int) -> str:
    number = index + 1
    letters = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters
