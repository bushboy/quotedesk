import json
import re
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, PlainTextResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape

router = APIRouter()

_FIXTURES = Path(__file__).resolve().parents[4] / "tests" / "fixtures" / "quote_card"
_TEMPLATES = Path(__file__).resolve().parent / "templates"
_STATE = re.compile(r"[a-z]+(?:-[a-z]+)*")
_MISSING = "That preview does not exist."


def _render(state: str) -> HTMLResponse | PlainTextResponse:
    if _STATE.fullmatch(state) is None:
        return PlainTextResponse(_MISSING, status_code=404)
    path = (_FIXTURES / f"{state.replace('-', '_')}.json").resolve()
    if not path.is_relative_to(_FIXTURES.resolve()) or not path.is_file():
        return PlainTextResponse(_MISSING, status_code=404)
    card = json.loads(path.read_text(encoding="utf-8"))
    environment = Environment(
        loader=FileSystemLoader(_TEMPLATES),
        autoescape=select_autoescape(["html"]),
    )
    html = environment.get_template("quote_card.html").render(card=card)
    return HTMLResponse(html)


@router.get("/dev/quote-card/{state}", response_model=None)
def preview_quote_card(state: str) -> HTMLResponse | PlainTextResponse:
    return _render(state)
