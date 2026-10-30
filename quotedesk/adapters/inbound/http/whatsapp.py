import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import PlainTextResponse, Response

from quotedesk.application.dto.inbound import InboundMessage
from quotedesk.application.dto.tenant import TenantContext

router = APIRouter()
_log = logging.getLogger(__name__)

_MEDIA = ("image", "audio", "video")


@router.get("/whatsapp/webhook", response_model=None)
def verify(request: Request) -> PlainTextResponse:
    params = request.query_params
    expected = request.app.state.settings.whatsapp_verify_token
    token = params.get("hub.verify_token")
    if (
        params.get("hub.mode") != "subscribe"
        or not expected
        or token is None
        or not hmac.compare_digest(token, expected)
    ):
        return PlainTextResponse("", status_code=403)
    return PlainTextResponse(params.get("hub.challenge", ""))


@router.post("/whatsapp/webhook")
async def webhook(request: Request, background: BackgroundTasks) -> Response:
    raw = await request.body()
    secret = request.app.state.settings.whatsapp_app_secret
    if secret and not _signed(raw, secret, request.headers.get("x-hub-signature-256", "")):
        _log.warning("WhatsApp webhook rejected: signature did not match")
        return Response(status_code=403)
    try:
        payload = json.loads(raw)
    except ValueError:
        _log.warning("WhatsApp webhook rejected: body was not JSON")
        return Response(status_code=400)
    context = TenantContext(tenant_id=request.app.state.tenant_id)
    messages = inbound_messages(payload, request.app.state.conversation_id)
    if not messages:
        _log.info("WhatsApp inbound with no customer message")
    for message in messages:
        message = message.model_copy(update={"conversation_id": _resume(request, message.wa_id)})
        message = _measured(request, message)
        _note_image(request, message)
        result = request.app.state.receive.execute(context, message, request.app.state.flags, request.app.state.limits)
        if result.duplicate:
            outcome = "duplicate"
        elif result.sentence is not None:
            outcome = "handled by gate"
        else:
            outcome = "stored for the turn"
        _log.info(
            "WhatsApp inbound id=%s from=%s conversation=%s kind=%s body=%s outcome=%s",
            message.provider_message_id,
            message.wa_id,
            message.conversation_id,
            message.kind,
            message.body,
            outcome,
        )
    background.add_task(request.app.state.run_turn)
    return Response(status_code=200)


@router.get("/whatsapp/history")
def history(request: Request, wa_id: str) -> list[dict[str, str]]:
    transcript = getattr(request.app.state.conversations, "transcript", None)
    if transcript is None:
        return []
    return transcript(request.app.state.tenant_id, wa_id)


@router.get("/whatsapp/outbox")
def read_outbox(request: Request, wa_id: str | None = None, after: int | None = None) -> list[dict[str, object]]:
    rows = request.app.state.outbox.pending()
    if wa_id is not None:
        rows = tuple(row for row in rows if row.wa_id == wa_id)
    if after is not None:
        rows = tuple(row for row in rows if row.id > after)
    return [row.model_dump() for row in rows]


def _resume(request: Request, wa_id: str):
    """The customer's existing thread, or a new one with its own case."""
    conversations = request.app.state.conversations
    cases = request.app.state.cases
    tenant_id = request.app.state.tenant_id
    found = conversations.find(tenant_id, wa_id)
    if found is not None:
        conversation_id = _for_tenant(conversations, tenant_id, found)
        if conversation_id != found:
            conversations.bind(tenant_id, wa_id, conversation_id)
            cases.ensure(tenant_id, conversation_id)
        request.app.state.conversation_id = conversation_id
        return conversation_id
    seeded = request.app.state.conversation_id
    candidate = uuid4() if conversations.taken(seeded) else seeded
    conversation_id = _for_tenant(conversations, tenant_id, candidate)
    conversations.bind(tenant_id, wa_id, conversation_id)
    cases.ensure(tenant_id, conversation_id)
    request.app.state.conversation_id = conversation_id
    return conversation_id


def _for_tenant(conversations, tenant_id, conversation_id):
    """The id when this tenant owns it. A row held by another tenant gets a new id."""
    place = getattr(conversations, "place", None)
    if place is None:
        return conversation_id
    return place(tenant_id, conversation_id)


def inbound_messages(payload: dict, conversation_id) -> list[InboundMessage]:
    """Every customer message in a Cloud API delivery. Status updates carry none."""
    found: list[InboundMessage] = []
    for entry in payload.get("entry") or ():
        for change in entry.get("changes") or ():
            value = change.get("value") or {}
            contacts = value.get("contacts") or ()
            for message in value.get("messages") or ():
                wa_id = contacts[0]["wa_id"] if contacts else message["from"]
                found.append(_inbound(message, wa_id, conversation_id))
    return found


def _inbound(message: dict, wa_id: str, conversation_id) -> InboundMessage:
    kind = message.get("type", "text")
    if kind == "interactive":
        return _text_message(message, wa_id, conversation_id, _interactive_body(message.get("interactive") or {}))
    if kind == "location":
        return _text_message(message, wa_id, conversation_id, _location_body(message.get("location") or {}))
    if kind not in ("text", *_MEDIA):
        kind = "text"
    media = message.get(kind) if kind in _MEDIA else None
    if kind == "text":
        body = (message.get("text") or {}).get("body")
    else:
        body = (media or {}).get("caption")
    mime = (media or {}).get("mime_type")
    media_id = (media or {}).get("id") if isinstance(media, dict) else None
    return InboundMessage(
        conversation_id=conversation_id,
        provider_message_id=message["id"],
        wa_id=wa_id,
        at=datetime.fromtimestamp(int(message["timestamp"]), tz=timezone.utc),
        kind=kind,
        body=body,
        media_id=media_id,
        mime=mime.split(";", 1)[0].strip().lower() if mime else None,
    )


def _text_message(message: dict, wa_id: str, conversation_id, body: str) -> InboundMessage:
    return InboundMessage(
        conversation_id=conversation_id,
        provider_message_id=message["id"],
        wa_id=wa_id,
        at=datetime.fromtimestamp(int(message["timestamp"]), tz=timezone.utc),
        kind="text",
        body=body,
    )


def _interactive_body(interactive: dict) -> str:
    reply = interactive.get("button_reply") or interactive.get("list_reply") or {}
    return reply.get("title") or reply.get("id") or ""


def _location_body(location: dict) -> str:
    name = location.get("name") or location.get("address") or ""
    latitude = location.get("latitude")
    longitude = location.get("longitude")
    pin = "" if latitude is None or longitude is None else f"{latitude}, {longitude}"
    return " ".join(part for part in (name, pin) if part) or "location"


def _measured(request: Request, message: InboundMessage) -> InboundMessage:
    """The live gate sees the hosted object's length. A missing id stays unset."""
    if message.kind != "image" or not message.media_id:
        return message
    host = getattr(request.app.state, "sim_media", None)
    if host is None:
        return message
    found = host.get(message.media_id)
    if found is None:
        return message
    return message.model_copy(update={"size_bytes": len(found[1])})


def _note_image(request: Request, message: InboundMessage) -> None:
    """Tell the enricher which hosted object belongs to this message."""
    if message.kind != "image":
        return
    enricher = getattr(getattr(request.app.state, "turn", None), "enricher", None)
    note = getattr(enricher, "note", None)
    if note is None:
        return
    note(message.provider_message_id, message.media_id, message.body or "")


def _signed(raw: bytes, secret: str, header: str) -> bool:
    expected = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header)
