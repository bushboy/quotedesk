from decimal import Decimal
from pathlib import Path

import yaml

from quotedesk.domain.policy.playbook import (
    BusinessPlaybook,
    CommonQuestion,
    EscalationTrigger,
    FactDefinition,
    InspectionTrigger,
    JobTypePlay,
)
from quotedesk.domain.policy.rules import Outcome, Policy, PolicyRule
from quotedesk.domain.policy.when import published_when
from quotedesk.domain.services.decide import parse_when
from quotedesk.domain.shared.ids import PolicyVersionId, RuleId


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
    return FactDefinition(
        key=raw["key"],
        type=kind,
        unit=str(raw.get("unit") or ""),
        allowed=tuple(raw.get("allowed") or ()),
        question=str(raw.get("question") or ""),
        photo_can_answer=bool(raw.get("photo_can_answer") or False),
        required=bool(raw.get("required") or False),
    )


def _inspection(raw: dict) -> InspectionTrigger:
    return InspectionTrigger(
        condition=str(raw.get("condition") or ""),
        rule_id=str(raw["rule_id"]),
        fee=str(raw.get("fee") or ""),
    )


def _escalation(raw: dict) -> EscalationTrigger:
    return EscalationTrigger(condition=str(raw.get("condition") or ""), rule_id=str(raw["rule_id"]))


def _question(raw: dict) -> CommonQuestion:
    return CommonQuestion(topic=str(raw.get("topic") or ""), answer=str(raw.get("answer") or ""))
