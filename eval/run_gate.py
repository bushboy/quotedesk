"""Run the release set and write the per-business numbers.

The customer is the scripted voice behind the model port. It does not call a
live model, and it does not write eval/results/small-set.json or latency.json.
A business is eligible for a live number only after three passing runs.
"""

from __future__ import annotations

import json
import math
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid5

import yaml
from fastapi import FastAPI

from eval.customer import CustomerPrompt, ScriptedCustomer
from eval.release import live_number_allowed
from quotedesk.application.dto.agent import ModelReply, ToolCall
from quotedesk.application.dto.tenant import TenantContext
from quotedesk.domain.conversation.events import Conversation
from quotedesk.domain.services.plan import StepKind
from quotedesk.domain.shared.errors import PolicyViolation
from quotedesk.infrastructure.demo import WHEN, bundle_for, install
from quotedesk.adapters.outbound.persistence.tenants import known_tenant

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "eval" / "conversations" / "gate"
RESULTS = ROOT / "eval" / "results" / "gate.json"
HISTORY = ROOT / "eval" / "results" / "gate-history.json"
NAMESPACE = UUID("44444444-4444-4444-8444-444444444444")
BUSINESSES = ("aquasure", "frameworks")
_UNFOUNDED = ("for free", "no charge", "already approved")
_KINDS = {
    StepKind.ASK: "asked",
    StepKind.CONFIRM: "asked",
    StepKind.QUOTE: "quoted",
    StepKind.INSPECTION: "inspection_offered",
    StepKind.ESCALATE: "escalated",
}


class Recorder:
    def __init__(self) -> None:
        self.sent: list[str] = []

    def send(self, wa_id: str, body: str, *, buttons: tuple[str, ...] = (), image_url: str | None = None) -> None:
        self.sent.append(body)


class Recording:
    """Writes the facts the customer was allowed to reveal, then lets the planner speak."""

    def __init__(self) -> None:
        self.pending: list[tuple[str, str]] = []
        self.job_type = ""

    def complete(self, prompt) -> ModelReply:
        if prompt.tool_payloads or not self.pending or not self.job_type:
            return ModelReply(text="", tool_calls=())
        event_id = prompt.messages[-1].provider_message_id
        facts = self.pending
        self.pending = []
        return ModelReply(
            text="",
            tool_calls=(
                ToolCall(
                    name="update_case",
                    arguments={
                        "job_id": self.job_type,
                        "job_type": self.job_type,
                        "facts": [
                            {"key": key, "value": value, "source": "customer_text", "event_id": event_id}
                            for key, value in facts
                        ],
                    },
                ),
            ),
        )


def run(*, seed: int = 0, voice: ScriptedCustomer | None = None) -> dict:
    customer = voice or ScriptedCustomer()
    rows = []
    for slug in BUSINESSES:
        document = yaml.safe_load((GATE / f"{slug}.yaml").read_text(encoding="utf-8"))
        for item in document["conversations"]:
            rows.append(_one(slug, item, seed, customer))
    businesses = {slug: _business(slug, [row for row in rows if row["business"] == slug]) for slug in BUSINESSES}
    report = {
        "ran_on": datetime.now(timezone.utc).date().isoformat(),
        "model": "scripted customer behind the model port",
        "seed": seed,
        "cost_note": "This voice makes no live model call, so the cost is zero.",
        "businesses": businesses,
        "rows": rows,
    }
    return report


def publish(report: dict) -> dict:
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    history = _history()
    history.append(
        {
            "ran_on": report["ran_on"],
            "seed": report["seed"],
            "passed": {slug: report["businesses"][slug]["passed"] for slug in BUSINESSES},
        }
    )
    HISTORY.write_text(json.dumps(history, indent=2) + "\n", encoding="utf-8")
    return report


def _one(slug: str, item: dict, seed: int, voice: ScriptedCustomer) -> dict:
    profile = known_tenant(slug)
    recorder = Recorder()
    model = Recording()
    application = FastAPI()
    install(application, bundle_for(slug), model=model, sender=recorder, tenant=profile)
    conversation_id = uuid5(NAMESPACE, f"{seed}:{item['id']}")
    application.state.cases.ensure(profile.tenant_id, conversation_id)
    context = TenantContext(tenant_id=profile.tenant_id)
    questions = 0
    reasked: list[str] = []
    known: set[str] = set()
    replies: list[str] = []
    outcome = "silent"
    rule_id = ""
    started = time.perf_counter()
    batches = item.get("batches") or [{}]
    for turn, batch in enumerate(batches, start=1):
        facts = tuple((key, str(value)) for key, value in batch.items() if key != "job_type")
        if batch.get("job_type"):
            model.job_type = str(batch["job_type"])
        sentence = voice.complete(
            CustomerPrompt(persona=item.get("persona", ""), seed=seed, facts=facts, turn=turn)
        ).text
        _hear(application, profile.tenant_id, conversation_id, f"{item['id']}-{turn}", sentence)
        before = len(recorder.sent)
        model.pending = list(facts)
        application.state.turn.execute(context, conversation_id)
        fresh = recorder.sent[before:]
        replies.extend(fresh)
        step = application.state.turn._step
        outcome = _KINDS.get(step.kind, step.kind.value)
        rule_id = step.rule_id
        if step.kind is StepKind.ASK and step.fact_key in known:
            reasked.append(step.fact_key)
        if step.kind is StepKind.ASK and outcome != item["expected_outcome"]:
            questions += 1
            known.update(key for key, _value in facts)
            continue
        known.update(key for key, _value in facts)
        break
    elapsed = time.perf_counter() - started
    reply = "\n".join(replies)
    expected_rule = "" if item["rule_id"] in ("", "none") else item["rule_id"]
    forbidden = [phrase for phrase in item.get("forbidden") or [] if phrase in reply]
    unfounded = [phrase for phrase in _UNFOUNDED if phrase in reply.casefold()]
    required = list(item.get("required_facts") or [])
    filled = _filled(application, profile.tenant_id, conversation_id, model.job_type, required)
    return {
        "id": item["id"],
        "business": slug,
        "reply": reply,
        "outcome": outcome,
        "expected_outcome": item["expected_outcome"],
        "outcome_match": outcome == item["expected_outcome"],
        "rule_id": rule_id,
        "expected_rule": expected_rule,
        "rule_match": rule_id == expected_rule,
        "forbidden": forbidden,
        "unfounded": unfounded,
        "silent": not reply.strip(),
        "questions_before_outcome": questions,
        "reasked": reasked,
        "brief_completeness": 1.0 if not required else len(filled) / len(required),
        "seconds": round(elapsed, 3),
    }


