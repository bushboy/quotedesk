"""The owner's console: discount asks waiting for a decision.

The page shows what `ListPending`, `ApproveException`, and `RejectException` return.
It never computes a price, a version, or whether an ask is allowed.
"""

import re
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qs
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape

from quotedesk.application.dto.tenant import TenantContext
from quotedesk.application.dto.tool_inputs import ApproveExceptionInput, RejectExceptionInput
from quotedesk.application.dto.tool_outputs import ApproveResult
from quotedesk.application.errors import ApplicationError
from quotedesk.domain.shared.errors import DomainError
from quotedesk.domain.shared.ids import QuoteId
from quotedesk.domain.shared.money import Money

router = APIRouter()

_TEMPLATES = Path(__file__).resolve().parent / "templates"
_APPROVAL_DAYS = timedelta(days=7)
_VERSION = re.compile(r"\d{1,9}")
_BAD_VERSION = "That version is not a number."
_ACTIONS = ("approved", "rejected")
_MAX_FORM = 4096


def owner_templates() -> Environment:
    environment = Environment(loader=FileSystemLoader(_TEMPLATES), autoescape=select_autoescape(["html"]))
    environment.filters["rand"] = rand
    environment.filters["percent"] = percent
    environment.filters["state"] = state_label
    return environment


def rand(money: Money) -> str:
    return "R " + f"{money.amount:,.2f}".replace(",", " ")


def percent(value: Decimal | int) -> str:
    if isinstance(value, int):
        return str(value)
    return f"{value.normalize():f}"


def state_label(state) -> str:
    return state.value.replace("_", " ").capitalize()


def total(lines) -> Money:
    amount = Money("0")
    for line in lines:
        amount = amount + line.total
    return amount


async def read_form(request: Request) -> dict[str, str]:
    body = (await request.body())[:_MAX_FORM].decode("utf-8", errors="replace")
    return {key: values[0] for key, values in parse_qs(body, keep_blank_values=True).items()}


def _context(request: Request) -> TenantContext:
    return TenantContext(tenant_id=request.app.state.tenant_id)


@router.get("/console", response_class=HTMLResponse)
def console(request: Request, done: str = "", action: str = "") -> HTMLResponse:
    result = None
    if done and action in _ACTIONS:
        result = request.app.state.unit.find_operator_result(request.app.state.tenant_id, done)
    return _page(request, result=result, action=action if result is not None else "")


@router.post("/console/approve", response_model=None)
async def approve(request: Request) -> HTMLResponse | RedirectResponse:
    return _decide(request, await read_form(request), "approved")


@router.post("/console/reject", response_model=None)
async def reject(request: Request) -> HTMLResponse | RedirectResponse:
    return _decide(request, await read_form(request), "rejected")


def _decide(request: Request, form: dict[str, str], action: str) -> HTMLResponse | RedirectResponse:
    state = request.app.state
    key = str(uuid4())
    try:
        quote_id = QuoteId(form.get("quote_id", "").strip())
        version = form.get("version", "").strip()
        if _VERSION.fullmatch(version) is None:
            return _page(request, error=_BAD_VERSION, status_code=400)
        if action == "approved":
            state.approve.execute(
                _context(request),
                ApproveExceptionInput(
                    quote_id=quote_id,
                    version=int(version),
                    idempotency_key=key,
                    expires_at=state.clock.now() + _APPROVAL_DAYS,
                ),
            )
        else:
            state.reject.execute(
                _context(request),
                RejectExceptionInput(quote_id=quote_id, version=int(version), idempotency_key=key),
            )
    except (DomainError, ApplicationError) as error:
        return _page(request, error=error.sentence, status_code=409)
    return RedirectResponse(f"/console?done={key}&action={action}", status_code=303)


def _page(
    request: Request,
    result: ApproveResult | None = None,
    action: str = "",
    error: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    rows = request.app.state.list_pending.execute(_context(request))
    html = owner_templates().get_template("console.html").render(
        page="console",
        rows=rows,
        result=result,
        result_total=total(result.lines) if result is not None else None,
        action=action,
        error=error,
    )
    return HTMLResponse(html, status_code=status_code, headers={"Cache-Control": "no-store"})
