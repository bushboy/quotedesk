"""The owner's console: who wrote in, which quotes went out, what waits for approval, and the policy.

The page shows what `ListPending`, `ApproveException`, `RejectException`, and `PublishPolicy` return,
plus read-only lists of stored messages and quotes. It never computes a price, a version,
or whether an ask or a draft is allowed.
"""

import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qs
from uuid import UUID, uuid4

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape

from quotedesk.application.dto.tenant import TenantContext
from quotedesk.application.dto.tool_inputs import ApproveExceptionInput, RejectExceptionInput
from quotedesk.application.dto.tool_outputs import ApproveResult
from quotedesk.application.errors import ApplicationError
from quotedesk.domain.quotes.quote import QuoteState
from quotedesk.domain.services.validate_policy import validate_policy
from quotedesk.domain.shared.errors import DomainError
from quotedesk.domain.shared.ids import PolicyVersionId, QuoteId
from quotedesk.domain.shared.money import Money

router = APIRouter()

_TEMPLATES = Path(__file__).resolve().parent / "templates"
_APPROVAL_DAYS = timedelta(days=7)
_VERSION = re.compile(r"\d{1,9}")
_BAD_VERSION = "That version is not a number."
_ACTIONS = ("approved", "rejected")
_MAX_FORM = 32768
_SAST = timezone(timedelta(hours=2))
_SNIPPET = 80
_SENT_SNIPPET = 160
_LIST_LIMIT = 20
_KINDS = {"image": "Photo", "audio": "Voice note", "video": "Video"}


def owner_templates() -> Environment:
    environment = Environment(loader=FileSystemLoader(_TEMPLATES), autoescape=select_autoescape(["html"]))
    environment.filters["rand"] = rand
    environment.filters["percent"] = percent
    environment.filters["state"] = state_label
    environment.filters["when"] = when
    return environment


def rand(money: Money) -> str:
    return "R " + f"{money.amount:,.2f}".replace(",", " ")


def percent(value: Decimal | int) -> str:
    if isinstance(value, int):
        return str(value)
    return f"{value.normalize():f}"


def state_label(state) -> str:
    return state.value.replace("_", " ").capitalize()


def when(at: datetime | None) -> str:
    if at is None:
        return ""
    local = at.astimezone(_SAST) if at.tzinfo is not None else at
    return f"{local.day} {local:%b %H:%M}"


def total(lines) -> Money:
    amount = Money("0")
    for line in lines:
        amount = amount + line.total
    return amount


def quote_amount(version) -> str:
    """The figure on the activity row. A range quote has no line items."""
    if version.lines:
        return rand(total(version.lines))
    low = version.range_min
    high = version.range_max
    if low is not None and high is not None:
        if low == high:
            return rand(low)
        return f"{rand(low)} to {rand(high)}"
    if low is not None:
        return rand(low)
    if high is not None:
        return rand(high)
    if version.site_visit_fee is not None:
        return rand(version.site_visit_fee)
    return rand(Money("0"))


async def read_form(request: Request) -> dict[str, str]:
    body = (await request.body())[:_MAX_FORM].decode("utf-8", errors="replace")
    return {key: values[0] for key, values in parse_qs(body, keep_blank_values=True).items()}


def _context(request: Request) -> TenantContext:
    return TenantContext(tenant_id=request.app.state.tenant_id)


@router.get("/console", response_class=HTMLResponse)
def console(request: Request, done: str = "", action: str = "", published: str = "") -> HTMLResponse:
    result = None
    if done and action in _ACTIONS:
        result = request.app.state.unit.find_operator_result(request.app.state.tenant_id, done)
    return owner_page(
        request,
        result=result,
        action=action if result is not None else "",
        policy=policy_view(request, published=published),
    )


@router.post("/console/approve", response_model=None)
async def approve(request: Request) -> HTMLResponse | RedirectResponse:
    return _decide(request, await read_form(request), "approved")


