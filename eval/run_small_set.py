"""Run the drafted ten-conversation sets through the real turn.

The model here only records facts the customer sentence states, then leaves
the sentence to the planner. It does not call a live model, so this run has
no latency number.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid5

import yaml
from fastapi import FastAPI

from quotedesk.application.dto.agent import ModelReply, ToolCall
from quotedesk.application.dto.tenant import TenantContext
from quotedesk.domain.conversation.events import Conversation
from quotedesk.domain.services.plan import StepKind
from quotedesk.infrastructure.demo import WHEN, bundle_for, install
from quotedesk.infrastructure.tenants import known_tenant

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "eval" / "results" / "small-set.json"
NAMESPACE = UUID("33333333-3333-4333-8333-333333333333")
_LITRES = re.compile(r"(\d+)\s*litre")
_SPAN = re.compile(r"(\d+(?:\.\d+)?)\s*m?\s*(?:by|x)\s*(\d+(?:\.\d+)?)", re.IGNORECASE)
_KINDS = {
    StepKind.ASK: "asked",
    StepKind.QUOTE: "quoted",
    StepKind.INSPECTION: "inspection_offered",
    StepKind.ESCALATE: "escalated",
}


class Recorder:
    def __init__(self) -> None:
        self.sent: list[str] = []

    def send(self, wa_id: str, body: str, *, buttons: tuple[str, ...] = (), image_url: str | None = None) -> None:
        self.sent.append(body)


class Reading:
    """Records facts that are written in the customer sentence, then stops."""

    def __init__(self, slug: str, text: str) -> None:
        self.slug = slug
        self.text = text
        self.calls = 0

    def complete(self, prompt) -> ModelReply:
        self.calls += 1
        if prompt.tool_payloads or self.text.strip().casefold() in ("hello", "hi"):
            return ModelReply(text="", tool_calls=())
        recorded = _stated(self.slug, self.text)
        if recorded is None:
            return ModelReply(text="", tool_calls=())
        job_type, facts = recorded
        event_id = prompt.messages[-1].provider_message_id
        return ModelReply(
            text="",
            tool_calls=(
                ToolCall(
                    name="update_case",
                    arguments={
                        "job_id": job_type,
                        "job_type": job_type,
                        "facts": [
                            {"key": key, "value": value, "source": "customer_text", "event_id": event_id}
                            for key, value in facts
                        ],
                    },
                ),
            ),
        )


def run() -> dict:
    rows = []
    for slug, filename in (("aquasure", "aquasure.yaml"), ("frameworks", "frameworks.yaml")):
        document = yaml.safe_load((ROOT / "eval" / "conversations" / filename).read_text(encoding="utf-8"))
        for item in document["conversations"]:
            rows.append(_one(slug, item))
    silent = sum(1 for row in rows if not row["reply"].strip())
    report = {
        "ran_on": datetime.now(timezone.utc).date().isoformat(),
        "model": "sentence facts, then the planner sentence",
        "latency": "not measured; this run does not call a live model",
        "conversations": len(rows),
        "silent": silent,
        "outcome_matches": sum(1 for row in rows if row["outcome_match"]),
        "rule_matches": sum(1 for row in rows if row["rule_match"]),
        "forbidden_hits": sum(1 for row in rows if row["forbidden"]),
        "rows": rows,
    }
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def _one(slug: str, item: dict) -> dict:
    profile = known_tenant(slug)
    recorder = Recorder()
    application = FastAPI()
    install(application, bundle_for(slug), model=Reading(slug, item["customer"]), sender=recorder, tenant=profile)
    conversation_id = uuid5(NAMESPACE, item["id"])
    application.state.cases.ensure(profile.tenant_id, conversation_id)
    opened = Conversation.open(conversation_id).append(item["id"], WHEN, item["customer"]).conversation
    application.state.conversations.save(profile.tenant_id, opened)
    application.state.turn.execute(TenantContext(tenant_id=profile.tenant_id), conversation_id)
    reply = recorder.sent[-1] if recorder.sent else ""
    step = application.state.turn._step
    outcome = _KINDS.get(step.kind, step.kind.value)
    expected_rule = "" if item["rule_id"] == "none" else item["rule_id"]
    forbidden = [phrase for phrase in item["forbidden"] if phrase in reply]
    return {
        "id": item["id"],
        "business": slug,
        "reply": reply,
        "outcome": outcome,
        "expected_outcome": item["expected_outcome"],
        "outcome_match": outcome == item["expected_outcome"],
        "rule_id": step.rule_id,
        "expected_rule": expected_rule,
        "rule_match": step.rule_id == expected_rule,
        "forbidden": forbidden,
    }


def _stated(slug: str, text: str) -> tuple[str, list[tuple[str, str]]] | None:
    folded = text.casefold().strip()
    if folded in ("hello", "hi"):
        return None
    facts: list[tuple[str, str]] = [("customer_text", text)]
    job_type = "replacement" if slug == "aquasure" else "carport"
    if "not a tank" in folded or "not a standard" in folded:
        job_type = "other"
    if "borehole" in folded:
        job_type = "borehole"
    if "new tank and a pump" in folded:
        job_type = "new_system"
        facts.append(("new_tank_and_pump", "true"))
        facts.append(("base_unconfirmed", "true"))
    if "damaged" in folded:
        facts.append(("installation_damaged", "true"))
        facts.append(("simple_swap", "false"))
    if "wiring" in folded:
        facts.append(("exposed_wiring", "true"))
    if "water on the floor" in folded:
        facts.append(("active_flooding", "true"))
    if "slope" in folded:
        facts.append(("sloped_ground", "true"))
    if "lintel" in folded and "cracked" in folded:
        facts.append(("lintel_cracked", "true"))
        job_type = "carport"
    if "asbestos" in folded:
        facts.append(("possible_asbestos", "true"))
        job_type = "carport"
    if "new opening" in folded:
        facts.append(("opening", "new"))
        job_type = "carport"
    if "ground floor" in folded:
        facts.append(("above_ground_floor", "true"))
        job_type = "carport"
    if "existing opening" in folded:
        facts.append(("opening", "existing"))
        job_type = "carport"
    if "standard size" in folded:
        facts.append(("standard_band", "true"))
        facts.append(("size_source", "customer_stated"))
    if "finish chosen" in folded:
        facts.append(("finish", "Economy sheeting"))
    litres = _LITRES.search(folded)
    if litres:
        facts.append(("size_litres", litres.group(1)))
        facts.append(("item_codes", f"TANK-{litres.group(1)}"))
        facts.append(("size_source", "customer_stated"))
    if "level" in folded:
        facts.append(("existing_level_base", "true"))
    span = _SPAN.search(text)
    if span:
        facts.append(("width_m", span.group(1)))
        facts.append(("length_m", span.group(2)))
        facts.append(("size_source", "customer_stated"))
        job_type = "carport"
    if "sheeting on the rate card" in folded:
        facts.append(("item_codes", "SHEET-ECO"))
        if not any(key == "finish" for key, _value in facts):
            facts.append(("finish", "Economy sheeting"))
    return job_type, facts


if __name__ == "__main__":
    report = run()
    print(
        f"conversations={report['conversations']} silent={report['silent']} "
        f"outcomes={report['outcome_matches']} rules={report['rule_matches']} "
        f"forbidden={report['forbidden_hits']}"
    )
    for row in report["rows"]:
        mark = "ok" if row["outcome_match"] and row["rule_match"] and not row["forbidden"] else "miss"
        print(f"{mark} {row['id']} outcome={row['outcome']} rule={row['rule_id'] or 'none'} reply={row['reply'][:80]!r}")
