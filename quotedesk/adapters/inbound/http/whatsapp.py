import hashlib
import hmac
import json
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import PlainTextResponse, Response

from quotedesk.application.dto.inbound import InboundMessage
from quotedesk.application.dto.tenant import TenantContext

router = APIRouter()

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
        return Response(status_code=403)
    try:
        payload = json.loads(raw)
    except ValueError:
        return Response(status_code=400)
    context = TenantContext(tenant_id=request.app.state.tenant_id)
    for message in inbound_messages(payload, request.app.state.conversation_id):
        request.app.state.receive.execute(context, message, request.app.state.flags, request.app.state.limits)
    background.add_task(request.app.state.run_turn)
    return Response(status_code=200)


@router.get("/whatsapp/outbox")
def read_outbox(request: Request, wa_id: str | None = None, after: int | None = None) -> list[dict[str, object]]:
    rows = request.app.state.outbox.pending()
    if wa_id is not None:
        rows = tuple(row for row in rows if row.wa_id == wa_id)
    if after is not None:
        rows = tuple(row for row in rows if row.id > after)
    return [row.model_dump() for row in rows]


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
    if kind not in ("text", *_MEDIA):
        kind = "text"
    media = message.get(kind) if kind in _MEDIA else None
    if kind == "text":
        body = (message.get("text") or {}).get("body")
    else:
        body = (media or {}).get("caption")
    mime = (media or {}).get("mime_type")
    return InboundMessage(
        conversation_id=conversation_id,
        provider_message_id=message["id"],
        wa_id=wa_id,
        at=datetime.fromtimestamp(int(message["timestamp"]), tz=timezone.utc),
        kind=kind,
        body=body,
        mime=mime.split(";", 1)[0].strip().lower() if mime else None,
    )


def _signed(raw: bytes, secret: str, header: str) -> bool:
    expected = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header)
