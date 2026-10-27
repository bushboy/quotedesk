from uuid import UUID

import pytest
from pydantic import ValidationError as ModelError

from quotedesk.application.dto.tenant import TenantContext
from quotedesk.application.dto.tool_inputs import FactInput, GetQuoteInput
from quotedesk.application.errors import TenantRequired
from quotedesk.application.use_cases.tools.get_quote import GetQuote
from quotedesk.domain.shared.errors import PolicyViolation

CONVERSATION = UUID("33333333-3333-4333-8333-333333333333")
TENANT_A = UUID("11111111-1111-4111-8111-111111111111")
EVENT = UUID("44444444-4444-4444-8444-444444444444")


def test_get_quote_input_forbids_commercial_fields():
    accepted = GetQuoteInput(conversation_id=CONVERSATION)
    assert accepted.conversation_id == CONVERSATION
    for field in ("unit_price", "outcome", "clause_text", "discount_percent"):
        with pytest.raises(ModelError):
            GetQuoteInput(conversation_id=CONVERSATION, **{field: "1"})


def test_tool_inputs_require_ids_not_prose():
    with pytest.raises(ModelError):
        GetQuoteInput()
    with pytest.raises(ModelError):
        FactInput()
    with pytest.raises(ModelError):
        FactInput(key="size_litres", value="5000", event_id=EVENT)
    with pytest.raises(ModelError):
        FactInput(
            key="size_litres",
            value="5000",
            source="customer_text",
            event_id=EVENT,
            prose="the tank is big",
        )
    accepted = FactInput(key="size_litres", value="5000", source="customer_text", event_id=EVENT)
    assert accepted.source == "customer_text"


class _Cases:
    def __init__(self) -> None:
        self.seen: list[UUID] = []

    def get(self, tenant_id: UUID, conversation_id: UUID):
        self.seen.append(tenant_id)
        return None


def test_tenant_context_is_required():
    cases = _Cases()
    use_case = GetQuote(cases, object(), object(), object(), object())
    with pytest.raises(TenantRequired) as caught:
        use_case.execute(None, GetQuoteInput(conversation_id=CONVERSATION))
    assert type(caught.value) is TenantRequired
    assert not isinstance(caught.value, PolicyViolation)
    assert caught.value.code == "tenant.required"
    assert caught.value.sentence == "A use case needs a tenant."
    assert cases.seen == []
    context = TenantContext(tenant_id=TENANT_A)
    with pytest.raises(Exception):
        use_case.execute(context, GetQuoteInput(conversation_id=CONVERSATION))
    assert cases.seen == [TENANT_A]
