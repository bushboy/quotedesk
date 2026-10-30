from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from quotedesk.application.dto.audit import AuditEvent
from quotedesk.application.dto.published import PublishedPolicy
from quotedesk.application.dto.tenant import TenantContext
from quotedesk.application.dto.tool_inputs import GetQuoteInput
from quotedesk.application.errors import CaseNotFound
from quotedesk.application.use_cases.tools.get_quote import GetQuote
from quotedesk.domain.case.case_file import CaseFile
from quotedesk.domain.policy.clauses import ClausePolicy
from quotedesk.domain.quotes.quote import Quote, QuoteState
from quotedesk.domain.services.price import RateCard, RateCardItem
from quotedesk.domain.shared.ids import PolicyVersionId, QuoteId
from quotedesk.domain.shared.money import Money
from tests.unit.domain.fabricator_policy import fabricator_policy
from tests.unit.domain.water_policy import aquasure_policy

TENANT_A = UUID("11111111-1111-4111-8111-111111111111")
TENANT_B = UUID("22222222-2222-4222-8222-222222222222")
CONVERSATION = UUID("33333333-3333-4333-8333-333333333333")
EVENT = UUID("44444444-4444-4444-8444-444444444444")
WHEN = datetime(2026, 10, 24, 0, 0, tzinfo=timezone.utc)

BASE = {
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
}


def card(unit_price: str = "4250.00") -> RateCard:
    return RateCard(
        vat_inclusive=True,
        site_visit_fee=Money("750.00"),
        items=(
            RateCardItem(
                item_code="TANK-5000",
                description="5000 L tank",
                unit_price=Money(unit_price),
            ),
        ),
    )


def clauses() -> ClausePolicy:
    return ClausePolicy(
        templates=(),
        settings={"deposit_percent": 30, "validity_days": 14},
        rate_card_codes=("TANK-5000",),
    )


def published(unit_price: str = "4250.00", policy=None) -> PublishedPolicy:
    return PublishedPolicy(
        policy=aquasure_policy() if policy is None else policy,
        rate_card=card(unit_price),
        clause_policy=clauses(),
    )


def build_case(values: dict[str, str], tenant_id: UUID = TENANT_A) -> CaseFile:
    case = CaseFile.open(CONVERSATION, tenant_id).add_job("tank", "replacement")
    for key, value in values.items():
        case = case.record_fact("tank", uuid4(), key, value, "customer_text", EVENT)
    return case


class Cases:
    def __init__(self, case: CaseFile | None, tenant_id: UUID = TENANT_A) -> None:
        self.case = case
        self.tenant_id = tenant_id
        self.seen: list[UUID] = []

    def get(self, tenant_id: UUID, conversation_id: UUID) -> CaseFile | None:
        self.seen.append(tenant_id)
        if tenant_id != self.tenant_id or self.case is None:
            return None
        return self.case


class Policies:
    def __init__(self, bundle: PublishedPolicy, draft: PublishedPolicy | None = None) -> None:
        self.bundle = bundle
        self.draft = draft

    def published(self, tenant_id: UUID) -> PublishedPolicy:
        return self.bundle


class Unit:
    def __init__(self, fail_audit: bool = False) -> None:
        self.fail_audit = fail_audit
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
        if self.fail_audit:
            raise RuntimeError("audit failed")
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
        return QuoteId("QD-1042")


def world(values: dict[str, str] | None = None, **kwargs: object):
    facts = BASE if values is None else values
    tenant = kwargs.pop("tenant_id", TENANT_A)
    cases = Cases(build_case(facts, tenant) if facts is not None else None, tenant)
    policies = Policies(kwargs.pop("bundle", published()), kwargs.pop("draft", None))
    unit = kwargs.pop("unit", Unit(fail_audit=bool(kwargs.pop("fail_audit", False))))
    ids = Ids()
    use_case = GetQuote(cases, policies, unit, Clock(), ids)
    return use_case, cases, unit, ids


def execute(values: dict[str, str] | None = None, **kwargs: object):
    use_case, cases, unit, ids = world(values, **kwargs)
    result = use_case.execute(TenantContext(tenant_id=TENANT_A), GetQuoteInput(conversation_id=CONVERSATION))
    return result, cases, unit, ids


def test_get_quote_fixed_offer_for_the_5000l_replacement():
    result, _, unit, _ = execute()
    assert result.rule_id.value == "WATER-F01"
    assert result.state is QuoteState.ISSUED
    assert result.schedule_status == "none"
    assert result.clauses == ()
    assert result.customer_template == "We can send a fixed quote for this replacement."
    assert len(result.lines) == 1
    assert result.lines[0].item_code == "TANK-5000"
    assert result.lines[0].total == Money("4250.00")
    assert result.total == Money("4250.00")
    assert result.expiry == datetime(2026, 11, 7).date()
    assert len(unit.audits) == 1
    assert unit.audits[0].action == "quote.issued"
    assert unit.audits[0].version == 1


def test_get_quote_rolls_back_when_audit_fails():
    use_case, _, unit, _ = world(fail_audit=True)
    with pytest.raises(RuntimeError):
        use_case.execute(TenantContext(tenant_id=TENANT_A), GetQuoteInput(conversation_id=CONVERSATION))
    assert unit.committed == {}
    assert unit.audits == []


