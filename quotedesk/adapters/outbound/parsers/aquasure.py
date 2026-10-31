from decimal import Decimal
from pathlib import Path

import yaml

from quotedesk.domain.policy.playbook import (
    BusinessPlaybook,
    CommonQuestion,
    EscalationTrigger,
    FactDefinition,
    FactOption,
    InspectionTrigger,
    JobTypePlay,
)
from quotedesk.domain.policy.rules import Outcome, Policy, PolicyRule
from quotedesk.domain.policy.when import published_when
from quotedesk.domain.services.decide import parse_when
from quotedesk.domain.services.price import RateCard, RateCardItem
from quotedesk.domain.shared.ids import PolicyVersionId, RuleId
from quotedesk.domain.shared.money import Money


def load_policy(path: Path) -> Policy:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    minimum = raw.get("range_minimum")
    return Policy(
        version=PolicyVersionId(raw["version"]),
        sam_score_threshold=Decimal(str(raw["sam_score_threshold"])),
        rate_card_codes=tuple(raw["rate_card_codes"]),
        range_minimum=None if minimum is None else Decimal(str(minimum)),
        rules=tuple(
            PolicyRule(
                rule_id=RuleId(rule["rule_id"]),
                priority=rule["priority"],
                outcome=Outcome(rule["outcome"]),
                customer_template=rule["customer_template"],
                reason=rule["reason"],
                when=parse_when(rule.get("when")) or published_when(rule["rule_id"]),
            )
            for rule in raw["rules"]
        ),
    )


def load_playbook(path: Path) -> BusinessPlaybook:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    block = raw.get("playbook") or {}
    return BusinessPlaybook(
        name=str(block.get("name") or ""),
        trade=str(block.get("trade") or ""),
        area=str(block.get("area") or ""),
        hours=str(block.get("hours") or ""),
        tone=str(block.get("tone") or ""),
        languages=str(block.get("languages") or ""),
        does_not=str(block.get("does_not") or ""),
        guidance=str(block.get("guidance") or "").strip(),
        owner_whatsapp=str(block.get("owner_whatsapp") or ""),
        owner_email=str(block.get("owner_email") or ""),
        job_types=tuple(_job(job) for job in block.get("job_types") or ()),
        inspections=tuple(_inspection(item) for item in block.get("inspections") or ()),
        escalations=tuple(_escalation(item) for item in block.get("escalations") or ()),
        questions=tuple(_question(item) for item in block.get("questions") or ()),
    )


def _job(raw: dict) -> JobTypePlay:
    return JobTypePlay(
        key=raw["key"],
        description=str(raw.get("description") or ""),
        label=str(raw.get("label") or ""),
        item_codes=tuple(raw.get("item_codes") or ()),
        roles=tuple(str(role) for role in raw.get("roles") or ()),
        pricing=str(raw.get("pricing") or ""),
        installation=str(raw.get("installation") or ""),
        delivery=str(raw.get("delivery") or ""),
        facts=tuple(_fact(fact) for fact in raw.get("facts") or ()),
    )


def _fact(raw: dict) -> FactDefinition:
    kind = str(raw.get("type") or "text").replace("/", "_")
    if kind not in ("number", "choice", "yes_no", "text"):
        kind = "text"
    decides = str(raw.get("decides") or "price")
    ease = str(raw.get("ease") or "easy")
    unsure = str(raw.get("if_unsure") or "inspection")
    minimum = raw.get("min_confidence")
    return FactDefinition(
        key=raw["key"],
        type=kind,
        unit=str(raw.get("unit") or ""),
        allowed=tuple(str(item) for item in raw.get("allowed") or ()),
        question=str(raw.get("question") or ""),
        photo_can_answer=bool(raw.get("photo_can_answer") or False),
        required=bool(raw.get("required") or False),
        label=str(raw.get("label") or ""),
        options=tuple(_option(item) for item in raw.get("options") or ()),
        look_for=str(raw.get("look_for") or ""),
        min_confidence=None if minimum in (None, "") else Decimal(str(minimum)),
        decides=decides if decides in ("price", "outcome", "both") else "price",
        ease=ease if ease in ("easy", "needs_tape", "needs_expert") else "easy",
        if_unsure=unsure if unsure in ("ask_photo", "range", "inspection", "photo_then_range") else "inspection",
    )


def _option(raw: dict) -> FactOption:
    return FactOption(
        value=str(raw["value"]),
        label=str(raw.get("label") or raw["value"]),
        hint=str(raw.get("hint") or ""),
        item_codes=tuple(str(code) for code in raw.get("item_codes") or ()),
    )


def _inspection(raw: dict) -> InspectionTrigger:
    return InspectionTrigger(
        condition=str(raw.get("condition") or ""),
        rule_id=str(raw["rule_id"]),
        fee=str(raw.get("fee") or ""),
        fee_item=str(raw.get("fee_item") or ""),
    )


def _escalation(raw: dict) -> EscalationTrigger:
    return EscalationTrigger(condition=str(raw.get("condition") or ""), rule_id=str(raw["rule_id"]))


def load_rate_card(path: Path) -> RateCard:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    block = raw.get("rate_card") or {}
    items = tuple(_rate_item(item) for item in block.get("items") or ())
    fee = block.get("site_visit_fee")
    if fee is None:
        inspection = next((item.unit_price for item in items if item.role == "inspection"), Money("0"))
        fee = inspection.amount
    return RateCard(vat_inclusive=bool(block.get("vat_inclusive", True)), site_visit_fee=Money(str(fee)), items=items)


def _rate_item(raw: dict) -> RateCardItem:
    unit = str(raw.get("unit") or "each")
    role = str(raw.get("role") or "product")
    applies = str(raw.get("applies_to") or "both")
    return RateCardItem(
        item_code=str(raw["code"]),
        description=str(raw.get("description") or raw["code"]),
        unit_price=Money(str(raw["price"])),
        unit=unit if unit in ("each", "per m²", "per metre") else "each",
        role=role if role in ("product", "frame", "hardware", "installation", "delivery", "inspection") else "product",
        applies_to=applies if applies in ("both", "swap", "new") else "both",
        job_types=tuple(str(item) for item in raw.get("job_types") or ()),
        when=parse_when(raw.get("when")),
    )


def _question(raw: dict) -> CommonQuestion:
    return CommonQuestion(topic=str(raw.get("topic") or ""), answer=str(raw.get("answer") or ""))
