"""The owner's console: Today, Inbox, Quotes, Customers, Rates & policy, and Settings.

The pages show what the operator, editor and summary use cases return, plus read-only lists of
stored messages and quotes. They never compute a price, a version, or whether an ask or a draft is allowed.
"""

import hashlib
import hmac
import json
import logging
import math
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qs, quote
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.routing import APIRoute
from jinja2 import Environment, FileSystemLoader, select_autoescape
from starlette.exceptions import HTTPException as StarletteHTTPException

from quotedesk.adapters.outbound.parsers.macros import reject_macros_before_parse
from quotedesk.application.dto.tenant import TenantContext
from quotedesk.application.dto.tool_inputs import (
    ApproveExceptionInput,
    EscalateToOwnerInput,
    RejectExceptionInput,
    RollbackInput,
)
from quotedesk.application.dto.tool_outputs import ApproveResult
from quotedesk.application.errors import ApplicationError
from quotedesk.application.use_cases.editor.rollback_policy import RollbackPolicy
from quotedesk.application.use_cases.imports.import_rate_card import ImportRateCard, ImportRateCardInput
from quotedesk.application.use_cases.operator.audit_timeline import AuditTimeline
from quotedesk.application.use_cases.operator.owner_summary import SummariseForOwner, first_sent
from quotedesk.application.use_cases.tools.escalate_to_owner import EscalateToOwner
from quotedesk.application.use_cases.tools.notify_owner import NotifyOwner
from quotedesk.domain.policy.when import summarise
from quotedesk.domain.quotes.quote import QuoteState
from quotedesk.domain.services.validate_policy import validate_policy
from quotedesk.domain.shared.errors import DomainError
from quotedesk.domain.shared.ids import PolicyVersionId, QuoteId
from quotedesk.domain.shared.money import Money

_LOG = logging.getLogger(__name__)
_TEMPLATES = Path(__file__).resolve().parent / "templates"
_APPROVAL_DAYS = timedelta(days=7)
_VERSION = re.compile(r"\d{1,9}")
_BAD_VERSION = "That version is not a number."
_ACTIONS = ("approved", "rejected")
_MAX_FORM = 32768
_SAST = timezone(timedelta(hours=2))
_SNIPPET = 80
_SENT_SNIPPET = 160
_LATEST = 6
_PAGE = 25
_KINDS = {"image": "Photo", "audio": "Voice note", "video": "Video"}
_COOKIE = "qd_owner"
_OPEN_PATHS = {"/console/login", "/console/logout"}
_PERIODS = ("today", "yesterday", "week")
_RAW_ERROR = re.compile(r"Traceback|\[SQL:|psycopg|sqlalche\.me|ProgrammingError|OperationalError|IntegrityError")
_BROKEN_BRIEF = "This brief could not be built. The details are in the app log."
_WRONG_PASSWORD = "That password is not right."
_TABS = (
    ("today", "Today", "/console"),
    ("inbox", "Inbox", "/console/inbox"),
    ("quotes", "Quotes", "/console/quotes"),
    ("customers", "Customers", "/console/customers"),
    ("policy", "Rates & policy", "/console/policy"),
    ("settings", "Settings", "/console/settings"),
)
_TONES = {
    QuoteState.ISSUED: "info",
    QuoteState.WAITING_FOR_DEPOSIT: "info",
    QuoteState.PENDING_APPROVAL: "warn",
    QuoteState.SITE_ASSESSMENT_OFFERED: "warn",
    QuoteState.ESCALATED: "warn",
    QuoteState.INSPECTION_BOOKED: "ok",
    QuoteState.DEPOSIT_PAID: "ok",
    QuoteState.BOOKING_CONFIRMED: "ok",
}
_SOURCES = {
    "customer_text": "Said",
    "voice_transcript": "Voice note",
    "photo_extraction": "Photo",
    "video_extraction": "Video",
    "owner": "Owner",
}
_ROLE_ORDER = ("product", "frame", "hardware", "installation", "delivery", "inspection")
_ROLE_LABELS = {
    "product": "Product",
    "frame": "Frame",
    "hardware": "Hardware",
    "installation": "Installation",
    "delivery": "Delivery",
    "inspection": "Inspection",
}


# Sign-in ---------------------------------------------------------------------------------------


def owner_password(state) -> str:
    settings = getattr(state, "settings", None)
    return (getattr(settings, "owner_password", "") or "").strip()


def _token(password: str) -> str:
    return hmac.new(password.encode("utf-8"), b"quotedesk-owner", hashlib.sha256).hexdigest()


def signed_in(request: Request) -> bool:
    password = owner_password(request.app.state)
    if not password:
        return True
    return hmac.compare_digest(request.cookies.get(_COOKIE, ""), _token(password))


