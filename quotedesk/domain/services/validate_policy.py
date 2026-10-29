import re

from quotedesk.domain.policy.draft import PolicyDraft, PolicyError

_TOKEN = re.compile(r"\{([A-Za-z0-9_]+)\}")
_LOCKED = frozenset({"WATER-E01", "WATER-E02", "WATER-E03", "FAB-E01", "FAB-E02", "FAB-E03"})
_QUESTION = "A required fact needs a question."
_PRICE = "A rate-card price must be greater than zero."
_DEPOSIT = "A deposit percent is a whole number from 0 to 99."
_CAP = "A discount cap is a percent from 0 to 100."
_VALIDITY = "Validity is at least one day."
_PLACEHOLDER = "A clause placeholder has no setting."
_VAT = "A rate card uses one VAT basis."
_DUPLICATE = "Each item code appears once on the rate card."
_EMPTY_CARD = "The rate card needs at least one item."
_LOCKED_SENTENCE = "A safety rule cannot be turned off."


def validate_policy(draft: PolicyDraft) -> tuple[PolicyError, ...]:
    errors: list[PolicyError] = []
    codes = {row.item_code for row in draft.rate_rows}
    for clause in draft.clauses:
        code = clause.variation_item_code
        if code is not None and code not in codes:
            errors.append(
                PolicyError(
                    code="policy.unknown_variation",
                    sentence=f"Clause {clause.clause_id} names a rate-card item that is not on the card.",
                    clause_id=clause.clause_id,
                )
            )
        for match in _TOKEN.finditer(clause.text):
            if match.group(1) not in draft.settings:
                errors.append(
                    PolicyError(
                        code="policy.placeholder",
                        sentence=_PLACEHOLDER,
                        clause_id=clause.clause_id,
                    )
                )
    for fact in draft.required_facts:
        if fact.question is None or fact.question.strip() == "":
            errors.append(PolicyError(code="policy.missing_question", sentence=_QUESTION))
    for row in draft.rate_rows:
        if row.unit_price <= 0:
            errors.append(PolicyError(code="policy.price", sentence=_PRICE))
    if not draft.rate_rows:
        errors.append(PolicyError(code="policy.empty_rate_card", sentence=_EMPTY_CARD))
    if len(codes) < len(draft.rate_rows):
        errors.append(PolicyError(code="policy.duplicate_item", sentence=_DUPLICATE))
    if draft.deposit_percent < 0 or draft.deposit_percent > 99:
        errors.append(PolicyError(code="policy.deposit_percent", sentence=_DEPOSIT))
    if draft.discount_cap_percent < 0 or draft.discount_cap_percent > 100:
        errors.append(PolicyError(code="policy.discount_cap", sentence=_CAP))
    if draft.validity_days < 1:
        errors.append(PolicyError(code="policy.validity_days", sentence=_VALIDITY))
    if len({row.vat_inclusive for row in draft.rate_rows}) > 1 or any(
        row.vat_inclusive is not draft.vat_inclusive for row in draft.rate_rows
    ):
        errors.append(PolicyError(code="policy.vat_basis", sentence=_VAT))
    for rule in draft.rules:
        if not rule.enabled and rule.rule_id in _LOCKED:
            errors.append(PolicyError(code="policy.locked_rule", sentence=_LOCKED_SENTENCE))
    return tuple(errors)
