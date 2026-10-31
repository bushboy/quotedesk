"""The customer's quote card. It renders the stored quote, not a fixture."""

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape

from quotedesk.application.dto.tenant import TenantContext
from quotedesk.application.dto.tool_inputs import GetQuoteStatusInput
from quotedesk.domain.shared.errors import ValidationError
from quotedesk.domain.shared.ids import QuoteId

router = APIRouter()

_TEMPLATES = Path(__file__).resolve().parent / "templates"
_MISSING = "That card needs its verification code."
_HEADLINES = {"fixed": "Fixed quote", "range": "Price range", "none": "We can't price this yet"}
_EXPIRED = "This quote has expired"


@router.get("/card/{quote_id}", response_model=None)
def card(request: Request, quote_id: str, code: str = "") -> HTMLResponse | PlainTextResponse:
    recorded = _card(request, quote_id, code)
    if recorded is None:
        return PlainTextResponse(_MISSING, status_code=404)
    environment = Environment(loader=FileSystemLoader(_TEMPLATES), autoescape=select_autoescape(["html"]))
    return HTMLResponse(environment.get_template("quote_card.html").render(card=recorded))


@router.get("/card/{quote_id}/preview", response_model=None)
def preview(request: Request, quote_id: str, code: str = "") -> JSONResponse | PlainTextResponse:
    """What a messaging app needs to draw a link preview: headline, amount, one line, a thumbnail."""
    recorded = _card(request, quote_id, code)
    if recorded is None:
        return PlainTextResponse(_MISSING, status_code=404)
    return JSONResponse(
        {
            key: recorded[key]
            for key in ("headline", "business_name", "quote_id", "amount_display", "body", "expiry_display", "evidence")
        }
    )


def _card(request: Request, quote_id: str, code: str) -> dict | None:
    try:
        parsed = QuoteId(quote_id)
    except ValidationError:
        return None
    status = request.app.state.status.execute(
        TenantContext(tenant_id=request.app.state.tenant_id),
        GetQuoteStatusInput(quote_id=parsed, verification_code=code),
    )
    if not status.found or status.expiry is None or status.version is None or status.state is None:
        return None
    quote = request.app.state.quotes.get_by_id(request.app.state.tenant_id, parsed)
    if quote is None:
        return None
    current = quote.current
    tenant = request.app.state.tenant
    price_type = current.price_type or ("fixed" if current.lines else "none")
    amount = _total(current.lines)
    low = current.range_min
    high = current.range_max
    single = low is not None and (high is None or high.amount == low.amount)
    if amount is None and single:
        amount = low
    show_range = amount is None and low is not None
    expiry_display = f"{status.expiry.day} {status.expiry.strftime('%B')} {status.expiry.year}"
    headline = _EXPIRED if status.state.value == "EXPIRED" else _HEADLINES.get(price_type, _HEADLINES["none"])
    return {
        "headline": headline,
        "business_name": " ".join(part for part in (tenant.display_name, tenant.area) if part),
        "quote_id": parsed.value,
        "rule_id": None,
        "body": None,
        "lines": [
            {"description": line.description, "total_display": _rand(line.total.amount)}
            for line in current.lines
        ] if price_type == "fixed" else [],
        "shared": ", ".join(current.included) if price_type == "range" and current.included else None,
        "amount_display": None if amount is None else _rand(amount.amount),
        "range_min_display": _rand(low.amount) if show_range else None,
        "range_max_display": _rand(high.amount) if show_range and high is not None else None,
        "fee_display": None if current.site_visit_fee is None else _rand(current.site_visit_fee.amount),
        "expiry_display": expiry_display,
        "status_line": (
            f"{status.state.value} · version {status.version} · {expiry_display} · {status.schedule_status}"
        ),
        "window_display": None,
        "hold_until_display": None,
        "evidence": None,
        "clauses": [{"text": clause.text, "if_not_true": clause.if_not_true} for clause in current.clauses],
        "next_step": None if current.deposit is None else f"Deposit {_rand(current.deposit.amount)} to go ahead.",
    }


def _total(lines):
    if not lines:
        return None
    amount = lines[0].total
    for line in lines[1:]:
        amount = amount + line.total
    return amount


def _rand(amount) -> str:
    return "R " + f"{amount:,.2f}".replace(",", " ")
