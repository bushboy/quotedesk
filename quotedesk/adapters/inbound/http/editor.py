"""The owner's policy editor: one deposit percent, one reason, one publish.

The draft is checked by `validate_policy` and published by `PublishPolicy`.
The page never writes the published bundle itself.
"""

import re
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from quotedesk.adapters.inbound.http.console import owner_templates, read_form
from quotedesk.application.dto.tenant import TenantContext
from quotedesk.application.dto.tool_inputs import PublishInput
from quotedesk.application.errors import ApplicationError
from quotedesk.domain.services.validate_policy import validate_policy
from quotedesk.domain.shared.errors import DomainError
from quotedesk.domain.shared.ids import PolicyVersionId

router = APIRouter()

_WHOLE = re.compile(r"-?\d{1,6}")
_NOT_A_NUMBER = "Type the deposit as a whole number, like 30."


@router.get("/editor", response_class=HTMLResponse)
def editor(request: Request, published: str = "") -> HTMLResponse:
    state = request.app.state
    draft = state.policies.draft(state.tenant_id)
    version = _published_version(request, published)
    deposit = str(draft.deposit_percent) if draft is not None else ""
    return _page(request, deposit=deposit, errors=_sentences(draft), published=version)


@router.post("/editor/draft", response_model=None)
async def check(request: Request) -> HTMLResponse | JSONResponse:
    form = await read_form(request)
    deposit = form.get("deposit", "").strip()
    errors = _store(request, deposit)
    if "application/json" in request.headers.get("accept", ""):
        return JSONResponse({"errors": list(errors)}, headers={"Cache-Control": "no-store"})
    return _page(request, deposit=deposit, reason=form.get("reason", ""), errors=errors)


@router.post("/editor/publish", response_model=None)
async def publish(request: Request) -> HTMLResponse | RedirectResponse:
    form = await read_form(request)
    deposit = form.get("deposit", "").strip()
    reason = form.get("reason", "")
    errors = _store(request, deposit)
    if errors:
        return _page(request, deposit=deposit, reason=reason, errors=errors, status_code=422)
    try:
        version = request.app.state.publish.execute(
            TenantContext(tenant_id=request.app.state.tenant_id),
            PublishInput(reason=reason.strip(), idempotency_key=str(uuid4())),
        )
    except (DomainError, ApplicationError) as error:
        return _page(request, deposit=deposit, reason=reason, refusal=error.sentence, status_code=422)
    return RedirectResponse(f"/editor?published={version.value}", status_code=303)


def _store(request: Request, deposit: str) -> tuple[str, ...]:
    """Put the typed percent on the draft and return what `validate_policy` says about it."""
    if _WHOLE.fullmatch(deposit) is None:
        return (_NOT_A_NUMBER,)
    state = request.app.state
    draft = state.policies.draft(state.tenant_id)
    if draft is None:
        return ()
    draft = draft.model_copy(update={"deposit_percent": int(deposit)})
    state.policies.save_draft(state.tenant_id, draft)
    return _sentences(draft)


def _sentences(draft) -> tuple[str, ...]:
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


def _page(
    request: Request,
    deposit: str = "",
    reason: str = "",
    errors: tuple[str, ...] = (),
    refusal: str | None = None,
    published: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    state = request.app.state
    bundle = state.policies.published(state.tenant_id)
    draft = state.policies.draft(state.tenant_id)
    html = owner_templates().get_template("editor.html").render(
        page="editor",
        bundle=bundle,
        draft=draft,
        deposit=deposit,
        reason=reason,
        errors=errors,
        refusal=refusal,
        published=published,
        names=_item_names(state),
        ready=not errors and draft is not None and reason.strip() != "",
    )
    return HTMLResponse(html, status_code=status_code, headers={"Cache-Control": "no-store"})