@router.post("/console/reject", response_model=None)
async def reject(request: Request) -> HTMLResponse | RedirectResponse:
    return _decide(request, await read_form(request), "rejected")


@router.post("/console/release", response_model=None)
async def release(request: Request) -> RedirectResponse:
    form = await read_form(request)
    raw = form.get("conversation_id", "").strip()
    try:
        conversation_id = UUID(raw)
    except ValueError:
        return RedirectResponse("/console#handovers", status_code=303)
    store = request.app.state.conversations
    release_hold = getattr(store, "release_escalation", None)
    if release_hold is not None:
        release_hold(request.app.state.tenant_id, conversation_id)
    return RedirectResponse("/console#handovers", status_code=303)


def _decide(request: Request, form: dict[str, str], action: str) -> HTMLResponse | RedirectResponse:
    state = request.app.state
    key = str(uuid4())
    try:
        quote_id = QuoteId(form.get("quote_id", "").strip())
        version = form.get("version", "").strip()
        if _VERSION.fullmatch(version) is None:
            return owner_page(request, error=_BAD_VERSION, status_code=400)
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
        return owner_page(request, error=error.sentence, status_code=409)
    return RedirectResponse(f"/console?done={key}&action={action}#approvals", status_code=303)


def contacts(state) -> list[dict]:
    """One row per customer number, newest first, from the messages the app has stored."""
    rows: dict[str, dict] = {}
    for message in _heard(state):
        row = rows.setdefault(message.wa_id, {"wa_id": message.wa_id, "count": 0, "at": None, "last": ""})
        row["count"] += 1
        if row["at"] is None or message.at >= row["at"]:
            row["at"] = message.at
            row["last"] = _snippet(message)
    named = getattr(state.conversations, "name", None)
    for row in rows.values():
        row["name"] = None if named is None else named(state.tenant_id, row["wa_id"])
        row["number"] = f"+{row['wa_id']}" if str(row["wa_id"]).isdigit() else row["wa_id"]
    return sorted(rows.values(), key=lambda row: row["at"], reverse=True)[:_LIST_LIMIT]


def _heard(state):
    store = state.conversations
    heard = getattr(store, "heard", None)
    if heard is not None:
        return heard(state.tenant_id)
    return tuple(
        message
        for tenant, message in getattr(store, "remembered", ())
        if tenant == state.tenant_id
    )


def _quote_threads(state) -> tuple:
    listed = getattr(state.unit, "list_quote_threads", None)
    if listed is not None:
        return listed(state.tenant_id)
    return tuple(
        (conversation_id, quote)
        for (tenant, conversation_id), quote in getattr(state.unit, "committed", {}).items()
        if tenant == state.tenant_id
    )


def _contact_label(state, conversation_id) -> str:
    store = state.conversations
    sender = getattr(store, "sender_for", None)
    if sender is None:
        return ""
    wa_id = sender(state.tenant_id, conversation_id)
    if not wa_id:
        return ""
    number = f"+{wa_id}" if str(wa_id).isdigit() else wa_id
    named = getattr(store, "name", None)
    name = None if named is None else named(state.tenant_id, wa_id)
    if name:
        return f"{name} · {number}"
    return number


def _sent_line(state, conversation_id, quote_id: str) -> str:
    """The message that carried this quote. Later notes, such as a deposit link, stay off this row."""
    replies = getattr(state.conversations, "replies", None)
    if replies is None:
        return ""
    card = f"/card/{quote_id}"
    chosen = ""
    for _at, body in replies(state.tenant_id, conversation_id):
        text = (body or "").strip()
        if card in text:
            chosen = text
            break
        if quote_id in text:
            chosen = text
    if len(chosen) <= _SENT_SNIPPET:
        return chosen
    return chosen[: _SENT_SNIPPET - 1].rstrip() + "…"


