from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from quotedesk.application.dto.audit import AuditEvent
from quotedesk.application.dto.published import PublishedPolicy
from quotedesk.application.dto.tenant import TenantContext
from quotedesk.application.dto.tool_inputs import GetQuoteInput, PublishInput, RollbackInput
from quotedesk.application.errors import TenantRequired
from quotedesk.application.use_cases.editor.publish_policy import PublishPolicy
from quotedesk.application.use_cases.editor.rollback_policy import RollbackPolicy
from quotedesk.application.use_cases.tools.get_quote import GetQuote
from quotedesk.domain.case.case_file import CaseFile
from quotedesk.domain.policy.clauses import ClausePolicy, ClauseTemplate
from quotedesk.domain.policy.draft import DraftClause, DraftRateRow, DraftRule, PolicyDraft, RequiredFact
from quotedesk.domain.quotes.quote import Quote
from quotedesk.domain.services.price import RateCard, RateCardItem
from quotedesk.domain.shared.errors import PolicyViolation, ValidationError
from quotedesk.domain.shared.ids import PolicyVersionId, QuoteId
from quotedesk.domain.shared.money import Money
from tests.unit.domain.test_clauses import ROWS
from tests.unit.domain.water_policy import aquasure_policy

TENANT = UUID("11111111-1111-4111-8111-111111111111")
FIRST = UUID("33333333-3333-4333-8333-333333333333")
SECOND = UUID("44444444-4444-4444-8444-444444444444")
EVENT = UUID("55555555-5555-4555-8555-555555555555")
WHEN = datetime(2026, 11, 1, 8, 0, tzinfo=timezone.utc)
FACTS = {
    "job": "replacement",
    "size_litres": "5000",
    "size_source": "customer_stated",
    "existing_level_base": "true",
    "item_codes": "TANK-5000",
    "required_fields": "true",
    "agreement": "true",
    "measurement": "true",
    "media_usable": "true",
    "rate_card": "true",
    "width_m": "6.0",
    "length_m": "7.0",
    "job_type": "carport",
}


class Library:
    def __init__(self, bundle: PublishedPolicy, draft: PolicyDraft) -> None:
        self.current = bundle
        self.versions = {bundle.policy.version.value: bundle}
        self.draft_bundle = draft
        self.keys: dict[tuple[UUID, str], PolicyVersionId] = {}

    def published(self, _tenant_id: UUID) -> PublishedPolicy:
        return self.current

    def draft(self, _tenant_id: UUID) -> PolicyDraft:
        return self.draft_bundle

    def get(self, _tenant_id: UUID, version_id: PolicyVersionId) -> PublishedPolicy | None:
        return self.versions.get(version_id.value)

    def save_published(self, _tenant_id: UUID, bundle: PublishedPolicy) -> None:
        self.current = bundle
        self.versions[bundle.policy.version.value] = bundle

    def find_publish(self, tenant_id: UUID, key: str) -> PolicyVersionId | None:
        return self.keys.get((tenant_id, key))

    def remember_publish(self, tenant_id: UUID, key: str, version: PolicyVersionId) -> None:
        self.keys[(tenant_id, key)] = version


class Cases:
    def __init__(self) -> None:
        self.rows = {
            (TENANT, FIRST): _case(FIRST),
            (TENANT, SECOND): _case(SECOND),
        }

    def get(self, tenant_id: UUID, conversation_id: UUID) -> CaseFile | None:
        return self.rows.get((tenant_id, conversation_id))


class Unit:
    def __init__(self) -> None:
        self.committed: dict[tuple[UUID, UUID], Quote] = {}
        self.audits: list[AuditEvent] = []
        self._pending_key: tuple[UUID, UUID] | None = None
        self._pending_quote: Quote | None = None
        self._pending_audit: AuditEvent | None = None

    def get_quote(self, tenant_id: UUID, conversation_id: UUID) -> Quote | None:
        return self.committed.get((tenant_id, conversation_id))

    def save_quote(self, tenant_id: UUID, conversation_id: UUID, quote: Quote) -> None:
        self._pending_key = (tenant_id, conversation_id)
        self._pending_quote = quote

    def record_audit(self, event: AuditEvent) -> None:
        self._pending_audit = event

    def commit(self) -> None:
        if self._pending_key is not None and self._pending_quote is not None:
            self.committed[self._pending_key] = self._pending_quote
        if self._pending_audit is not None:
            self.audits.append(self._pending_audit)
        self.rollback()

    def rollback(self) -> None:
        self._pending_key = None
        self._pending_quote = None
        self._pending_audit = None


