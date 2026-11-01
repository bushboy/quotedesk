"""Decides whether a confirmed carport quote gets a drawing, and what the drawing says.

The quote sentence is already chosen before this runs. A missing photo, a blurry photo,
or a failed drawing does not change that sentence.
"""

import base64
import re
from typing import NamedTuple

from quotedesk.application.ports.pictures import PictureRequest
from quotedesk.domain.case.contradictions import spec_choice

_SITE = re.compile(r"\b(garage|wall|house)\b", re.IGNORECASE)
_ASK = re.compile(r"\b(render|preview|drawing)\b|\bpicture of\b", re.IGNORECASE)
_RAND = re.compile(r"\br\s*[\d,]+", re.IGNORECASE)
_ABOVE = (
    "The camera is above the carport, looking down, between 5 and 10 metres away, "
    "so the whole roof and its sheeting are visible."
)
_LEVEL = (
    "The camera is at eye level with the ground, between 5 and 10 metres away, "
    "so the whole carport is in the frame."
)
_VIEWS = (("above", _ABOVE, "from above"), ("level", _LEVEL, "from eye level"))
FAILED = "I couldn't draw that carport. The quote above still stands."


class Drawn(NamedTuple):
    """A follow-up after the quote. No image URL means the drawing did not come through."""

    caption: str
    image_url: str | None


class CarportSketch:
    """Calls the renderer for a confirmed carport. AquaSure never reaches it."""

    def __init__(self, drawer, cases, conversations, policies, host, trade: str) -> None:
        self._drawer = drawer
        self._cases = cases
        self._conversations = conversations
        self._policies = policies
        self._host = host
        self._trade = trade

    def replaces_reply(self, context, conversation_id) -> bool:
        """A request for a picture is answered by the drawings, not by a text refusal."""
        return self._prepared(context, conversation_id) is not None and _asked(self, context, conversation_id)

    def after_quote(self, context, conversation_id, body: str) -> tuple[Drawn, ...] | None:
        if "carport" not in self._trade.casefold():
            return None
        prepared = self._prepared(context, conversation_id)
        if prepared is None:
            return None
        if not _fixed_quote(body) and not _asked(self, context, conversation_id):
            return None
        case, playbook = prepared
        ready = _ready(case, playbook)
        if ready is None:
            return None
        option, width, length, finish, gutter, usable = ready
        photo, hard = _photo(self, context, conversation_id, case, usable)
        drawn: list[Drawn] = []
        for view, instruction, name in _VIEWS:
            prompt = drawing_prompt(
                label=option.label,
                width=width,
                length=length,
                curved=option.sags,
                finish=finish,
                gutter=gutter,
                onto_photo=photo is not None,
                view=instruction,
            )
            try:
                data = self._drawer.draw(PictureRequest(prompt, photo))
            except Exception:
                continue
            if not data:
                continue
            caption = _caption(photo is not None, hard, name)
            drawn.append(Drawn(caption, _data_url(data)))
        if not drawn:
            return (Drawn(FAILED, None),)
        return tuple(drawn)

    def _prepared(self, context, conversation_id):
        case = self._cases.get(context.tenant_id, conversation_id)
        published = None if self._policies is None else self._policies.published(context.tenant_id)
        if case is None or published is None or _ready(case, published.playbook) is None:
            return None
        return case, published.playbook


def drawing_prompt(
    *,
    label: str,
    width: str,
    length: str,
    curved: bool,
    finish: str,
    gutter: bool,
    onto_photo: bool,
    view: str,
) -> str:
    """The drawing instruction. It names the spec and no price."""
    if curved:
        roof = f"The roof is {label}. It sags in a curve between the posts."
    else:
        roof = f"The roof is a straight pitched roof of {label}."
    extras = []
    if finish:
        extras.append(f"The frame is {finish}.")
    if gutter:
        extras.append("A gutter runs along the front.")
    if onto_photo:
        place = "Keep this garage and this wall. Add the carport against the wall. Do not change the building."
    else:
        place = "The carport stands against a plain plastered wall of a single garage."
    words = f"A carport {width} metres wide and {length} metres long. {roof}"
    if extras:
        words = f"{words} {' '.join(extras)}"
    return f"{words} {place} {view} No logos. No prices. No writing."


