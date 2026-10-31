"""Policy posts for the owner console: the deposit percent, the rate card rows, one reason, one publish.

The draft is checked by `validate_policy` and published by `PublishPolicy`.
The form lives on the console page; this module never writes the published bundle itself.
"""

import json
import re
from decimal import Decimal
from urllib.parse import quote
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from quotedesk.adapters.inbound.http.console import owner_page, policy_sentences, policy_view, read_form
from quotedesk.application.dto.tenant import TenantContext
from quotedesk.application.dto.tool_inputs import PublishInput
from quotedesk.application.errors import ApplicationError
from quotedesk.domain.policy.draft import DraftRateRow
from quotedesk.domain.services.decide import parse_when
from quotedesk.domain.shared.errors import DomainError

router = APIRouter()

_WHOLE = re.compile(r"-?\d{1,6}")
_NOT_A_NUMBER = "Type the deposit as a whole number, like 30."
_ROW = re.compile(r"(code|name|price|remove|unit|role|applies-to|job-types|when)-(\d{1,3})")
_UNITS = {"each", "per m²", "per metre"}
_ROLES = {"product", "frame", "hardware", "installation", "delivery", "inspection"}
_APPLIES = {"both", "swap", "new"}
_CODE = re.compile(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*")
_PRICE = re.compile(r"\d{1,9}(?:\.\d{1,2})?")
_NO_CODE = "Each priced item needs a code, like TANK-5000."
_BAD_CODE = "An item code is letters and numbers joined by dashes, like TANK-5000."
_BAD_PRICE = "Type each price in rand, like 4250.00."
_BAD_APPLIES = "Say whether a row applies to both, a swap, or a new installation."


@router.get("/editor")
def editor(published: str = "") -> RedirectResponse:
    query = f"?published={quote(published)}" if published else ""
    return RedirectResponse(f"/console{query}#policy", status_code=303)


@router.post("/editor/draft", response_model=None)
async def check(request: Request) -> HTMLResponse | JSONResponse:
    form = await read_form(request)
    errors, rows = _store(request, form)
    if "application/json" in request.headers.get("accept", ""):
        return JSONResponse({"errors": list(errors)}, headers={"Cache-Control": "no-store"})
    view = policy_view(request, deposit=form.get("deposit", "").strip(), reason=form.get("reason", ""), errors=errors, rows=rows)
    return owner_page(request, policy=view)


@router.post("/editor/publish", response_model=None)
async def publish(request: Request) -> HTMLResponse | RedirectResponse:
    form = await read_form(request)
    deposit = form.get("deposit", "").strip()
    reason = form.get("reason", "")
    errors, rows = _store(request, form)
    if errors:
        view = policy_view(request, deposit=deposit, reason=reason, errors=errors, rows=rows)
        return owner_page(request, policy=view, status_code=422)
    try:
        version = request.app.state.publish.execute(
            TenantContext(tenant_id=request.app.state.tenant_id),
            PublishInput(reason=reason.strip(), idempotency_key=str(uuid4())),
        )
    except (DomainError, ApplicationError) as error:
        view = policy_view(request, deposit=deposit, reason=reason, errors=(), refusal=error.sentence)
        return owner_page(request, policy=view, status_code=422)
    return RedirectResponse(f"/console?published={version.value}#policy", status_code=303)


def _store(request: Request, form: dict[str, str]) -> tuple[tuple[str, ...], list[dict] | None]:
    """Put the typed percent and rate rows on the draft and return what `validate_policy` says about it.

    A post without rate rows keeps the draft's rows. When a typed value cannot be read,
    the draft is left alone and the typed rows come back so the page can show them again.
    """
    deposit = form.get("deposit", "").strip()
    typed = _typed_rows(form)
    problems: list[str] = []
    if _WHOLE.fullmatch(deposit) is None:
        problems.append(_NOT_A_NUMBER)
    state = request.app.state
    draft = state.policies.draft(state.tenant_id)
    if draft is None:
        return tuple(problems), typed
    update: dict = {}
    if typed is not None:
        rate_rows, row_problems = _rate_rows(typed, draft.vat_inclusive)
        problems.extend(row_problems)
        update["rate_rows"] = rate_rows
    if problems:
        return tuple(problems), typed
    update["deposit_percent"] = int(deposit)
    draft = draft.model_copy(update=update)
    state.policies.save_draft(state.tenant_id, draft)
    return policy_sentences(draft), None


def _typed_rows(form: dict[str, str]) -> list[dict] | None:
    indexes = sorted({int(match.group(2)) for key in form if (match := _ROW.fullmatch(key)) is not None})
    if not indexes:
        return None
    return [
        {
            "code": form.get(f"code-{index}", "").strip(),
            "name": form.get(f"name-{index}", "").strip(),
            "price": form.get(f"price-{index}", "").strip(),
            "remove": f"remove-{index}" in form,
            "unit": form.get(f"unit-{index}", "").strip(),
            "role": form.get(f"role-{index}", "").strip(),
            "applies_to": form.get(f"applies-to-{index}", "").strip(),
            "job_types": form.get(f"job-types-{index}", "").strip(),
            "when": form.get(f"when-{index}", "").strip(),
        }
        for index in indexes
    ]


def _rate_rows(typed: list[dict], vat_inclusive: bool) -> tuple[tuple[DraftRateRow, ...], list[str]]:
    rows: list[DraftRateRow] = []
    problems: list[str] = []
    for row in typed:
        if row["remove"] or not (row["code"] or row["name"] or row["price"]):
            continue
        price = row["price"].replace(" ", "").removeprefix("R").removeprefix("r")
        if row["code"] == "":
            problems.append(_NO_CODE)
        elif _CODE.fullmatch(row["code"]) is None:
            problems.append(_BAD_CODE)
        elif _PRICE.fullmatch(price) is None:
            problems.append(_BAD_PRICE)
        else:
            unit = row.get("unit") or "each"
            role = row.get("role") or "product"
            applies = row.get("applies_to") or "both"
            if applies not in _APPLIES:
                problems.append(_BAD_APPLIES)
                continue
            rows.append(
                DraftRateRow(
                    item_code=row["code"],
                    unit_price=Decimal(price),
                    vat_inclusive=vat_inclusive,
                    description=row["name"],
                    unit=unit if unit in _UNITS else "each",
                    role=role if role in _ROLES else "product",
                    applies_to=applies,
                    job_types=tuple(part.strip() for part in row.get("job_types", "").split(",") if part.strip()),
                    when=_when(row.get("when", "")),
                )
            )
    return tuple(rows), list(dict.fromkeys(problems))


def _when(raw: str):
    if not raw.strip():
        return None
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parse_when(loaded)