class Clock:
    def now(self) -> datetime:
        return WHEN


class Ids:
    def __init__(self) -> None:
        self.calls = 0

    def next_quote_id(self) -> QuoteId:
        self.calls += 1
        return QuoteId(f"QD-{self.calls:04d}")


def _case(conversation_id: UUID) -> CaseFile:
    case = CaseFile.open(conversation_id, TENANT).add_job("tank", "replacement")
    for key, value in FACTS.items():
        case = case.record_fact("tank", uuid4(), key, value, "customer_text", EVENT)
    return case


def _clauses(deposit: int) -> ClausePolicy:
    templates = tuple(
        ClauseTemplate(
            clause_id=clause_id,
            clause_version="1",
            kind=kind,
            text=text,
            if_not_true=if_not_true,
            variation_item_code=variation,
        )
        for clause_id, kind, text, if_not_true, variation in ROWS
    )
    return ClausePolicy(
        templates=templates,
        settings={"deposit_percent": deposit, "validity_days": 14},
        rate_card_codes=("HEIGHT-EXTRA", "TANK-5000"),
    )


def _bundle(deposit: int) -> PublishedPolicy:
    return PublishedPolicy(
        policy=aquasure_policy(),
        rate_card=RateCard(
            vat_inclusive=True,
            site_visit_fee=Money("450.00"),
            items=(
                RateCardItem(item_code="TANK-5000", description="5000 L tank", unit_price=Money("4250.00")),
                RateCardItem(item_code="HEIGHT-EXTRA", description="Extra height", unit_price=Money("100.00")),
            ),
        ),
        clause_policy=_clauses(deposit),
    )


def _draft(
    deposit: int = 40,
    clauses: tuple[DraftClause, ...] = (),
    rules: tuple[DraftRule, ...] | None = None,
) -> PolicyDraft:
    return PolicyDraft(
        deposit_percent=deposit,
        discount_cap_percent=5,
        validity_days=14,
        vat_inclusive=True,
        rate_rows=(
            DraftRateRow(item_code="TANK-5000", unit_price=Decimal("4250.00"), vat_inclusive=True),
            DraftRateRow(item_code="HEIGHT-EXTRA", unit_price=Decimal("100.00"), vat_inclusive=True),
        ),
        clauses=clauses,
        required_facts=(RequiredFact(key="width_m", question="What is the width?"),),
        rules=(DraftRule(rule_id="WATER-E01", enabled=True),) if rules is None else rules,
        settings=("deposit_percent", "validity_days"),
    )


def _world(deposit: int = 30, draft: PolicyDraft | None = None):
    library = Library(_bundle(deposit), _draft() if draft is None else draft)
    unit = Unit()
    quotes = GetQuote(Cases(), library, unit, Clock(), Ids())
    return library, unit, quotes


def _issue(quotes: GetQuote, conversation_id: UUID):
    return quotes.execute(TenantContext(tenant_id=TENANT), GetQuoteInput(conversation_id=conversation_id))


def _publish(library: Library, unit: Unit, reason: str = "Raise the deposit.", key: str = "publish-1"):
    return PublishPolicy(library, unit, Clock()).execute(
        TenantContext(tenant_id=TENANT), PublishInput(reason=reason, idempotency_key=key)
    )


def test_draft_does_not_change_live_decide() -> None:
    library, _, quotes = _world(30, _draft(40))
    result = _issue(quotes, FIRST)

    assert any("30%" in clause.text for clause in result.clauses)
    assert result.policy_version == PolicyVersionId("water-policy-v1.0")
    assert library.published(TENANT).clause_policy.settings["deposit_percent"] == 30


def test_invalid_draft_cannot_publish() -> None:
    missing = _draft(clauses=(DraftClause(clause_id="CARPORT-A2", text="Extra height.", variation_item_code="GONE"),))
    library, unit, _ = _world(30, missing)
    with pytest.raises(PolicyViolation, match="CARPORT-A2"):
        _publish(library, unit, "Name a missing item.")
    assert library.published(TENANT).policy.version == PolicyVersionId("water-policy-v1.0")

    fresh, fresh_unit, _ = _world()
    with pytest.raises(ValidationError, match="A publish needs a reason."):
        _publish(fresh, fresh_unit, "   ", "publish-2")
    assert fresh.published(TENANT).policy.version == PolicyVersionId("water-policy-v1.0")


