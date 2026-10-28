from quotedesk.application.dto.agent import ModelReply, ToolCall
from quotedesk.application.dto.published import PublishedPolicy
from quotedesk.domain.policy.clauses import ClausePolicy
from quotedesk.domain.services.price import RateCard, RateCardItem
from quotedesk.domain.shared.money import Money
from quotedesk.infrastructure.config import Settings
from quotedesk.infrastructure.demo import CONVERSATION, TENANT_A, install
from quotedesk.infrastructure.main import create_app
from harness.runner import run
from tests.unit.domain.water_policy import aquasure_policy

EVENT = "44444444-4444-4444-8444-444444444444"


def bundle() -> PublishedPolicy:
    return PublishedPolicy(
        policy=aquasure_policy(),
        rate_card=RateCard(
            vat_inclusive=True,
            site_visit_fee=Money("750.00"),
            items=(
                RateCardItem(
                    item_code="TANK-5000",
                    description="5000 L tank",
                    unit_price=Money("4250.00"),
                ),
            ),
        ),
        clause_policy=ClausePolicy(
            templates=(),
            settings={"deposit_percent": 30, "validity_days": 14},
            rate_card_codes=("TANK-5000",),
        ),
    )


def app():
    application = create_app(Settings(database_url="postgresql://quotedesk:quotedesk@127.0.0.1:1/quotedesk"))
    install(application, bundle())
    return application


def test_harness_posts_a_text_scenario(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    application = app()
    report = run(application, "harness/scenarios/text.yaml")
    assert report.responses == ((200, ""),)
    assert "The tank in the yard is leaking." not in report.responses[0][1]
    stored = application.state.conversations.get(TENANT_A, CONVERSATION)
    assert stored is not None
    assert len(stored.log) == 1
    assert stored.log[0].provider_message_id == "wamid.TEXT1"
    assert stored.log[0].body == "The tank in the yard is leaking."
    assert report.outbox[0]["body"] == "Thanks."
    assert report.outbox[0]["status"] == "pending"
    assert report.outbox[0]["id"] == 1
    assert report.outbox[0]["wa_id"] == "15550002222"
    assert "The tank in the yard is leaking." not in report.outbox[0]["body"]


def test_harness_s08_duplicate_and_order(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    application = app()
    run(application, "harness/scenarios/s08.yaml")
    stored = application.state.conversations.get(TENANT_A, CONVERSATION)
    assert stored is not None
    assert len(stored.log) == 3
    assert [event.provider_message_id for event in stored.events] == [
        "wamid.S08A",
        "wamid.S08B",
        "wamid.S08C",
    ]


def test_harness_fixed_offer_replies_with_the_tool_amount(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    application = app()

    class Script:
        def complete(self, prompt):
            return ModelReply(
                text="The total is R 4 250.",
                tool_calls=(
                    ToolCall(
                        name="update_case",
                        arguments={
                            "conversation_id": str(CONVERSATION),
                            "job_id": "tank",
                            "job_type": "replacement",
                            "facts": [
                                {"key": "job", "value": "replacement", "source": "customer_text", "event_id": EVENT},
                                {"key": "size_litres", "value": "5000", "source": "customer_text", "event_id": EVENT},
                                {
                                    "key": "size_source",
                                    "value": "customer_stated",
                                    "source": "customer_text",
                                    "event_id": EVENT,
                                },
                                {
                                    "key": "existing_level_base",
                                    "value": "true",
                                    "source": "customer_text",
                                    "event_id": EVENT,
                                },
                                {
                                    "key": "item_codes",
                                    "value": "TANK-5000",
                                    "source": "customer_text",
                                    "event_id": EVENT,
                                },
                                {
                                    "key": "required_fields",
                                    "value": "true",
                                    "source": "customer_text",
                                    "event_id": EVENT,
                                },
                                {"key": "agreement", "value": "true", "source": "customer_text", "event_id": EVENT},
                                {"key": "measurement", "value": "true", "source": "customer_text", "event_id": EVENT},
                                {"key": "media_usable", "value": "true", "source": "customer_text", "event_id": EVENT},
                                {"key": "rate_card", "value": "true", "source": "customer_text", "event_id": EVENT},
                                {
                                    "key": "photo_note",
                                    "value": "tank on a sound base",
                                    "source": "photo_extraction",
                                    "event_id": EVENT,
                                },
                            ],
                        },
                    ),
                    ToolCall(name="get_quote", arguments={"conversation_id": str(CONVERSATION)}),
                ),
            )

    application.state.slot.model = Script()
    report = run(application, "harness/scenarios/aquasure_5000l.yaml")
    bodies = " ".join(row["body"] for row in report.outbox)
    assert "R 4 250" in bodies
    assert "R 3" not in bodies
    assert bodies.count("R ") == 1
    assert len(application.state.unit.committed) == 1
    facts = report.case.facts("tank")
    assert any(fact.source == "photo_extraction" and fact.value == "tank on a sound base" for fact in facts)
