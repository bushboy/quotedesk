from datetime import datetime, timezone
from uuid import UUID

from quotedesk.domain.conversation.events import Conversation
from quotedesk.domain.shared.errors import PolicyViolation
from tests.unit.domain.assertions import expect_domain

CONVERSATION = UUID("33333333-3333-4333-8333-333333333333")
EARLIER = datetime(2026, 10, 30, 8, 0, tzinfo=timezone.utc)
LATER = datetime(2026, 10, 30, 9, 0, tzinfo=timezone.utc)


def test_duplicate_provider_id_is_ignored():
    conversation = Conversation.open(CONVERSATION)
    first = conversation.append("wamid.1", EARLIER, "The tank is leaking.")
    assert first.duplicate is False
    second = first.conversation.append("wamid.1", LATER, "Again.")
    assert second.duplicate is True
    assert len(second.conversation.events) == 1
    assert second.conversation.events[0].body == "The tank is leaking."


def test_events_order_by_provider_timestamp():
    conversation = Conversation.open(CONVERSATION)
    conversation = conversation.append("wamid.later", LATER, "second").conversation
    conversation = conversation.append("wamid.earlier", EARLIER, "first").conversation
    assert [event.body for event in conversation.events] == ["first", "second"]


def test_events_are_append_only():
    conversation = Conversation.open(CONVERSATION).append("wamid.1", EARLIER, "The tank is leaking.").conversation
    expect_domain(
        lambda: conversation.replace_body("wamid.1", "A different body."),
        PolicyViolation,
        "policy.violation",
        "A message body is not edited.",
    )
    assert conversation.events[0].body == "The tank is leaking."


def test_enrichment_attaches_to_the_event():
    conversation = Conversation.open(CONVERSATION).append("wamid.1", EARLIER, "Listen.").conversation
    attached = conversation.attach("wamid.1", transcript_id="tr-1", extraction_id="ex-1")
    assert len(attached.events) == 1
    assert attached.events[0].transcript_id == "tr-1"
    assert attached.events[0].extraction_id == "ex-1"
    assert attached.events[0].body == "Listen."
