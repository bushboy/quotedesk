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
_ON_PHOTO = "This is a drawing of that spec on your photo, not a measure."
_IMAGINARY = "This is a drawing of that spec against a plain wall and garage, not a measure."
_HARD = "That photo was hard to use. This is a drawing of that spec against a plain wall and garage, not a measure."
FAILED = "I couldn't draw that carport. The quote above still stands."


class Drawn(NamedTuple):
    """A follow-up after the quote. No image URL means the drawing did not come through."""

    caption: str
    image_url: str | None


class CarportSketch:
    """Calls the renderer after a fixed carport quote. AquaSure never reaches it."""

    def __init__(self, drawer, cases, conversations, policies, host, trade: str) -> None:
        self._drawer = drawer
        self._cases = cases
        self._conversations = conversations
        self._policies = policies
        self._host = host
        self._trade = trade

    def after_quote(self, context, conversation_id, body: str) -> Drawn | None:
        if "carport" not in self._trade.casefold():
            return None
        if not _fixed_quote(body):
            return None
        case = self._cases.get(context.tenant_id, conversation_id)
        published = None if self._policies is None else self._policies.published(context.tenant_id)
        if case is None or published is None:
            return None
        ready = _ready(case, published.playbook)
        if ready is None:
            return None
        option, width, length, finish, gutter, usable = ready
        photo, hard = _photo(self, context, conversation_id, case, usable)
        prompt = drawing_prompt(
            label=option.label,
            width=width,
            length=length,
            curved=option.sags,
            finish=finish,
            gutter=gutter,
            onto_photo=photo is not None,
        )
        try:
            data = self._drawer.draw(PictureRequest(prompt, photo))
        except Exception:
            return Drawn(FAILED, None)
        if not data:
            return Drawn(FAILED, None)
        encoded = base64.b64encode(data).decode("ascii")
        return Drawn(_caption(photo is not None, hard), f"data:image/png;base64,{encoded}")


def drawing_prompt(
    *,
    label: str,
    width: str,
    length: str,
    curved: bool,
    finish: str,
    gutter: bool,
    onto_photo: bool,
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
    return f"{words} {place} No logos. No prices. No writing."


def _caption(used_photo: bool, hard: bool) -> str:
    if used_photo:
        return _ON_PHOTO
    if hard:
        return _HARD
    return _IMAGINARY


def _fixed_quote(body: str) -> bool:
    folded = body.casefold()
    if "the total is" not in folded:
        return False
    if "indicative range" in folded or "site measure" in folded:
        return False
    return True


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
