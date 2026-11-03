"""A stated name is kept, and a number without one is asked."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID

from quotedesk.application.dto.inbound import InboundMessage
from quotedesk.application.use_cases.conversation.run_agent_turn import (
    NAME_ASK,
    _apply_name,
    keep_profile_name,
    remember_name,
    with_name,
)
from quotedesk.domain.case.case_file import CaseFile
from quotedesk.domain.services.plan import NextStep, StepKind
from quotedesk.infrastructure.demo import Conversations

TENANT = UUID("11111111-1111-4111-8111-111111111111")
CONVERSATION = UUID("33333333-3333-4333-8333-333333333333")
WHEN = datetime(2026, 10, 30, 8, 0, tzinfo=timezone.utc)
WA = "27821234567"


def _event(body: str):
    return SimpleNamespace(body=body)


def test_a_profile_name_is_kept_and_not_asked_again():
    store = Conversations()
    store.bind(TENANT, WA, CONVERSATION)
    keep_profile_name(store, TENANT, WA, "Thabo")
    assert store.name(TENANT, WA) == "Thabo"
    assert with_name(store, TENANT, WA, "Thanks.") == "Thanks."
    remember_name(store, TENANT, CONVERSATION, WA, (_event("Please quote a 5000 L replacement."),))
    assert store.name(TENANT, WA) == "Thabo"


def test_my_name_without_is_replaces_the_stored_name():
    store = Conversations()
    store.bind(TENANT, WA, CONVERSATION)
    keep_profile_name(store, TENANT, WA, "Thabo")
    remember_name(
        store,
        TENANT,
        CONVERSATION,
        WA,
        (_event("Hello. My name Joshua. Please quote me on a carport to sit in front of a single garage."),),
    )
    assert store.name(TENANT, WA) == "Joshua"


def test_an_introduction_replaces_the_profile_name():
    store = Conversations()
    store.bind(TENANT, WA, CONVERSATION)
    keep_profile_name(store, TENANT, WA, "Thabo")
    remember_name(store, TENANT, CONVERSATION, WA, (_event("My name is Lerato Mokoena, please quote a tank"),))
    assert store.name(TENANT, WA) == "Lerato Mokoena"


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
    assert with_name(store, TENANT, WA, "Thanks.") == "Thanks."


def test_a_sheet_we_just_offered_is_not_stored_as_a_name():
    store = Conversations()
    store.bind(TENANT, WA, CONVERSATION)
    store.record_reply(
        TENANT,
        CONVERSATION,
        WHEN,
        f"We offer Polycarbonate sheeting. Which sheet are you interested in? {NAME_ASK}",
    )
    remember_name(store, TENANT, CONVERSATION, WA, (_event("Polycarbonate"),))
    assert store.name(TENANT, WA) is None


def test_use_the_name_is_stored_and_not_asked_again():
    store = Conversations()
    store.bind(TENANT, WA, CONVERSATION)
    remember_name(
        store,
        TENANT,
        CONVERSATION,
        WA,
        (_event("Use the name Fabian. I want insulated roof sheeting."),),
    )
    assert store.name(TENANT, WA) == "Fabian"
    assert with_name(store, TENANT, WA, "Is that the spec to price? Reply yes or no.") == (
        "Is that the spec to price? Reply yes or no."
    )


def test_yes_after_the_question_is_not_a_name():
    store = Conversations()
    store.bind(TENANT, WA, CONVERSATION)
    store.record_reply(TENANT, CONVERSATION, WHEN, NAME_ASK)
    remember_name(store, TENANT, CONVERSATION, WA, (_event("Yes"),))
    assert store.name(TENANT, WA) is None


def _named_thread(store: Conversations, *turns: tuple[datetime, str, str]) -> None:
    store.bind(TENANT, WA, CONVERSATION)
    store.rename(TENANT, WA, "Tseliso")
    for moment, side, body in turns:
        if side == "out":
            store.record_reply(TENANT, CONVERSATION, moment, body)
            continue
        store.remember(
            TENANT,
            InboundMessage(
                conversation_id=CONVERSATION,
                provider_message_id=f"wamid.{moment.timestamp()}",
                wa_id=WA,
                at=moment,
                kind="text",
                body=body,
            ),
        )


def test_an_introduced_name_is_used_without_asking():
    store = Conversations()
    _named_thread(store, (WHEN, "in", "My name is Tseliso"))
    step = NextStep(kind=StepKind.ASK, sentence="What can we help with: a carport?", fact_key="job_type")
    applied = _apply_name(
        SimpleNamespace(_conversations=store),
        SimpleNamespace(tenant_id=TENANT),
        CONVERSATION,
        CaseFile.open(CONVERSATION, TENANT),
        step,
    )
    assert applied.sentence == "What can we help with: a carport?"


def test_yes_to_the_name_lets_the_next_question_through():
    store = Conversations()
    asked = WHEN + timedelta(seconds=1)
    agreed = WHEN + timedelta(seconds=2)
    _named_thread(
        store,
        (WHEN, "in", "My name is Tseliso"),
        (asked, "out", "I'll use Tseliso. Is that right? Reply yes or no."),
        (agreed, "in", "Yes"),
    )
    step = NextStep(kind=StepKind.ASK, sentence="What can we help with: a carport?", fact_key="job_type")
    applied = _apply_name(
        SimpleNamespace(_conversations=store),
        SimpleNamespace(tenant_id=TENANT),
        CONVERSATION,
        CaseFile.open(CONVERSATION, TENANT),
        step,
    )
    assert applied.sentence == "What can we help with: a carport?"
