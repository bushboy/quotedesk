"""Policy posts for the owner console: one deposit percent, one reason, one publish.

The draft is checked by `validate_policy` and published by `PublishPolicy`.
The form lives on the console page; this module never writes the published bundle itself.
"""

import re
from urllib.parse import quote
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from quotedesk.adapters.inbound.http.console import owner_page, policy_sentences, policy_view, read_form
from quotedesk.application.dto.tenant import TenantContext
from quotedesk.application.dto.tool_inputs import PublishInput
from quotedesk.application.errors import ApplicationError
from quotedesk.domain.shared.errors import DomainError

router = APIRouter()

_WHOLE = re.compile(r"-?\d{1,6}")
_NOT_A_NUMBER = "Type the deposit as a whole number, like 30."


@router.get("/editor")
def editor(published: str = "") -> RedirectResponse:
    query = f"?published={quote(published)}" if published else ""
    return RedirectResponse(f"/console{query}#policy", status_code=303)


@router.post("/editor/draft", response_model=None)
async def check(request: Request) -> HTMLResponse | JSONResponse:
    form = await read_form(request)
    deposit = form.get("deposit", "").strip()
    errors = _store(request, deposit)
    if "application/json" in request.headers.get("accept", ""):
        return JSONResponse({"errors": list(errors)}, headers={"Cache-Control": "no-store"})
    return owner_page(request, policy=policy_view(request, deposit=deposit, reason=form.get("reason", ""), errors=errors))


@router.post("/editor/publish", response_model=None)
async def publish(request: Request) -> HTMLResponse | RedirectResponse:
    form = await read_form(request)
    deposit = form.get("deposit", "").strip()
    reason = form.get("reason", "")
    errors = _store(request, deposit)
    if errors:
        view = policy_view(request, deposit=deposit, reason=reason, errors=errors)
        return owner_page(request, policy=view, status_code=422)
    try:
        version = request.app.state.publish.execute(
            TenantContext(tenant_id=request.app.state.tenant_id),
            PublishInput(reason=reason.strip(), idempotency_key=str(uuid4())),
        )
    except (DomainError, ApplicationError) as error:
        view = policy_view(request, deposit=deposit, reason=reason, errors=(), refusal=error.sentence)
        return owner_page(request, policy=view, status_code=422)
    return RedirectResponse(f"/console?published={version.value}#policy", status_code=303)


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
    return policy_sentences(draft)
