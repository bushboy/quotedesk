"""Time the twenty text-only evaluation turns on the live agent.

Loads `.env` into this process and does not print secrets. The store stays
in memory, so the run does not write quotes. Each figure is the wall-clock
time of one turn, from the customer sentence to the reply.
"""

from __future__ import annotations

import json
import math
import os
import time
from datetime import datetime, timezone
from uuid import uuid5

import yaml
from fastapi import FastAPI

from eval.run_small_set import NAMESPACE, ROOT
from quotedesk.application.dto.tenant import TenantContext
from quotedesk.domain.conversation.events import Conversation
from quotedesk.infrastructure.config import get_settings
from quotedesk.infrastructure.container import _model
from quotedesk.infrastructure.demo import WHEN, bundle_for, install
from quotedesk.infrastructure.tenants import known_tenant

RESULTS = ROOT / "eval" / "results" / "latency.json"


def main() -> dict:
    _load_env()
    os.environ["STORE"] = "memory"
    settings = get_settings()
    model = _model(settings)
    rows = []
    for slug, filename in (("aquasure", "aquasure.yaml"), ("frameworks", "frameworks.yaml")):
        document = yaml.safe_load((ROOT / "eval" / "conversations" / filename).read_text(encoding="utf-8"))
        for item in document["conversations"]:
            row = _one(slug, item, model)
            rows.append(row)
            print(f"{row['id']} {row['seconds']:.2f}s reply={row['replied']}", flush=True)
    seconds = sorted(row["seconds"] for row in rows)
    report = {
        "ran_on": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "provider": settings.agent_provider,
        "model_id": settings.baseten_model_id if settings.agent_provider == "baseten" else settings.spark_model_id,
        "conversations": len(rows),
        "silent": sum(1 for row in rows if not row["replied"]),
        "median_seconds": _median(seconds),
        "p90_seconds": _percentile(seconds, 90),
        "slowest_seconds": seconds[-1],
        "rows": rows,
    }
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        f"conversations={report['conversations']} silent={report['silent']} "
        f"median={report['median_seconds']:.2f}s p90={report['p90_seconds']:.2f}s "
        f"slowest={report['slowest_seconds']:.2f}s",
        flush=True,
    )
    return report


def _one(slug: str, item: dict, model) -> dict:
    profile = known_tenant(slug)
    recorder = _Recorder()
    application = FastAPI()
    install(application, bundle_for(slug), model=model, sender=recorder, tenant=profile)
    conversation_id = uuid5(NAMESPACE, item["id"])
    application.state.cases.ensure(profile.tenant_id, conversation_id)
    opened = Conversation.open(conversation_id).append(item["id"], WHEN, item["customer"]).conversation
    application.state.conversations.save(profile.tenant_id, opened)
    started = time.perf_counter()
    application.state.turn.execute(TenantContext(tenant_id=profile.tenant_id), conversation_id)
    elapsed = time.perf_counter() - started
    reply = recorder.sent[-1] if recorder.sent else ""
    return {
        "id": item["id"],
        "business": slug,
        "seconds": round(elapsed, 3),
        "replied": bool(reply.strip()),
    }


def _median(seconds: list[float]) -> float:
    count = len(seconds)
    middle = count // 2
    if count % 2:
        return seconds[middle]
    return (seconds[middle - 1] + seconds[middle]) / 2


def _percentile(seconds: list[float], percent: int) -> float:
    """Nearest rank. For 20 turns, the 90th is the 18th, so two turns are slower."""
    if not seconds:
        return 0.0
    rank = max(1, math.ceil(percent / 100 * len(seconds)))
    return seconds[rank - 1]


def _load_env() -> None:
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        os.environ.setdefault(name.strip(), value.strip().strip('"').strip("'"))


class _Recorder:
    def __init__(self) -> None:
        self.sent: list[str] = []

    def send(self, wa_id: str, body: str, *, buttons: tuple[str, ...] = (), image_url: str | None = None) -> None:
        self.sent.append(body)


if __name__ == "__main__":
    main()
