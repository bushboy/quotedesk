"""The chat simulator. It plays the provider's side of the channel.

The page posts Cloud API JSON to the webhook and reads the outbox, like the harness.
Uploads land here, the way a provider hosts media, and the webhook carries only the media id.
Nothing in this module calls a use case.
"""

import re
import threading
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, Response
from jinja2 import Environment, FileSystemLoader, select_autoescape

router = APIRouter()

_TEMPLATES = Path(__file__).resolve().parent / "templates"
_MEDIA = Path(__file__).resolve().parents[4] / "seeds" / "media"
_WA_ID = re.compile(r"\d{6,15}")
_CLIENTS = (
    "15550002222",
    "15550003333",
    "15550004444",
    "15550005555",
    "15550006666",
)
_PINNED = _CLIENTS[0]
_MAX_UPLOAD = 16 * 1024 * 1024
_MAX_OBJECTS = 200


class SimulatedMedia:
    """In-process stand-in for the provider's media hosting."""

    def __init__(self) -> None:
        self._objects: dict[str, tuple[str, bytes]] = {}
        self._lock = threading.Lock()

    def put(self, mime: str, data: bytes) -> str:
        media_id = uuid4().hex
        with self._lock:
            if len(self._objects) >= _MAX_OBJECTS:
                self._objects.pop(next(iter(self._objects)))
            self._objects[media_id] = (mime, data)
        return media_id

    def get(self, media_id: str) -> tuple[str, bytes] | None:
        return self._objects.get(media_id)


def _labels(request: Request, numbers: tuple[str, ...]) -> dict[str, str]:
    store = getattr(request.app.state, "conversations", None)
    named = None if store is None else getattr(store, "name", None)
    tenant_id = getattr(request.app.state, "tenant_id", None)
    labels = {}
    for number in numbers:
        name = named(tenant_id, number) if named is not None and tenant_id is not None else None
        labels[number] = f"{name} · {number}" if name else number
    return labels


def _environment() -> Environment:
    return Environment(loader=FileSystemLoader(_TEMPLATES), autoescape=select_autoescape(["html"]))


@router.get("/chat", response_class=HTMLResponse)
def chat(request: Request, wa_id: str | None = None) -> HTMLResponse:
    explicit = bool(wa_id) and _WA_ID.fullmatch(wa_id) is not None
    active = wa_id if explicit else _PINNED
    numbers = _CLIENTS if active in _CLIENTS else (active, *_CLIENTS)
    profile = getattr(request.app.state, "tenant", None)
    business = profile.display_name if profile is not None else "AquaSure"
    html = _environment().get_template("chat.html").render(
        business=business,
        wa_id=active,
        customer="Thabo",
        numbers=numbers,
        labels=_labels(request, numbers),
        remember=not explicit,
    )
    return HTMLResponse(html)


@router.get("/media/{name}", response_model=None)
def media(name: str) -> FileResponse | PlainTextResponse:
    path = (_MEDIA / name).resolve()
    if not path.is_relative_to(_MEDIA.resolve()) or not path.is_file():
        return PlainTextResponse("That file is not on disk.", status_code=404)
    return FileResponse(path)


@router.post("/sim/media", response_model=None)
async def upload(request: Request) -> JSONResponse | PlainTextResponse:
    mime = request.headers.get("content-type", "application/octet-stream").split(";", 1)[0].strip().lower()
    data = await request.body()
    if not data:
        return PlainTextResponse("Empty upload.", status_code=400)
    if len(data) > _MAX_UPLOAD:
        return PlainTextResponse("That file is too large.", status_code=413)
    media_id = request.app.state.sim_media.put(mime, data)
    return JSONResponse({"id": media_id, "mime_type": mime, "url": f"/sim/media/{media_id}"})


@router.get("/sim/media/{media_id}", response_model=None)
def download(request: Request, media_id: str) -> Response:
    found = request.app.state.sim_media.get(media_id)
    if found is None:
        return PlainTextResponse("That file is not on disk.", status_code=404)
    mime, data = found
    return Response(content=data, media_type=mime, headers={"cache-control": "private, max-age=86400"})


@router.post("/sim/reset", response_model=None)
def reset(request: Request) -> Response:
    request.app.state.reset()
    return Response(status_code=204)
