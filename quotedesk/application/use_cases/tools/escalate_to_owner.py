"""Hand the case to the owner with a brief built from the case, and tell them once."""

from datetime import datetime, timezone
from decimal import Decimal

from quotedesk.application.dto.tenant import TenantContext
from quotedesk.application.dto.tool_inputs import EscalateToOwnerInput
from quotedesk.application.dto.tool_outputs import EscalateToOwnerResult
from quotedesk.application.errors import CaseNotFound, TenantRequired
from quotedesk.application.use_cases.tools.notify_owner import NotifyOwner
from quotedesk.domain.case.case_file import CaseFile
from quotedesk.domain.policy.playbook import BusinessPlaybook
from quotedesk.domain.policy.rules import Policy
from quotedesk.domain.services.brief import OwnerBrief, render_brief
from quotedesk.domain.services.plan import fact_applies, plan_next_step
from quotedesk.domain.shared.ids import PolicyVersionId

_SOURCE = {
    "customer_text": "said",
    "photo_extraction": "photo",
    "voice_transcript": "voice note",
    "video_extraction": "video",
    "owner": "owner",
}
_MEDIA = {"image": "photo", "audio": "voice note", "video": "video"}


class EscalateToOwner:
    def __init__(self, cases, conversations, policies, handovers, inspections, notifier: NotifyOwner, clock, quotes=None) -> None:
        self._cases = cases
        self._conversations = conversations
        self._policies = policies
        self._handovers = handovers
        self._inspections = inspections
        self._notifier = notifier
        self._clock = clock
        self._quotes = quotes

    def render(self, context: TenantContext | None, data: EscalateToOwnerInput) -> str:
        brief, _step, _playbook = self._compose(context, data)
        return brief

    def execute(self, context: TenantContext | None, data: EscalateToOwnerInput) -> EscalateToOwnerResult:
        brief, step, playbook = self._compose(context, data)
        now = self._clock.now() if self._clock is not None else datetime.now(timezone.utc)
        if self._handovers is not None:
            from quotedesk.application.dto.agent import HandoverNote

            self._handovers.append(
                context.tenant_id,
                HandoverNote(
                    conversation_id=data.conversation_id,
                    reason=step.reason or data.summary or "The quote needs a person.",
                    brief=brief,
                    at=now,
                ),
            )
        link = f"/console/brief/{data.conversation_id}"
        notified = self._notifier.send(
            context.tenant_id,
            playbook,
            data.conversation_id,
            f"A customer needs you.\n{link}\n\n{brief}",
        )
        sentence = step.sentence if step.kind.value == "escalate" else "I'll ask someone from the business to pick this up."
        return EscalateToOwnerResult(sentence=sentence, brief=brief, notified=notified)

    def _compose(self, context: TenantContext | None, data: EscalateToOwnerInput):
        if context is None:
            raise TenantRequired()
        case = self._cases.get(context.tenant_id, data.conversation_id)
        if case is None:
            raise CaseNotFound()
        playbook, policy = _published(self._policies, context.tenant_id)
        from quotedesk.application.use_cases.tools.planner_inputs import planner_inputs

        text, asked = planner_inputs(self._conversations, context.tenant_id, data.conversation_id, playbook)
        step = plan_next_step(case, playbook, policy, asked=asked, customer_text=text)
        brief = render_brief(
            _brief(
                case,
                playbook,
                step,
                data.summary,
                _customer(self._conversations, context.tenant_id, data.conversation_id),
                _media(self._conversations, context.tenant_id, data.conversation_id),
                _inspection_line(self._inspections, context.tenant_id, data.conversation_id),
                _quote_line(self._quotes, context.tenant_id, data.conversation_id, case),
            )
        )
        return brief, step, playbook


def _published(policies, tenant_id):
    bundle = None if policies is None else policies.published(tenant_id)
    if bundle is None:
        return BusinessPlaybook(), Policy(
            version=PolicyVersionId("planner-policy-v1.0"),
            rules=(),
            rate_card_codes=(),
            sam_score_threshold=Decimal("0"),
        )
    return bundle.playbook, bundle.policy


def _brief(case: CaseFile, playbook, step, summary: str, customer: tuple[str, str, str, str], media, inspection: str, quote: str):
    number, name, last, last_at = customer
    known, missing, unknown = _facts(case, playbook)
    return OwnerBrief(
        customer_number=number,
        customer_name=name,
        summary=summary.strip() or last,
        jobs=tuple(job.job_type or job.job_id for job in case.jobs),
        known=known,
        missing=missing,
        unknown=unknown,
        media=media,
        outcome=step.kind.value,
        rule_id=step.rule_id,
        reason=step.reason,
        quote=quote,
        inspection=inspection,
        next_action=step.sentence,
        last_message=last,
        last_at=last_at,
    )


