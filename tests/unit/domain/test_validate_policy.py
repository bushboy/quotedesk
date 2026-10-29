from decimal import Decimal

from quotedesk.domain.policy.draft import DraftClause, DraftRateRow, DraftRule, PolicyDraft, RequiredFact
from quotedesk.domain.services.validate_policy import validate_policy


def _draft(**updates: object) -> PolicyDraft:
    base = PolicyDraft(
        deposit_percent=30,
        discount_cap_percent=5,
        validity_days=14,
        vat_inclusive=True,
        rate_rows=(DraftRateRow(item_code="TANK-5000", unit_price=Decimal("4250.00"), vat_inclusive=True),),
        clauses=(DraftClause(clause_id="GEN-S1", text="Deposit {deposit_percent}%."),),
        required_facts=(RequiredFact(key="width_m", question="What is the width?"),),
        rules=(DraftRule(rule_id="WATER-E01", enabled=True),),
        settings=("deposit_percent",),
    )
    return base.model_copy(update=updates)


def _codes(draft: PolicyDraft) -> set[str]:
    return {error.code for error in validate_policy(draft)}


def test_validate_variation_item_must_exist() -> None:
    draft = _draft(
        clauses=(DraftClause(clause_id="CARPORT-A2", text="Extra height.", variation_item_code="GONE"),)
    )
    errors = validate_policy(draft)
    assert errors[0].code == "policy.unknown_variation"
    assert errors[0].clause_id == "CARPORT-A2"
    assert "CARPORT-A2" in errors[0].sentence


def test_validate_required_fact_has_a_question() -> None:
    draft = _draft(
        required_facts=(
            RequiredFact(key="width_m", question=None),
            RequiredFact(key="length_m", question="  "),
        )
    )
    errors = validate_policy(draft)
    assert len(errors) == 2
    assert {error.code for error in errors} == {"policy.missing_question"}
    assert {error.sentence for error in errors} == {"A required fact needs a question."}


def test_validate_prices_and_settings_ranges() -> None:
    assert validate_policy(_draft()) == ()
    assert validate_policy(_draft(deposit_percent=0)) == ()
    assert validate_policy(_draft(deposit_percent=99)) == ()
    assert validate_policy(_draft(discount_cap_percent=0)) == ()
    assert validate_policy(_draft(discount_cap_percent=100)) == ()
    for price in (Decimal("0"), Decimal("-1")):
        priced = _draft(rate_rows=(DraftRateRow(item_code="TANK-5000", unit_price=price, vat_inclusive=True),))
        assert "policy.price" in _codes(priced)
        assert any(error.sentence == "A rate-card price must be greater than zero." for error in validate_policy(priced))
    for deposit in (-1, 100):
        assert "policy.deposit_percent" in _codes(_draft(deposit_percent=deposit))
    assert "policy.discount_cap" in _codes(_draft(discount_cap_percent=101))
    assert "policy.validity_days" in _codes(_draft(validity_days=0))


def test_validate_placeholders() -> None:
    draft = _draft(clauses=(DraftClause(clause_id="GEN-S1", text="Wait {unknown_token} days."),))
    errors = validate_policy(draft)
    assert errors[0].code == "policy.placeholder"
    assert errors[0].clause_id == "GEN-S1"
    assert errors[0].sentence == "A clause placeholder has no setting."
    assert validate_policy(_draft()) == ()


def test_validate_single_vat_basis() -> None:
    mixed = _draft(
        rate_rows=(
            DraftRateRow(item_code="TANK-5000", unit_price=Decimal("4250.00"), vat_inclusive=True),
            DraftRateRow(item_code="PUMP-1", unit_price=Decimal("1800.00"), vat_inclusive=False),
        )
    )
    assert "policy.vat_basis" in _codes(mixed)
    assert any(error.sentence == "A rate card uses one VAT basis." for error in validate_policy(mixed))
    uniform = _draft(
        vat_inclusive=False,
        rate_rows=(
            DraftRateRow(item_code="TANK-5000", unit_price=Decimal("4250.00"), vat_inclusive=False),
            DraftRateRow(item_code="PUMP-1", unit_price=Decimal("1800.00"), vat_inclusive=False),
        ),
    )
    assert validate_policy(uniform) == ()


def test_validate_locked_rules_cannot_be_disabled() -> None:
    for rule_id in ("WATER-E01", "WATER-E02", "WATER-E03", "FAB-E01", "FAB-E02", "FAB-E03"):
        errors = validate_policy(_draft(rules=(DraftRule(rule_id=rule_id, enabled=False),)))
        assert "policy.locked_rule" in {error.code for error in errors}
        assert any(error.sentence == "A safety rule cannot be turned off." for error in errors)
    assert validate_policy(_draft(rules=(DraftRule(rule_id="WATER-E01", enabled=True),))) == ()


def test_validate_rate_card_codes_are_unique_and_present() -> None:
    row = DraftRateRow(item_code="TANK-5000", unit_price=Decimal("4250.00"), vat_inclusive=True)
    assert "policy.duplicate_item" in _codes(_draft(rate_rows=(row, row)))
    assert "policy.empty_rate_card" in _codes(_draft(rate_rows=()))
    assert _codes(_draft()) == set()