def test_get_quote_uses_the_published_policy_only():
    draft = published("4999.00", aquasure_policy().model_copy(update={"version": PolicyVersionId("water-policy-v1.1")}))
    result, _, _, _ = execute(bundle=published(), draft=draft)
    assert result.policy_version.value == "water-policy-v1.0"
    assert result.total == Money("4250.00")
    assert draft.rate_card.items[0].unit_price == Money("4999.00")


def test_get_quote_low_confidence_has_no_price():
    values = dict(BASE)
    values["required_fields"] = "false"
    values["media_usable"] = "false"
    result, _, _, _ = execute(values)
    assert result.rule_id.value == "WATER-R02"
    assert result.outcome.value == "indicative_range"
    assert result.state is QuoteState.ISSUED
    assert result.lines == ()
    assert result.total is None
    assert result.range_min == Money("4250.00")
    assert result.range_max == Money("4250.00")
    assert result.deposit == Money("1275.00")
    assert result.site_visit_fee is None


def test_get_quote_hazard_has_no_price():
    values = dict(BASE)
    values["stand_condition"] = "leaning"
    values["simple_swap"] = "false"
    result, _, _, _ = execute(values)
    assert result.rule_id.value == "WATER-E02"
    assert result.state is QuoteState.SITE_ASSESSMENT_OFFERED
    assert result.customer_template == (
        "We'll book an inspection. The installation is damaged, and it is not clear this is a simple tank replacement."
    )
    assert result.site_visit_fee == Money("750.00")
    assert result.deposit is None
    assert result.lines == ()
    assert result.total is None


def test_a_stated_carport_size_prices_the_chosen_sheet():
    sheet = RateCard(
        vat_inclusive=True,
        site_visit_fee=Money("750.00"),
        items=(
            RateCardItem(item_code="SHEET-ECO", description="Economy sheeting", unit_price=Money("8500.00")),
            RateCardItem(item_code="SHEET-POLY", description="Polycarbonate sheeting", unit_price=Money("12400.00")),
        ),
    )
    bundle = PublishedPolicy(
        policy=fabricator_policy(),
        rate_card=sheet,
        clause_policy=ClausePolicy(
            templates=(),
            settings={"deposit_percent": 30, "validity_days": 14},
            rate_card_codes=("SHEET-ECO", "SHEET-POLY"),
        ),
    )
    result, _, _, _ = execute(
        {
            "item": "Economy sheeting",
            "size": "5 x 7 meters",
            "required_fields": "true",
            "agreement": "true",
            "measurement": "true",
            "media_usable": "true",
            "rate_card": "true",
        },
        bundle=bundle,
    )
    assert result.rule_id.value == "FAB-R02"
    assert result.range_min == Money("297500.00")
    assert result.range_max == Money("297500.00")
    assert result.deposit == Money("89250.00")


def test_a_stated_size_without_item_codes_is_still_indicative():
    result, _, _, _ = execute({"job": "swap", "tank_size": "5000l"})
    assert result.rule_id.value == "WATER-R02"
    assert result.range_min == Money("4250.00")
    assert result.range_max == Money("4250.00")


def test_a_confirmed_swap_is_quoted_even_when_the_stand_is_damaged():
    values = dict(BASE)
    values["stand_condition"] = "leaning"
    result, _, _, _ = execute(values)
    assert result.rule_id.value == "WATER-F01"
    assert result.total == Money("4250.00")


def test_get_quote_second_call_creates_version_two():
    values = dict(BASE)
    values["size_litres"] = "2500"
    use_case, cases, unit, ids = world(values)
    context = TenantContext(tenant_id=TENANT_A)
    data = GetQuoteInput(conversation_id=CONVERSATION)
    first = use_case.execute(context, data)
    assert first.version == 1
    cases.case = cases.case.record_fact("tank", uuid4(), "size_litres", "5000", "customer_text", EVENT)
    second = use_case.execute(context, data)
    stored = unit.get_quote(TENANT_A, CONVERSATION)
    assert second.version == 2
    assert second.state is QuoteState.ISSUED
    assert stored.version(1).state is QuoteState.REVISED
    assert stored.version(1).lines[0].total == Money("4250.00")
    assert stored.current.lines[0].total == Money("4250.00")
    assert ids.calls == 1
    assert unit.audits[-1].action == "quote.revised"
    assert unit.audits[-1].version == 2


def test_get_quote_is_tenant_scoped():
    use_case, cases, unit, _ = world(tenant_id=TENANT_B)
    with pytest.raises(CaseNotFound) as caught:
        use_case.execute(TenantContext(tenant_id=TENANT_A), GetQuoteInput(conversation_id=CONVERSATION))
    assert caught.value.code == "case.not_found"
    assert cases.seen == [TENANT_A]
    assert unit.committed == {}
    assert unit.audits == []


def test_get_quote_pins_policy_version():
    result, _, _, _ = execute()
    assert result.policy_version.value == "water-policy-v1.0"
    assert result.rule_id.value == "WATER-F01"
