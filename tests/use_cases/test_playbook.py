from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import yaml

from quotedesk.application.dto.tenant import TenantContext
from quotedesk.application.dto.tool_inputs import PublishInput, RollbackInput
from quotedesk.application.prompts import render_task
from quotedesk.application.use_cases.editor.publish_policy import PublishPolicy
from quotedesk.application.use_cases.editor.rollback_policy import RollbackPolicy
from quotedesk.domain.policy.playbook import BusinessPlaybook, EscalationTrigger, FactDefinition, JobTypePlay
from quotedesk.domain.services.validate_policy import validate_policy
from quotedesk.domain.shared.ids import PolicyVersionId
from quotedesk.infrastructure.demo import Catalog, Policies, policy_draft, published_bundle
from tests.unit.domain.test_validate_policy import _draft

TENANT = UUID("11111111-1111-4111-8111-111111111111")


class Clock:
    def now(self) -> datetime:
        return datetime(2026, 10, 30, tzinfo=timezone.utc)


class Unit:
    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None


def test_a_third_trade_gets_its_own_question():
    doors = BusinessPlaybook(
        name="Oakmere Doors",
        trade="doors",
        job_types=(
            JobTypePlay(
                key="door",
                description="Hang a door",
                facts=(
                    FactDefinition(
                        key="width_mm",
                        type="number",
                        question="What is the opening width?",
                        required=True,
                    ),
                ),
            ),
        ),
    )
    task = render_task(doors)
    assert "What is the opening width?" in task
    assert "water tank" not in task.casefold()
    assert "carport" not in task.casefold()
    assert Catalog(doors).required("door") == ("width_mm",)


def test_frameworks_has_required_facts_and_a_bare_catalog_does_not_change():
    book = published_bundle()
    assert Catalog().required("replacement") == ("size_litres", "existing_level_base")
    from quotedesk.infrastructure.demo import bundle_for

    frames = bundle_for("frameworks").playbook
    assert frames.required("carport") == ("width_m", "length_m", "sheet")
    sheet = next(fact for fact in frames.job_types[0].facts if fact.key == "sheet")
    assert sheet.required is True
    assert sheet.options[0].label == "Economy sheeting"
    assert sheet.options[0].item_codes == ("SHEET-ECO",)
    assert "tank" not in frames.guidance.casefold()
    assert book.playbook.required("replacement") == ("size_litres", "existing_level_base")


def test_rollback_restores_the_previous_question():
    bundle = published_bundle()
    original = bundle.playbook.job_types[0].facts[0].question
    job = bundle.playbook.job_types[0]
    changed = job.facts[0].model_copy(update={"question": "Changed question?"})
    book = bundle.playbook.model_copy(
        update={"job_types": (job.model_copy(update={"facts": (changed,) + job.facts[1:]}),)}
    )
    policies = Policies(bundle)
    policies.save_draft(TENANT, policy_draft(bundle, Decimal("5")).model_copy(update={"playbook": book}))
    context = TenantContext(tenant_id=TENANT)
    PublishPolicy(policies, Unit(), Clock()).execute(
        context, PublishInput(reason="Change the size question.", idempotency_key="pub-1")
    )
    assert policies.published(TENANT).playbook.job_types[0].facts[0].question == "Changed question?"
    RollbackPolicy(policies, Unit(), Clock()).execute(
        context,
        RollbackInput(
            source_version=PolicyVersionId("water-policy-v1.0"),
            reason="Restore the previous question.",
            idempotency_key="rb-1",
        ),
    )
    assert policies.published(TENANT).playbook.job_types[0].facts[0].question == original


def test_a_playbook_field_over_the_cap_is_rejected():
    draft = _draft(
        playbook=BusinessPlaybook(
            guidance="x" * 4001,
            job_types=(JobTypePlay(key="replacement", item_codes=("TANK-5000",)),),
        )
    )
    assert "policy.playbook_length" in {error.code for error in validate_policy(draft)}


def test_a_playbook_item_and_rule_must_exist():
    draft = _draft(
        playbook=BusinessPlaybook(
            job_types=(
                JobTypePlay(
                    key="replacement",
                    item_codes=("GONE",),
                    facts=(
                        FactDefinition(key="size_litres", question="", required=True),
                        FactDefinition(key="size_litres", question="Again?", required=True),
                    ),
                ),
            ),
            escalations=(),
        )
    )
    draft = draft.model_copy(
        update={
            "playbook": draft.playbook.model_copy(
                update={"escalations": (EscalationTrigger(condition="unknown", rule_id="NO-SUCH"),)}
            )
        }
    )
    codes = {error.code for error in validate_policy(draft)}
    assert "policy.playbook_item" in codes
    assert "policy.playbook_question" in codes
    assert "policy.playbook_fact" in codes
    assert "policy.playbook_rule" in codes


def test_each_business_has_ten_draft_conversations():
    for name in ("aquasure", "frameworks"):
        raw = yaml.safe_load(Path(f"eval/conversations/{name}.yaml").read_text(encoding="utf-8"))
        rows = raw["conversations"]
        assert len(rows) == 10
        for row in rows:
            assert row["expected_outcome"]
            assert "rule_id" in row
            assert "required_facts" in row
            assert isinstance(row["forbidden"], list)


def test_seeded_drafts_validate():
    from quotedesk.infrastructure.demo import bundle_for

    for bundle in (published_bundle(), bundle_for("frameworks")):
        assert validate_policy(policy_draft(bundle, Decimal("5"))) == ()
