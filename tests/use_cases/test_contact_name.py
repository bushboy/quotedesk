"""A stated name is kept, and a number without one is asked."""

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

from quotedesk.application.use_cases.conversation.run_agent_turn import NAME_ASK, remember_name, with_name
from quotedesk.infrastructure.demo import Conversations

TENANT = UUID("11111111-1111-4111-8111-111111111111")
CONVERSATION = UUID("33333333-3333-4333-8333-333333333333")
WHEN = datetime(2026, 10, 30, 8, 0, tzinfo=timezone.utc)
WA = "27821234567"


def _event(body: str):
    return SimpleNamespace(body=body)


def test_an_introduction_is_stored_and_not_asked_again():
    store = Conversations()
    store.bind(TENANT, WA, CONVERSATION)
    remember_name(store, TENANT, CONVERSATION, WA, (_event("My name is Lerato Mokoena, please quote a tank"),))
    assert store.name(TENANT, WA) == "Lerato Mokoena"
    assert with_name(store, TENANT, WA, "The total is R 4 250.") == "The total is R 4 250."


def test_a_short_reply_after_the_question_is_the_name():
    store = Conversations()
    store.bind(TENANT, WA, CONVERSATION)
    store.record_reply(TENANT, CONVERSATION, WHEN, f"The total is R 4 250. {NAME_ASK}")
    remember_name(store, TENANT, CONVERSATION, WA, (_event("Lerato"),))
    assert store.name(TENANT, WA) == "Lerato"


def test_a_job_request_is_not_stored_as_a_name():
    store = Conversations()
    store.bind(TENANT, WA, CONVERSATION)
    remember_name(store, TENANT, CONVERSATION, WA, (_event("Please quote a 5000 L replacement."),))
    assert store.name(TENANT, WA) is None
    assert with_name(store, TENANT, WA, "Thanks.") == f"Thanks. {NAME_ASK}"


def test_yes_after_the_question_is_not_a_name():
    store = Conversations()
    store.bind(TENANT, WA, CONVERSATION)
    store.record_reply(TENANT, CONVERSATION, WHEN, NAME_ASK)
    remember_name(store, TENANT, CONVERSATION, WA, (_event("Yes"),))
    assert store.name(TENANT, WA) is None
