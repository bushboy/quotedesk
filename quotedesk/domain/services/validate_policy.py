import re

from pydantic import BaseModel

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
_FIELD_CAP = 4000
_LONG = "A playbook field is too long."
_PLAYBOOK_QUESTION = "A required playbook fact needs a question."
_UNKNOWN_ITEM = "A job type names a rate-card item that is not on the card."
_UNKNOWN_RULE = "A playbook trigger names a rule that is not on the policy."
_DUPLICATE_FACT = "A job type uses the same fact key twice."


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
    errors.extend(_playbook_errors(draft))
    return tuple(errors)


def _playbook_errors(draft: PolicyDraft) -> list[PolicyError]:
    book = draft.playbook
    if not book.populated() and not _over_cap(book):
        return []
    errors: list[PolicyError] = []
    rule_ids = {rule.rule_id for rule in draft.rules}
    codes = {row.item_code for row in draft.rate_rows}
    _lengths(book, errors)
    for job in book.job_types:
        seen: set[str] = set()
        if codes:
            for code in job.item_codes:
                if code not in codes:
                    errors.append(PolicyError(code="policy.playbook_item", sentence=_UNKNOWN_ITEM))
        for fact in job.facts:
            if fact.key in seen:
                errors.append(PolicyError(code="policy.playbook_fact", sentence=_DUPLICATE_FACT))
            seen.add(fact.key)
            if fact.required and not fact.question.strip():
                errors.append(PolicyError(code="policy.playbook_question", sentence=_PLAYBOOK_QUESTION))
    for trigger in book.inspections + book.escalations:
        if trigger.rule_id not in rule_ids:
            errors.append(PolicyError(code="policy.playbook_rule", sentence=_UNKNOWN_RULE))
    return errors


def _over_cap(value: object) -> bool:
    if isinstance(value, str):
        return len(value) > _FIELD_CAP
    if isinstance(value, BaseModel):
        return any(_over_cap(getattr(value, name)) for name in type(value).model_fields)
    if isinstance(value, tuple):
        return any(_over_cap(item) for item in value)
    return False


def _lengths(value: object, errors: list[PolicyError]) -> None:
    if isinstance(value, str):
        if len(value) > _FIELD_CAP:
            errors.append(PolicyError(code="policy.playbook_length", sentence=_LONG))
        return
    if isinstance(value, BaseModel):
        for name in type(value).model_fields:
            _lengths(getattr(value, name), errors)
        return
    if isinstance(value, tuple):
        for item in value:
            _lengths(item, errors)