def require_owner(request: Request) -> None:
    """Every owner route needs the owner signed in. With no OWNER_PASSWORD set, sign-in is off."""
    if request.url.path in _OPEN_PATHS or signed_in(request):
        return
    if request.method != "GET" or request.url.path == "/console/summary":
        raise HTTPException(status_code=401, detail="Sign in first.")
    target = request.url.path + (f"?{request.url.query}" if request.url.query else "")
    raise HTTPException(status_code=303, headers={"Location": f"/console/login?next={quote(target)}"})


def actor(request: Request) -> str:
    return "Owner" if owner_password(request.app.state) else "Owner (sign-in off)"


def owner_log(state) -> list[dict]:
    log = getattr(state, "owner_log", None)
    if log is None:
        log = []
        state.owner_log = log
    return log


def record_action(request: Request, action: str, detail: str = "", version: str = "") -> None:
    """Who did what on the console, newest last. Kept for the life of the process."""
    state = request.app.state
    clock = getattr(state, "clock", None)
    at = clock.now() if clock is not None else datetime.now(timezone.utc)
    log = owner_log(state)
    log.append({"at": at, "actor": actor(request), "action": action, "detail": detail, "version": version})
    del log[:-200]


class OwnerRoute(APIRoute):
    """An owner page that fails shows a plain sentence, never a stack trace or SQL."""

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def guarded(request: Request) -> Response:
            try:
                return await handler(request)
            except (StarletteHTTPException, RequestValidationError):
                raise
            except Exception:
                _LOG.exception("Owner page failed: %s %s", request.method, request.url.path)
                return error_page(request)

        return guarded


router = APIRouter(route_class=OwnerRoute, dependencies=[Depends(require_owner)])


# Formatting ------------------------------------------------------------------------------------


def _business_name(state) -> str:
    tenant = getattr(state, "tenant", None)
    name = "" if tenant is None else getattr(tenant, "display_name", "") or ""
    return name.strip()


def owner_templates() -> Environment:
    environment = Environment(loader=FileSystemLoader(_TEMPLATES), autoescape=select_autoescape(["html"]))
    environment.filters["rand"] = rand
    environment.filters["percent"] = percent
    environment.filters["state"] = state_label
    environment.filters["when"] = when
    environment.filters["day"] = day
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


def day(value: date | None) -> str:
    if value is None:
        return ""
    return f"{value.day} {value:%b %Y}"


