"""The customer's quote card. A real customer surface, not part of the chat simulator."""

import json
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
_FIXTURE = Path(__file__).resolve().parents[4] / "tests" / "fixtures" / "quote_card" / "fixed_offer.json"
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
    recorded = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    quote = request.app.state.unit.get_quote(request.app.state.tenant_id, request.app.state.conversation_id)
    if quote is not None and quote.current.lines:
        line = quote.current.lines[0]
        recorded["amount_display"] = _rand(line.total.amount)
        recorded["body"] = f"{line.description}. {recorded['body']}"
    remembered = request.app.state.quoted.last
    if remembered is not None:
        recorded["rule_id"] = remembered.rule_id.value
    recorded["expiry_display"] = f"{status.expiry.day} {status.expiry.strftime('%B')} {status.expiry.year}"
    recorded["status_line"] = (
        f"{status.state.value} · version {status.version} · {recorded['expiry_display']} · {status.schedule_status}"
    )
    recorded["evidence"] = "/media/tank-mask.png"
    recorded["headline"] = _headline(status.state.value, remembered)
    return recorded


def _headline(state: str, remembered) -> str:
    if state == "EXPIRED":
        return _EXPIRED
    if remembered is None:
        return _HEADLINES["fixed"]
    return _HEADLINES.get(remembered.price_type, _HEADLINES["fixed"])


def _rand(amount) -> str:
    return "R " + f"{amount:,.2f}".replace(",", " ")
