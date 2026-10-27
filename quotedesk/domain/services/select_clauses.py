import re
from decimal import Decimal

from quotedesk.domain.policy.clauses import (
    ClauseFacts,
    ClausePolicy,
    ClauseSelection,
    ClauseTemplate,
    Condition,
)
from quotedesk.domain.policy.rules import Decision, Outcome
from quotedesk.domain.shared.errors import PolicyViolation

_MISSING_CLAUSE = "The policy has no clause for that fact."
_MISSING_ITEM = "That variation item is not on the rate card."
_MISSING_SETTING = "A clause placeholder has no setting."
_TOKEN = re.compile(r"\{([A-Za-z0-9_]+)\}")
_CARPORT = (
    "CARPORT-A1",
    "CARPORT-A2",
    "CARPORT-A3",
    "CARPORT-A4",
    "CARPORT-A5",
    "CARPORT-A6",
    "CARPORT-X1",
    "CARPORT-X2",
    "GEN-V1",
    "GEN-V2",
    "GEN-S1",
)


def select_clauses(
    decision: Decision,
    facts: ClauseFacts,
    job_type: str,
    policy: ClausePolicy,
) -> ClauseSelection:
    if decision.outcome == Outcome.ESCALATION or job_type != "carport":
        return ClauseSelection(conditions=(), customer_template=decision.customer_template)
    selected = _select(policy, facts)
    _require_variations(selected, policy.rate_card_codes)
    conditions = tuple(_render(template, facts, policy.settings) for template in selected)
    return ClauseSelection(conditions=conditions, customer_template=decision.customer_template)


def _select(policy: ClausePolicy, facts: ClauseFacts) -> tuple[ClauseTemplate, ...]:
    by_id = {template.clause_id: template for template in policy.templates}
    chosen: list[ClauseTemplate] = []
    roof_stated = isinstance(facts.roof_covering, str) and facts.roof_covering.strip() != ""
    for clause_id in _CARPORT:
        if clause_id == "CARPORT-A5" and roof_stated:
            continue
        template = by_id.get(clause_id)
        if template is None:
            raise PolicyViolation(code="policy.violation", sentence=_MISSING_CLAUSE)
        chosen.append(template)
    return tuple(chosen)


def _require_variations(templates: tuple[ClauseTemplate, ...], codes: tuple[str, ...]) -> None:
    for template in templates:
        code = template.variation_item_code
        if code is not None and code not in codes:
            raise PolicyViolation(code="policy.violation", sentence=_MISSING_ITEM)


def _render(template: ClauseTemplate, facts: ClauseFacts, settings: dict[str, int]) -> Condition:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name == "width_m":
            return _one_decimal(facts.width_m)
        if name == "length_m":
            return _one_decimal(facts.length_m)
        if name == "area_m2":
            return _area(facts.width_m, facts.length_m)
        if name not in settings:
            raise PolicyViolation(code="policy.violation", sentence=_MISSING_SETTING)
        return str(settings[name])

    return Condition(
        clause_id=template.clause_id,
        clause_version=template.clause_version,
        kind=template.kind,
        text=_TOKEN.sub(replace, template.text),
        if_not_true=template.if_not_true,
        variation_item_code=template.variation_item_code,
    )


def _one_decimal(value: Decimal | None) -> str:
    if value is None:
        raise PolicyViolation(code="policy.violation", sentence=_MISSING_SETTING)
    return format(value.quantize(Decimal("0.1")), "f")


def _area(width: Decimal | None, length: Decimal | None) -> str:
    if width is None or length is None:
        raise PolicyViolation(code="policy.violation", sentence=_MISSING_SETTING)
    product = width * length
    whole = product.to_integral_value()
    if product == whole:
        return str(int(whole))
    return format(product, "f")