def _snippet(message) -> str:
    text = (message.body or message.transcript or "").strip()
    label = _KINDS.get(message.kind)
    if label and text:
        text = f"{label}: {text}"
    elif label:
        text = label
    return text if len(text) <= _SNIPPET else text[: _SNIPPET - 1].rstrip() + "…"


def sent_quotes(state) -> list[dict]:
    """Every stored quote past draft, newest first, with the contact it was sent to."""
    rows = []
    for conversation_id, quote in _quote_threads(state):
        current = quote.current
        if current.state is QuoteState.DRAFT:
            continue
        rows.append(
            {
                "quote_id": quote.quote_id.value,
                "version": current.number,
                "state": current.state,
                "total": total(current.lines),
                "amount": quote_amount(current),
                "deposit": None if current.deposit is None else rand(current.deposit),
                "at": current.at,
                "contact": _contact_label(state, conversation_id),
                "sent": _sent_line(state, conversation_id, quote.quote_id.value),
            }
        )
    floor = datetime.min.replace(tzinfo=timezone.utc)
    rows.sort(key=lambda row: row["at"] or floor, reverse=True)
    return rows[:_LIST_LIMIT]


def policy_view(
    request: Request,
    deposit: str | None = None,
    reason: str = "",
    errors: tuple[str, ...] | None = None,
    refusal: str | None = None,
    published: str = "",
    rows: list[dict] | None = None,
) -> dict:
    state = request.app.state
    draft = state.policies.draft(state.tenant_id)
    if deposit is None:
        deposit = str(draft.deposit_percent) if draft is not None else ""
    if errors is None:
        errors = policy_sentences(draft)
    if rows is None:
        rows = draft_rows(draft)
    store = getattr(state, "rate_cards", None)
    return {
        "bundle": state.policies.published(state.tenant_id),
        "draft": draft,
        "deposit": deposit,
        "reason": reason,
        "errors": errors,
        "refusal": refusal,
        "published": _published_version(request, published),
        "names": _item_names(state),
        "rows": [*rows, {"code": "", "name": "", "price": "", "remove": False, "blank": True}],
        "deposit_invalid": any("deposit" in sentence.lower() for sentence in errors),
        "storage": None if store is None else store.reachable,
        "ready": not errors and draft is not None and reason.strip() != "",
    }


def draft_rows(draft) -> list[dict]:
    if draft is None:
        return []
    return [
        {"code": row.item_code, "name": row.description, "price": f"{row.unit_price:.2f}", "remove": False}
        for row in draft.rate_rows
    ]


def policy_sentences(draft) -> tuple[str, ...]:
    if draft is None:
        return ()
    return tuple(error.sentence for error in validate_policy(draft))


def _published_version(request: Request, value: str) -> str | None:
    if not value:
        return None
    try:
        version = PolicyVersionId(value)
    except DomainError:
        return None
    if request.app.state.policies.get(request.app.state.tenant_id, version) is None:
        return None
    return version.value


def _item_names(state) -> dict[str, str]:
    """Item descriptions from every kept version, since a published draft only carries item codes."""
    names: dict[str, str] = {}
    for bundle in getattr(state.policies, "versions", {}).values():
        for item in bundle.rate_card.items:
            if item.description != item.item_code:
                names.setdefault(item.item_code, item.description)
    return names


def owner_page(
    request: Request,
    result: ApproveResult | None = None,
    action: str = "",
    error: str | None = None,
    policy: dict | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    state = request.app.state
    rows = state.list_pending.execute(_context(request))
    log = getattr(state, "handovers", None)
    handovers = () if log is None else log.list(state.tenant_id)
    html = owner_templates().get_template("console.html").render(
        contacts=contacts(state),
        quotes=sent_quotes(state),
        rows=rows,
        handovers=handovers,
        result=result,
        result_total=total(result.lines) if result is not None else None,
        action=action,
        error=error,
        policy=policy if policy is not None else policy_view(request),
    )
    return HTMLResponse(html, status_code=status_code, headers={"Cache-Control": "no-store"})