def _facts(case: CaseFile, playbook: BusinessPlaybook):
    known: list[str] = []
    missing: list[str] = []
    unknown: list[str] = []
    for job in case.jobs:
        current = {
            fact.key: fact
            for fact in job.facts
            if fact.superseded_by is None and not fact.contested
        }
        values = {key: fact.value for key, fact in current.items()}
        required = tuple(
            key for key in playbook.required(job.job_type or "") if fact_applies(key, job.job_type or "", values)
        )
        for key in required:
            fact = current.get(key)
            if fact is None or (fact.state == "known" and not fact.value.strip()):
                missing.append(key)
            elif fact.state == "unknown":
                unknown.append(key)
        for key, fact in current.items():
            if fact.state == "unknown":
                if key not in unknown:
                    unknown.append(key)
                continue
            if not fact.value.strip():
                continue
            known.append(f"{key} = {fact.value} ({_SOURCE.get(fact.source, fact.source)})")
    return tuple(known), tuple(missing), tuple(unknown)


def _customer(conversations, tenant_id, conversation_id) -> tuple[str, str, str, str]:
    messages = []
    reader = getattr(conversations, "messages", None)
    if reader is not None:
        messages = list(reader(tenant_id, conversation_id))
    spoken = [message for message in messages if (message.body or "").strip()]
    last = spoken[-1] if spoken else (messages[-1] if messages else None)
    number = "" if last is None else last.wa_id
    named = getattr(conversations, "name", None)
    name = named(tenant_id, number) if named is not None and number else ""
    body = "" if last is None or not last.body else last.body
    at = "" if last is None else last.at.isoformat()
    return number or "", name or "", body, at


def _media(conversations, tenant_id, conversation_id) -> tuple[str, ...]:
    reader = getattr(conversations, "messages", None)
    if reader is None:
        return ()
    lines = []
    for message in reader(tenant_id, conversation_id):
        label = _MEDIA.get(message.kind)
        if label is None:
            continue
        detail = message.transcript or message.image_text or message.body or ""
        lines.append(f"{label}: {detail}".strip())
    return tuple(lines)


def _quote_line(quotes, tenant_id, conversation_id, case: CaseFile) -> str:
    getter = getattr(quotes, "get_quote", None) if quotes is not None else None
    if getter is None:
        return ""
    try:
        found = getter(tenant_id, conversation_id)
    except Exception:
        return ""
    if found is None:
        return ""
    current = found.current
    parts = [f"{found.quote_id.value} {current.state.value}"]
    if current.lines:
        label = _work_label(case)
        if label:
            parts.append(label)
        for line in current.lines:
            parts.append(f"{line.description} {_rand(line.total.amount)}")
    return " ".join(parts)


_SWAP = frozenset({"replacement", "swap", "tank_swap"})
_NEW = frozenset({"new_system", "new", "installation", "new_installation", "new_install"})


def _work_label(case: CaseFile) -> str:
    for job in case.jobs:
        values = {
            fact.key: fact.value.strip().casefold()
            for fact in job.facts
            if fact.superseded_by is None and not fact.contested and fact.value.strip()
        }
        kind = (job.job_type or values.get("job_type") or "").casefold().replace("-", "_").replace(" ", "_")
        opening = values.get("opening")
        if kind in _SWAP or opening == "existing":
            return "a swap"
        if values.get("stand_present") in ("true", "yes") or values.get("existing_frame") in ("true", "yes"):
            return "a swap"
        if kind in _NEW or opening == "new":
            return "a new installation"
        if values.get("stand_present") in ("false", "no") or values.get("existing_frame") in ("false", "no"):
            return "a new installation"
    return ""


def _rand(amount) -> str:
    return "R " + f"{amount:,.2f}".replace(",", " ")


def _inspection_line(inspections, tenant_id, conversation_id) -> str:
    if inspections is None:
        return ""
    reader = getattr(inspections, "for_conversation", None)
    if reader is None:
        return ""
    rows = reader(tenant_id, conversation_id)
    if not rows:
        return ""
    item = rows[-1]
    window = "" if item.window_start is None else item.window_start.isoformat()
    return " ".join(part for part in (item.status.value, item.fee, window, item.address) if part)