def ago(now: datetime, at: datetime | None) -> str:
    if at is None:
        return ""
    minutes = max(0, int((now - at).total_seconds() // 60))
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes} min"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} h"
    return f"{hours // 24} d"


def total(lines) -> Money:
    amount = Money("0")
    for line in lines:
        amount = amount + line.total
    return amount


def quote_amount(version) -> str:
    """The figure on a quote row. A range quote has no line items."""
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


def clean(text: str) -> str:
    """Owner-facing text with any leaked exception replaced by a plain sentence."""
    if text and _RAW_ERROR.search(text):
        return _BROKEN_BRIEF
    return text


def _cut(text: str, limit: int = _SNIPPET) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


async def read_form(request: Request) -> dict[str, str]:
    body = (await request.body())[:_MAX_FORM].decode("utf-8", errors="replace")
    return {key: values[0] for key, values in parse_qs(body, keep_blank_values=True).items()}


def _context(request: Request) -> TenantContext:
    return TenantContext(tenant_id=request.app.state.tenant_id)


def _store_down(request: Request) -> bool:
    return getattr(request.app.state, "store_status", "postgres") == "down"


# Reads -----------------------------------------------------------------------------------------


class StateReads:
    """The stores on `app.state`, as the summary use case reads them."""

    def __init__(self, state) -> None:
        self._state = state

    def messages(self, tenant_id: UUID):
        return _heard(self._state, tenant_id)

    def quote_threads(self, tenant_id: UUID):
        return _quote_threads(self._state, tenant_id)

    def inspections(self, tenant_id: UUID):
        store = getattr(self._state, "inspections", None)
        return () if store is None else store.list(tenant_id)

    def handovers(self, tenant_id: UUID):
        log = getattr(self._state, "handovers", None)
        return () if log is None else log.list(tenant_id)

    def held(self, tenant_id: UUID, conversation_id: UUID) -> bool:
        check = getattr(self._state.conversations, "escalation_held", None)
        return True if check is None else bool(check(tenant_id, conversation_id))

    def pending(self, context: TenantContext):
        return self._state.list_pending.execute(context)


def summary(request: Request, period: str = "today"):
    state = request.app.state
    chosen = period if period in _PERIODS else "today"
    return SummariseForOwner(StateReads(state), state.clock).execute(_context(request), chosen)


def _heard(state, tenant_id: UUID | None = None):
    tenant = state.tenant_id if tenant_id is None else tenant_id
    store = state.conversations
    heard = getattr(store, "heard", None)
    if heard is not None:
        return heard(tenant)
    return tuple(message for owner, message in getattr(store, "remembered", ()) if owner == tenant)


def _quote_threads(state, tenant_id: UUID | None = None) -> tuple:
    tenant = state.tenant_id if tenant_id is None else tenant_id
    listed = getattr(state.unit, "list_quote_threads", None)
    if listed is not None:
        loaded = listed(tenant)
    else:
        loaded = tuple(
            (conversation_id, quote)
            for (owner, conversation_id), quote in getattr(state.unit, "committed", {}).items()
            if owner == tenant
        )
    return tuple((conversation_id, quote) for conversation_id, quote in loaded if quote.versions)


def _number(wa_id: str) -> str:
    return f"+{wa_id}" if str(wa_id).isdigit() else str(wa_id)


def _who(state, conversation_id) -> dict:
    store = state.conversations
    sender = getattr(store, "sender_for", None)
    wa_id = sender(state.tenant_id, conversation_id) if sender is not None else None
    if not wa_id:
        return {"wa_id": "", "number": "", "name": None, "label": ""}
    named = getattr(store, "name", None)
    name = None if named is None else named(state.tenant_id, wa_id)
    number = _number(wa_id)
    return {"wa_id": wa_id, "number": number, "name": name, "label": f"{name} · {number}" if name else number}


def _contact_label(state, conversation_id) -> str:
    return _who(state, conversation_id)["label"]


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
    return _cut(chosen, _SENT_SNIPPET)


def _snippet(message) -> str:
    text = (message.body or message.transcript or "").strip()
    label = _KINDS.get(message.kind)
    if label and text:
        text = f"{label}: {text}"
    elif label:
        text = label
    return _cut(text)


def _messages(state, conversation_id) -> tuple:
    reader = getattr(state.conversations, "messages", None)
    if reader is None:
        return ()
    try:
        return tuple(reader(state.tenant_id, conversation_id))
    except (ApplicationError, DomainError, KeyError):
        return ()


def _wants(state, conversation_id) -> str:
    for message in _messages(state, conversation_id):
        text = _snippet(message)
        if text:
            return text
    return ""


def _held(state, conversation_id) -> bool:
    check = getattr(state.conversations, "escalation_held", None)
    return False if check is None else bool(check(state.tenant_id, conversation_id))


def _why(version) -> str:
    reason = version.reasons[0] if version.reasons else ""
    if version.rule_id and reason:
        return f"{version.rule_id}: {reason}"
    return version.rule_id or reason


def _items(version) -> str:
    if version.lines:
        names = [line.description or line.item_code for line in version.lines]
        return _cut(", ".join(names), 60)
    if version.range_min is not None or version.range_max is not None:
        return "Price range"
    if version.site_visit_fee is not None:
        return "Site visit"
    return ""


def contacts(state, limit: int | None = None) -> list[dict]:
    """One row per customer number, newest first, from the messages the app has stored."""
    rows: dict[str, dict] = {}
    for message in _heard(state):
        row = rows.setdefault(message.wa_id, {"wa_id": message.wa_id, "count": 0, "at": None, "last": "", "first": None})
        row["count"] += 1
        if row["at"] is None or message.at >= row["at"]:
            row["at"] = message.at
            row["last"] = _snippet(message)
        if row["first"] is None or message.at < row["first"]:
            row["first"] = message.at
    named = getattr(state.conversations, "name", None)
    for row in rows.values():
        row["name"] = None if named is None else named(state.tenant_id, row["wa_id"])
        row["number"] = _number(row["wa_id"])
    ordered = sorted(rows.values(), key=lambda row: row["at"], reverse=True)
    return ordered if limit is None else ordered[:limit]


def quote_rows(state) -> list[dict]:
    """Every stored quote past draft, newest first, with the contact it was sent to."""
    rows = []
    for conversation_id, quote in _quote_threads(state):
        current = quote.current
        if current.state is QuoteState.DRAFT:
            continue
        who = _who(state, conversation_id)
        rows.append(
            {
                "quote_id": quote.quote_id.value,
                "conversation_id": conversation_id,
                "version": current.number,
                "state": current.state,
                "status": current.state.value.casefold(),
                "tone": _TONES.get(current.state, "muted"),
                "total": total(current.lines),
                "amount": quote_amount(current),
                "deposit": None if current.deposit is None else rand(current.deposit),
                "goods": _items(current),
                "at": current.at,
                "first": first_sent(quote) or current.at,
                "expiry": current.expiry,
                "contact": who["label"],
                "customer": who["name"] or who["number"],
                "number": who["number"],
                "sent": _sent_line(state, conversation_id, quote.quote_id.value),
                "why": _why(current),
            }
        )
    floor = datetime.min.replace(tzinfo=timezone.utc)
    rows.sort(key=lambda row: row["at"] or floor, reverse=True)
    return rows


def sent_quotes(state) -> list[dict]:
    return quote_rows(state)[:_LATEST]


def customer_rows(state) -> list[dict]:
    rows = contacts(state)
    find = getattr(state.conversations, "find", None)
    latest = {}
    for row in quote_rows(state):
        latest.setdefault(row["conversation_id"], row)
    for row in rows:
        conversation_id = find(state.tenant_id, row["wa_id"]) if find is not None else None
        row["conversation_id"] = conversation_id
        quote = latest.get(conversation_id)
        row["quote"] = quote
        if conversation_id is not None and _held(state, conversation_id):
            row["status"], row["tone"] = "Waiting for you", "warn"
        elif quote is not None:
            row["status"], row["tone"] = state_label(quote["state"]), quote["tone"]
        else:
            row["status"], row["tone"] = "Enquiry", "muted"
    return rows


def inbox_items(state, handovers, pending) -> list[dict]:
    """Callbacks, inspections and discount asks, newest first. Each row links to its case."""
    now = state.clock.now()
    threads = {quote.quote_id.value: (conversation_id, quote) for conversation_id, quote in _quote_threads(state)}
    items = []
    for note in handovers:
        held = _held(state, note.conversation_id)
        items.append(
            {
                "kind": "Call back" if held else "Handed back",
                "tone": "warn" if held else "muted",
                "waiting": held,
                "held": held,
                "at": note.at,
                "conversation_id": note.conversation_id,
                "customer": _contact_label(state, note.conversation_id) or "Customer",
                "wants": _wants(state, note.conversation_id),
                "detail": clean(note.reason),
                "amount": "",
            }
        )
    store = getattr(state, "inspections", None)
    for item in () if store is None else store.list(state.tenant_id):
        status = getattr(item.status, "value", item.status)
        if status not in ("offered", "booked"):
            continue
        window = ""
        if item.window_start is not None:
            window = day(item.window_start) + (f" to {day(item.window_end)}" if item.window_end else "")
        items.append(
            {
                "kind": "Inspection offered" if status == "offered" else "Inspection booked",
                "tone": "warn" if status == "offered" else "ok",
                "waiting": status == "offered",
                "held": False,
                "at": item.at,
                "conversation_id": item.conversation_id,
                "customer": _contact_label(state, item.conversation_id) or "Customer",
                "wants": clean(item.summary) or _wants(state, item.conversation_id),
                "detail": " · ".join(part for part in (item.address, window) if part),
                "amount": f"Fee {item.fee}" if item.fee else "",
            }
        )
    for row in pending:
        conversation_id, quote = threads.get(row.quote_id.value, (None, None))
        items.append(
            {
                "kind": "Discount ask",
                "tone": "warn",
                "waiting": True,
                "held": False,
                "at": None if quote is None else quote.current.at,
                "conversation_id": conversation_id,
                "customer": (_contact_label(state, conversation_id) if conversation_id else "") or row.quote_id.value,
                "wants": f"{percent(row.requested_discount_percent)}% off {row.quote_id.value} (cap {percent(row.discount_cap_percent)}%)",
                "detail": "",
                "amount": rand(row.total),
                "quote_id": row.quote_id.value,
                "version": row.version,
            }
        )
    floor = datetime.min.replace(tzinfo=timezone.utc)
    items.sort(key=lambda item: (not item["waiting"], -(item["at"] or floor).timestamp()))
    for item in items:
        item["waited"] = ago(now, item["at"])
    return items


def _handovers(state) -> tuple:
    log = getattr(state, "handovers", None)
    return () if log is None else log.list(state.tenant_id)


def waiting_count(state, pending=None) -> int:
    rows = state.list_pending.execute(TenantContext(tenant_id=state.tenant_id)) if pending is None else pending
    held = sum(1 for note in _handovers(state) if _held(state, note.conversation_id))
    return held + len(rows)


def _matches(text: str, needle: str) -> bool:
    return needle.casefold() in text.casefold()


def _paged(rows: list, page: int) -> tuple[list, dict]:
    pages = max(1, math.ceil(len(rows) / _PAGE))
    page = min(max(page, 1), pages)
    start = (page - 1) * _PAGE
    return rows[start : start + _PAGE], {"page": page, "pages": pages, "count": len(rows)}


# Pages -----------------------------------------------------------------------------------------


def _shell(request: Request, tab: str, pending=None) -> dict:
    state = request.app.state
    return {
        "business": _business_name(state),
        "tab": tab,
        "tabs": _TABS,
        "waiting": waiting_count(state, pending),
        "signin": bool(owner_password(state)),
        "actor": actor(request),
    }


def _render(request: Request, template: str, tab: str, status_code: int = 200, pending=None, **values) -> HTMLResponse:
    html = owner_templates().get_template(template).render(**_shell(request, tab, pending), **values)
    return HTMLResponse(html, status_code=status_code, headers={"Cache-Control": "no-store"})


def error_page(request: Request) -> HTMLResponse:
    try:
        business = _business_name(request.app.state)
    except Exception:  # noqa: BLE001 - the error page must render whatever failed
        business = ""
    html = owner_templates().get_template("error.html").render(
        business=business, tab="", tabs=_TABS, waiting=0, signin=False, actor=""
    )
    return HTMLResponse(html, status_code=500, headers={"Cache-Control": "no-store"})


@router.get("/console", response_class=HTMLResponse, response_model=None)
def console(
    request: Request, done: str = "", action: str = "", published: str = "", period: str = "today"
) -> HTMLResponse | Response:
    if _store_down(request):
        return Response(status_code=503)
    if published:
        return RedirectResponse(f"/console/policy?published={quote(published)}", status_code=303)
    result = None
    if done and action in _ACTIONS:
        result = request.app.state.unit.find_operator_result(request.app.state.tenant_id, done)
    return owner_page(request, result=result, action=action if result is not None else "", period=period)


@router.get("/console/summary", response_model=None)
def summary_json(request: Request, period: str = "today") -> JSONResponse | Response:
    if _store_down(request):
        return Response(status_code=503)
    found = summary(request, period)
    return JSONResponse(
        {
            "period": found.period,
            "label": found.label,
            "customers": found.customers,
            "messages": found.messages,
            "quotes_sent": found.quotes_sent,
            "quoted_value": f"{found.quoted_value.amount:.2f}",
            "ranges": found.ranges,
            "deposits_due": f"{found.deposits_due.amount:.2f}",
            "deposits_paid": found.deposits_paid,
            "inspections_offered": found.inspections_offered,
            "inspections_booked": found.inspections_booked,
            "handovers_waiting": found.handovers_waiting,
            "approvals_waiting": found.approvals_waiting,
            "oldest_wait": None if found.oldest_wait is None else found.oldest_wait.isoformat(),
            "lines": found.lines.model_dump(),
            "spoken": found.spoken,
        },
        headers={"Cache-Control": "no-store"},
    )


@router.get("/console/inbox", response_class=HTMLResponse, response_model=None)
def inbox(request: Request) -> HTMLResponse | Response:
    if _store_down(request):
        return Response(status_code=503)
    state = request.app.state
    rows = state.list_pending.execute(_context(request))
    return _render(
        request,
        "inbox.html",
        "inbox",
        pending=rows,
        items=inbox_items(state, _handovers(state), rows),
        rows=rows,
        result=None,
        action="",
        error=None,
        result_total=None,
    )


@router.get("/console/quotes", response_class=HTMLResponse, response_model=None)
def quotes_page(request: Request, q: str = "", status: str = "", page: int = 1) -> HTMLResponse | Response:
    if _store_down(request):
        return Response(status_code=503)
    rows = quote_rows(request.app.state)
    statuses = sorted({(row["status"], state_label(row["state"])) for row in rows}, key=lambda pair: pair[1])
    needle = q.strip()
    if needle:
        rows = [row for row in rows if any(_matches(str(row[key] or ""), needle) for key in ("quote_id", "contact", "goods", "sent"))]
    if status:
        rows = [row for row in rows if row["status"] == status]
    shown, paging = _paged(rows, page)
    return _render(request, "quotes.html", "quotes", quotes=shown, paging=paging, q=needle, status=status, statuses=statuses)


@router.get("/console/customers", response_class=HTMLResponse, response_model=None)
def customers_page(request: Request, q: str = "", page: int = 1) -> HTMLResponse | Response:
    if _store_down(request):
        return Response(status_code=503)
    rows = customer_rows(request.app.state)
    needle = q.strip()
    if needle:
        rows = [row for row in rows if any(_matches(str(row[key] or ""), needle) for key in ("name", "number", "last"))]
    shown, paging = _paged(rows, page)
    return _render(request, "customers.html", "customers", customers=shown, paging=paging, q=needle)


@router.get("/console/policy", response_class=HTMLResponse, response_model=None)
def policy_page(request: Request, published: str = "", imported: str = "") -> HTMLResponse | Response:
    if _store_down(request):
        return Response(status_code=503)
    return owner_page(request, policy=policy_view(request, published=published), imported=imported == "1")


@router.get("/console/settings", response_class=HTMLResponse, response_model=None)
def settings_page(request: Request) -> HTMLResponse | Response:
    if _store_down(request):
        return Response(status_code=503)
    state = request.app.state
    tenant = getattr(state, "tenant", None)
    phones = getattr(state, "tenants_by_phone", None) or {}
    return _render(
        request,
        "settings.html",
        "settings",
        tenant=tenant,
        phones=[phone for phone, owner in phones.items() if owner == state.tenant_id] if isinstance(phones, dict) else [],
        actions=list(reversed(owner_log(state)))[:50],
        store=getattr(state, "store_status", "postgres"),
    )


@router.get("/console/login", response_class=HTMLResponse, response_model=None)
def login_page(request: Request, next: str = "/console") -> HTMLResponse | RedirectResponse:  # noqa: A002
    if not owner_password(request.app.state):
        return RedirectResponse("/console", status_code=303)
    return _login(request, next, error="")


def _safe_next(target: str) -> str:
    return target if target.startswith("/console") and not target.startswith("/console/login") else "/console"


def _login(request: Request, target: str, error: str, status_code: int = 200) -> HTMLResponse:
    html = owner_templates().get_template("login.html").render(
        business=_business_name(request.app.state), next=_safe_next(target), error=error
    )
    return HTMLResponse(html, status_code=status_code, headers={"Cache-Control": "no-store"})


@router.post("/console/login", response_model=None)
async def login(request: Request) -> HTMLResponse | RedirectResponse:
    form = await read_form(request)
    password = owner_password(request.app.state)
    target = _safe_next(form.get("next", "/console"))
    if not password:
        return RedirectResponse(target, status_code=303)
    if not hmac.compare_digest(form.get("password", "").encode("utf-8"), password.encode("utf-8")):
        return _login(request, target, error=_WRONG_PASSWORD, status_code=401)
    response = RedirectResponse(target, status_code=303)
    response.set_cookie(_COOKIE, _token(password), httponly=True, samesite="lax", max_age=60 * 60 * 12)
    record_action(request, "Signed in")
    return response


@router.post("/console/logout", response_model=None)
async def logout(request: Request) -> RedirectResponse:
    response = RedirectResponse("/console/login" if owner_password(request.app.state) else "/console", status_code=303)
    response.delete_cookie(_COOKIE)
    if signed_in(request):
        record_action(request, "Signed out")
    return response


@router.post("/console/approve", response_model=None)
async def approve(request: Request) -> HTMLResponse | RedirectResponse:
    return _decide(request, await read_form(request), "approved")


@router.post("/console/reject", response_model=None)
async def reject(request: Request) -> HTMLResponse | RedirectResponse:
    return _decide(request, await read_form(request), "rejected")


# The case page ---------------------------------------------------------------------------------


class _Silent:
    def already(self, *_args) -> bool:
        return True

    def record(self, *_args) -> None:
        return None

    def send(self, *_args) -> None:
        return None


def _built_brief(state, conversation_id: UUID) -> str:
    """A brief from the case, for a row that was never escalated or still has the old short note."""
    cases = getattr(state, "cases", None)
    if cases is None:
        return ""
    try:
        tool = EscalateToOwner(
            cases,
            state.conversations,
            getattr(state, "policies", None),
            None,
            getattr(state, "inspections", None),
            NotifyOwner(_Silent(), _Silent()),
            getattr(state, "clock", None),
            quotes=getattr(state, "unit", None),
        )
        return tool.render(
            TenantContext(tenant_id=state.tenant_id),
            EscalateToOwnerInput(conversation_id=conversation_id),
        )
    except (ApplicationError, DomainError):
        return ""


def _brief_text(state, conversation_id: UUID) -> str:
    notes = _handovers(state)
    found = next((note for note in notes if note.conversation_id == conversation_id), None)
    text = "" if found is None else clean(found.brief)
    if "Customer:" not in text:
        built = _built_brief(state, conversation_id)
        if built:
            text = built
    return clean(text)


def _brief_fields(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in text.splitlines():
        key, colon, value = line.partition(":")
        if colon and key.strip() and key.strip() not in fields:
            fields[key.strip()] = value.strip()
    return fields


def _none(value: str | None) -> str:
    value = (value or "").strip()
    return "" if value.casefold() in ("none", "not said", "not given") else value


def _facts(state, conversation_id: UUID) -> list[dict]:
    cases = getattr(state, "cases", None)
    case = None if cases is None else cases.get(state.tenant_id, conversation_id)
    rows = []
    for job in () if case is None else case.jobs:
        for fact in job.facts:
            if fact.superseded_by is not None or fact.state != "known":
                continue
            rows.append(
                {
                    "label": fact.key.replace("_", " ").capitalize(),
                    "value": fact.value,
                    "source": _SOURCES.get(fact.source, fact.source),
                    "status": fact.status.capitalize(),
                    "contested": fact.contested or fact.status == "contested",
                }
            )
    return rows


def _conversation(state, conversation_id: UUID) -> list[dict]:
    rows = []
    for message in _messages(state, conversation_id):
        rows.append(
            {
                "side": "in",
                "at": message.at,
                "text": (message.body or message.transcript or "").strip(),
                "kind": _KINDS.get(message.kind, ""),
                "media": message.media_id if message.kind in ("image", "video") else None,
            }
        )
    replies = getattr(state.conversations, "replies", None)
    for at, body in () if replies is None else replies(state.tenant_id, conversation_id):
        rows.append({"side": "out", "at": at, "text": (body or "").strip(), "kind": "", "media": None})
    floor = datetime.min.replace(tzinfo=timezone.utc)
    rows.sort(key=lambda row: row["at"] or floor)
    return rows


def case_view(request: Request, conversation_id: UUID) -> dict:
    state = request.app.state
    who = _who(state, conversation_id)
    text = _brief_text(state, conversation_id)
    fields = _brief_fields(text)
    quote = state.unit.get_quote(state.tenant_id, conversation_id) if getattr(state, "unit", None) is not None else None
    quote_row = None
    if quote is not None and quote.versions and quote.current.state is not QuoteState.DRAFT:
        current = quote.current
        quote_row = {
            "quote_id": quote.quote_id.value,
            "version": current.number,
            "state": current.state,
            "tone": _TONES.get(current.state, "muted"),
            "amount": quote_amount(current),
            "deposit": None if current.deposit is None else rand(current.deposit),
            "lines": current.lines,
            "expiry": current.expiry,
            "at": current.at,
            "why": _why(current),
            "revisions": max(0, current.number - 1),
        }
    pending = [
        row
        for row in state.list_pending.execute(_context(request))
        if quote is not None and row.quote_id.value == quote.quote_id.value
    ]
    held = _held(state, conversation_id)
    conversation = _conversation(state, conversation_id)
    first = next((row["at"] for row in conversation if row["side"] == "in"), None)
    if held:
        status, tone = "Waiting for you", "warn"
    elif quote_row is not None:
        status, tone = state_label(quote_row["state"]), quote_row["tone"]
    else:
        status, tone = "Enquiry", "muted"
    timeline = ()
    if getattr(state, "unit", None) is not None:
        timeline = AuditTimeline(state.unit).execute(_context(request), conversation_id)
    return {
        "conversation_id": conversation_id,
        "who": who,
        "status": status,
        "tone": tone,
        "first": first,
        "wants": _none(fields.get("Wants")) or _wants(state, conversation_id),
        "missing": [part.strip() for part in _none(fields.get("Missing")).split(",") if part.strip()],
        "next_step": _none(fields.get("Next")),
        "outcome": _none(fields.get("Outcome")),
        "reason": _none(fields.get("Reason")),
        "inspection": _none(fields.get("Inspection")),
        "facts": _facts(state, conversation_id),
        "photos": [row for row in conversation if row["media"]],
        "conversation": conversation,
        "quote": quote_row,
        "pending": pending,
        "held": held,
        "timeline": timeline,
        "brief": text or "This case has no brief yet.",
        "whatsapp": f"https://wa.me/{who['wa_id']}" if str(who["wa_id"]).isdigit() else "",
    }


@router.get("/console/brief/{conversation_id}", response_class=HTMLResponse)
def brief(request: Request, conversation_id: UUID) -> HTMLResponse:
    return _render(request, "brief.html", "inbox", case=case_view(request, conversation_id))


@router.post("/console/release", response_model=None)
async def release(request: Request) -> RedirectResponse:
    form = await read_form(request)
    raw = form.get("conversation_id", "").strip()
    back = "/console/inbox"
    try:
        conversation_id = UUID(raw)
    except ValueError:
        return RedirectResponse(back, status_code=303)
    store = request.app.state.conversations
    release_hold = getattr(store, "release_escalation", None)
    if release_hold is not None:
        release_hold(request.app.state.tenant_id, conversation_id)
        record_action(request, "Released to the assistant", _contact_label(request.app.state, conversation_id))
    if form.get("back", "") == "case":
        back = f"/console/brief/{conversation_id}"
    return RedirectResponse(back, status_code=303)


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
    record_action(request, "Approved a discount" if action == "approved" else "Rejected a discount", f"{quote_id.value} v{version}")
    return RedirectResponse(f"/console?done={key}&action={action}#approvals", status_code=303)


# Rates & policy --------------------------------------------------------------------------------


class _KeepHeaders:
    def label(self, headers):
        return {header: header for header in headers}


def _backups(state) -> dict:
    backups = getattr(state, "draft_backups", None)
    if backups is None:
        backups = {}
        state.draft_backups = backups
    return backups


@router.post("/console/rate-card/import", response_model=None)
async def import_rate_card(request: Request) -> HTMLResponse | RedirectResponse | Response:
    if _store_down(request):
        return Response(status_code=503)
    state = request.app.state
    form = await request.form()
    upload = form.get("rate_card")
    filename = getattr(upload, "filename", "") or ""
    body = await upload.read() if upload is not None and hasattr(upload, "read") else b""
    before = state.policies.draft(state.tenant_id)
    tool = ImportRateCard(state.policies, state.unit, reject_macros_before_parse)
    try:
        result = tool.execute(
            _context(request),
            ImportRateCardInput(filename=filename or "rate-card.csv", body=body, expected_unit="each", labeller=_KeepHeaders()),
        )
    except (ApplicationError, DomainError) as exc:
        return owner_page(request, policy=policy_view(request, refusal=getattr(exc, "sentence", str(exc))), status_code=422)
    if before is not None:
        _backups(state)[state.tenant_id] = {"draft": before, "rows": result.rows, "filename": filename}
    record_action(request, "Imported a rate card", f"{filename or 'file'}: {len(result.rows)} rows")
    return RedirectResponse("/console/policy?imported=1#rates", status_code=303)


@router.post("/console/rate-card/undo", response_model=None)
async def undo_import(request: Request) -> RedirectResponse:
    state = request.app.state
    backup = _backups(state).pop(state.tenant_id, None)
    if backup is not None:
        state.policies.save_draft(state.tenant_id, backup["draft"])
        record_action(request, "Undid a rate card import", backup.get("filename", ""))
    return RedirectResponse("/console/policy#rates", status_code=303)


@router.post("/console/policy/rollback", response_model=None)
async def rollback(request: Request) -> HTMLResponse | RedirectResponse | Response:
    if _store_down(request):
        return Response(status_code=503)
    form = await read_form(request)
    version = form.get("source_version", "").strip()
    reason = form.get("reason", "").strip()
    tool = RollbackPolicy(request.app.state.policies, request.app.state.unit, request.app.state.clock)
    try:
        published = tool.execute(
            _context(request),
            RollbackInput(source_version=PolicyVersionId(version), reason=reason, idempotency_key=str(uuid4())),
        )
    except (ApplicationError, DomainError) as exc:
        return owner_page(request, policy=policy_view(request, refusal=getattr(exc, "sentence", str(exc))), status_code=422)
    record_action(request, f"Restored {version}", reason, version=published.value)
    return RedirectResponse(f"/console/policy?published={published.value}", status_code=303)


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
    bundle = state.policies.published(state.tenant_id)
    return {
        "bundle": bundle,
        "draft": draft,
        "deposit": deposit,
        "reason": reason,
        "errors": errors,
        "refusal": refusal,
        "published": _published_version(request, published),
        "names": _item_names(state),
        "groups": _live_groups(state, bundle),
        "history": policy_history(state),
        "rows": [
            *rows,
            {
                "code": "",
                "name": "",
                "price": "",
                "remove": False,
                "blank": True,
                "unit": "each",
                "role": "product",
                "applies_to": "both",
                "job_types": "",
                "when": "",
                "when_summary": "",
            },
        ],
        "deposit_invalid": any("deposit" in sentence.lower() for sentence in errors),
        "storage": None if store is None else store.reachable,
        "ready": not errors and draft is not None and reason.strip() != "",
        "roles": _ROLE_LABELS,
    }


def _rank(role: str) -> int:
    return _ROLE_ORDER.index(role) if role in _ROLE_ORDER else len(_ROLE_ORDER)


def _live_groups(state, bundle) -> list[dict]:
    names = _item_names(state)
    groups: dict[str, list] = {}
    for item in bundle.rate_card.items:
        groups.setdefault(item.role, []).append(
            {"item": item, "name": names.get(item.item_code, item.description)}
        )
    return [
        {"role": role, "label": _ROLE_LABELS.get(role, role.capitalize()), "entries": items}
        for role, items in sorted(groups.items(), key=lambda pair: _rank(pair[0]))
    ]


def policy_history(state) -> list[dict]:
    """Every kept version, newest first, with the reason the owner gave when there is one."""
    bundle = state.policies.published(state.tenant_id)
    current = bundle.policy.version.value
    reasons = {entry["version"]: entry for entry in owner_log(state) if entry.get("version")}
    rows = []
    for version, kept in reversed(list(getattr(state.policies, "versions", {}).items())):
        entry = reasons.get(version, {})
        rows.append(
            {
                "version": version,
                "current": version == current,
                "deposit": kept.clause_policy.settings.get("deposit_percent", ""),
                "validity": kept.clause_policy.settings.get("validity_days", ""),
                "items": len(kept.rate_card.items),
                "reason": entry.get("detail", ""),
                "at": entry.get("at"),
                "actor": entry.get("actor", ""),
            }
        )
    return rows


def draft_rows(draft) -> list[dict]:
    if draft is None:
        return []
    rows = [
        {
            "code": row.item_code,
            "name": row.description,
            "price": f"{row.unit_price:.2f}",
            "remove": False,
            "unit": row.unit,
            "role": row.role,
            "applies_to": row.applies_to,
            "job_types": ", ".join(row.job_types),
            "when": "" if row.when is None else json.dumps(row.when.model_dump(mode="json"), separators=(",", ":")),
            "when_summary": summarise(row.when),
        }
        for row in draft.rate_rows
    ]
    return sorted(rows, key=lambda row: _rank(row["role"]))


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
    period: str = "today",
    imported: bool = False,
) -> HTMLResponse:
    """The Today tab, or the Rates & policy tab when a policy view is passed in."""
    state = request.app.state
    rows = state.list_pending.execute(_context(request))
    if policy is not None:
        backup = _backups(state).get(state.tenant_id)
        return _render(
            request,
            "policy.html",
            "policy",
            status_code=status_code,
            pending=rows,
            policy=policy,
            imported=backup if imported else None,
            undo=backup is not None,
        )
    return _render(
        request,
        "console.html",
        "today",
        status_code=status_code,
        pending=rows,
        summary=summary(request, period),
        periods=(("today", "Today"), ("yesterday", "Yesterday"), ("week", "This week")),
        contacts=contacts(state, _LATEST),
        quotes=sent_quotes(state),
        rows=rows,
        result=result,
        result_total=total(result.lines) if result is not None else None,
        action=action,
        error=error,
    )