def _hear(application, tenant_id: UUID, conversation_id: UUID, message_id: str, body: str) -> None:
    current = application.state.conversations.get(tenant_id, conversation_id)
    opened = Conversation.open(conversation_id) if current is None else current
    application.state.conversations.save(
        tenant_id,
        opened.append(message_id, WHEN, body).conversation,
    )


def _filled(application, tenant_id: UUID, conversation_id: UUID, job_id: str, required: list[str]) -> list[str]:
    if not job_id or not required:
        return []
    case = application.state.cases.get(tenant_id, conversation_id)
    if case is None:
        return []
    found = []
    for key in required:
        try:
            if case.current(job_id, key).strip():
                found.append(key)
        except PolicyViolation:
            continue
    return found


def _business(slug: str, rows: list[dict]) -> dict:
    count = len(rows)
    seconds = sorted(row["seconds"] for row in rows)
    accuracy = sum(1 for row in rows if row["outcome_match"]) / count
    rules = sum(1 for row in rows if row["rule_match"]) / count
    silent = sum(1 for row in rows if row["silent"])
    unfounded = sum(len(row["forbidden"]) + len(row["unfounded"]) for row in rows)
    passed = silent == 0 and unfounded == 0 and accuracy == 1 and rules == 1
    return {
        "conversations": count,
        "outcome_accuracy": round(accuracy, 3),
        "rule_accuracy": round(rules, 3),
        "questions_before_outcome": round(sum(row["questions_before_outcome"] for row in rows) / count, 2),
        "silent": silent,
        "unfounded": unfounded,
        "reasked_facts": sum(len(row["reasked"]) for row in rows),
        "brief_completeness": round(sum(row["brief_completeness"] for row in rows) / count, 3),
        "median_seconds": round(_median(seconds), 3),
        "p90_seconds": round(_percentile(seconds, 90), 3),
        "cost_per_conversation": 0,
        "passed": passed,
    }


def eligibility(history: list[dict] | None = None) -> dict[str, bool]:
    runs = _history() if history is None else history
    return {slug: live_number_allowed([bool(item["passed"].get(slug)) for item in runs]) for slug in BUSINESSES}


def _history() -> list[dict]:
    if not HISTORY.is_file():
        return []
    loaded = json.loads(HISTORY.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, list) else []


def _median(seconds: list[float]) -> float:
    count = len(seconds)
    middle = count // 2
    if count % 2:
        return seconds[middle]
    return (seconds[middle - 1] + seconds[middle]) / 2


def _percentile(seconds: list[float], percent: int) -> float:
    if not seconds:
        return 0.0
    rank = max(1, math.ceil(percent / 100 * len(seconds)))
    return seconds[min(rank, len(seconds)) - 1]


def _print(report: dict) -> None:
    print(f"ran_on={report['ran_on']} model={report['model']} seed={report['seed']}")
    for slug, numbers in report["businesses"].items():
        print(
            f"{slug} conversations={numbers['conversations']} "
            f"outcome_accuracy={numbers['outcome_accuracy']} "
            f"questions={numbers['questions_before_outcome']} "
            f"silent={numbers['silent']} unfounded={numbers['unfounded']} "
            f"reasked={numbers['reasked_facts']} brief={numbers['brief_completeness']} "
            f"median={numbers['median_seconds']}s p90={numbers['p90_seconds']}s "
            f"cost={numbers['cost_per_conversation']} passed={numbers['passed']}"
        )
    allowed = eligibility()
    for slug, yes in allowed.items():
        print(f"live_number {slug}={'allowed' if yes else 'refused'}")
    for row in report["rows"]:
        if row["outcome_match"] and row["rule_match"] and not row["silent"] and not row["forbidden"]:
            continue
        print(
            f"miss {row['id']} outcome={row['outcome']} rule={row['rule_id'] or 'none'} "
            f"reply={row['reply'][:120]!r}"
        )


if __name__ == "__main__":
    _print(publish(run()))