def test_publish_requires_a_reason_and_is_idempotent() -> None:
    library, unit, _ = _world()
    with pytest.raises(ValidationError, match="A publish needs a reason.") as blank:
        _publish(library, unit, " ", "publish-blank")
    assert blank.value.code == "publish.reason"
    assert library.get(TENANT, PolicyVersionId("water-policy-v1.1")) is None

    first = _publish(library, unit)
    second = _publish(library, unit)
    assert first == PolicyVersionId("water-policy-v1.1")
    assert second == first
    assert library.get(TENANT, PolicyVersionId("water-policy-v1.2")) is None


def test_publish_leaves_issued_quotes_on_their_version() -> None:
    library, unit, quotes = _world(30, _draft(40))
    issued = _issue(quotes, FIRST)
    version = _publish(library, unit)
    again = _issue(quotes, SECOND)
    stored = unit.get_quote(TENANT, FIRST)

    assert version == PolicyVersionId("water-policy-v1.1")
    assert library.get(TENANT, PolicyVersionId("water-policy-v1.0")) is not None
    assert stored is not None
    assert any("30%" in clause.text for clause in stored.current.clauses)
    assert issued.policy_version == PolicyVersionId("water-policy-v1.0")
    assert again.policy_version == PolicyVersionId("water-policy-v1.1")
    assert any("40%" in clause.text for clause in again.clauses)
    assert any(
        clause.text == "No installation date is reserved until the 40% deposit is paid." for clause in again.clauses
    )


def test_rollback_republishes_as_a_new_version() -> None:
    library, unit, _ = _world(30, _draft(40))
    _publish(library, unit)
    rollback = RollbackPolicy(library, unit, Clock())
    with pytest.raises(ValidationError, match="A publish needs a reason."):
        rollback.execute(
            TenantContext(tenant_id=TENANT),
            RollbackInput(source_version=PolicyVersionId("water-policy-v1.0"), reason=" ", idempotency_key="rollback-1"),
        )
    assert library.get(TENANT, PolicyVersionId("water-policy-v1.2")) is None

    version = rollback.execute(
        TenantContext(tenant_id=TENANT),
        RollbackInput(
            source_version=PolicyVersionId("water-policy-v1.0"),
            reason="Restore the deposit.",
            idempotency_key="rollback-1",
        ),
    )
    again = rollback.execute(
        TenantContext(tenant_id=TENANT),
        RollbackInput(
            source_version=PolicyVersionId("water-policy-v1.0"),
            reason="Restore the deposit.",
            idempotency_key="rollback-1",
        ),
    )

    assert version == PolicyVersionId("water-policy-v1.2")
    assert again == version
    assert library.published(TENANT).clause_policy.settings["deposit_percent"] == 30
    assert library.get(TENANT, PolicyVersionId("water-policy-v1.0")).clause_policy.settings["deposit_percent"] == 30
    assert library.get(TENANT, PolicyVersionId("water-policy-v1.1")).clause_policy.settings["deposit_percent"] == 40
    assert [rule.rule_id for rule in library.published(TENANT).policy.rules] == [
        rule.rule_id for rule in aquasure_policy().rules
    ]


def test_locked_rule_rejected_by_the_use_case() -> None:
    library, unit, _ = _world(30, _draft(rules=(DraftRule(rule_id="WATER-E01", enabled=False),)))
    with pytest.raises(PolicyViolation, match="A safety rule cannot be turned off.") as raised:
        _publish(library, unit, "Disable a safety rule.")
    assert raised.value.code == "policy.violation"
    published = library.published(TENANT)
    assert published.policy.version == PolicyVersionId("water-policy-v1.0")
    assert any(rule.rule_id.value == "WATER-E01" for rule in published.policy.rules)


def test_publish_requires_a_tenant() -> None:
    library, unit, _ = _world()
    with pytest.raises(TenantRequired):
        PublishPolicy(library, unit, Clock()).execute(None, PublishInput(reason="Raise the deposit.", idempotency_key="publish-1"))