def _caption(used_photo: bool, hard: bool, view: str) -> str:
    if used_photo:
        return f"This is a drawing of that spec on your photo, {view}, not a measure."
    if hard:
        return f"That photo was hard to use. This is a drawing of that spec against a plain wall and garage, {view}, not a measure."
    return f"This is a drawing of that spec against a plain wall and garage, {view}, not a measure."


def _fixed_quote(body: str) -> bool:
    folded = body.casefold()
    if "indicative range" in folded or "site measure" in folded:
        return False
    if "the total is" in folded:
        return True
    return "total" in folded and "/card/" in folded and _RAND.search(body) is not None


def _asked(sketch: CarportSketch, context, conversation_id) -> bool:
    messages = sketch._conversations.messages(context.tenant_id, conversation_id)
    for message in reversed(tuple(messages)):
        if message.kind == "image":
            continue
        body = (message.body or "").strip()
        if not body:
            continue
        return _ASK.search(body) is not None
    return False


def _data_url(data: bytes) -> str:
    if data.startswith(b"\x89PNG"):
        mime = "image/png"
    elif data.startswith(b"\xff\xd8\xff"):
        mime = "image/jpeg"
    elif len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        mime = "image/webp"
    else:
        mime = "image/png"
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def _ready(case, playbook):
    for job in case.jobs:
        if spec_choice(case, job.job_id) is not True:
            continue
        width = _value(case, job.job_id, "width_m")
        length = _value(case, job.job_id, "length_m")
        option = _sheet(playbook, case, job.job_id)
        if not width or not length or option is None:
            continue
        finish = _finish(playbook, _value(case, job.job_id, "finish"))
        gutter = _value(case, job.job_id, "gutters").casefold() in ("true", "yes")
        usable = _value(case, job.job_id, "media_usable").casefold() not in ("false", "no")
        return option, width, length, finish, gutter, usable
    return None


def _sheet(playbook, case, job_id: str):
    codes = []
    for key in ("item_codes", "sheet"):
        value = _value(case, job_id, key)
        if value:
            codes.extend(part.strip() for part in value.split(",") if part.strip())
    for code in codes:
        for option in _options(playbook, "sheet"):
            if option.value == code or code in option.item_codes:
                return option
    return None


def _value(case, job_id: str, key: str) -> str:
    fact = case.active_fact(job_id, key)
    if fact is None or fact.state == "unknown":
        return ""
    return fact.value.strip()


def _finish(playbook, value: str) -> str:
    chosen = value.strip()
    if not chosen:
        return ""
    for option in _options(playbook, "finish"):
        if option.value == chosen:
            return option.label
    return chosen


def _options(playbook, key: str):
    for job in playbook.job_types:
        for fact in job.facts:
            if fact.key == key:
                return fact.options
    return ()


def _photo(sketch: CarportSketch, context, conversation_id, case, usable: bool):
    if not usable:
        return None, True
    messages = sketch._conversations.messages(context.tenant_id, conversation_id)
    notes = _notes(case)
    getter = getattr(sketch._conversations, "enrichment", None)
    chosen = None
    for message in reversed(tuple(messages)):
        if message.kind != "image":
            continue
        read = None if getter is None else getter(context.tenant_id, message.provider_message_id)
        if _SITE.search(_describe(message, read, notes)) is None:
            continue
        chosen = message
        break
    if chosen is None or not chosen.media_id:
        return None, chosen is not None
    found = sketch._host.get(chosen.media_id)
    if found is None:
        return None, True
    return found[1], False


def _notes(case) -> str:
    parts = []
    for job in case.jobs:
        for fact in job.facts:
            if fact.superseded_by is None and fact.key == "photo_note":
                parts.append(fact.value)
    return " ".join(parts)


def _describe(message, read, notes: str) -> str:
    parts = [message.body or "", message.image_text or "", notes]
    if read is not None:
        parts.append(getattr(read, "summary", "") or "")
        parts.extend(getattr(read, "objects", ()) or ())
        parts.extend(getattr(read, "notes", ()) or ())
    return " ".join(part for part in parts if part)
