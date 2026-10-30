"""Record an inspection from the planner's step, the capacity calendar, and the playbook fee."""

from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

from quotedesk.application.dto.tenant import TenantContext
from quotedesk.application.dto.tool_inputs import BookInspectionInput
from quotedesk.application.dto.tool_outputs import BookInspectionResult
from quotedesk.application.errors import CaseNotFound, TenantRequired
from quotedesk.application.ports.repositories import CapacityRepository, CaseFileRepository
from quotedesk.application.ports.runtime import Clock
from quotedesk.domain.policy.playbook import BusinessPlaybook
from quotedesk.domain.policy.rules import Policy
from quotedesk.domain.quotes.inspection import Inspection, InspectionStatus
from quotedesk.domain.quotes.quote import QuoteState
from quotedesk.domain.quotes.schedule import DepositState, ScheduleRequest, ScheduleSettings
from quotedesk.domain.services.plan import StepKind, plan_next_step
from quotedesk.domain.services.schedule import civil_date, schedule
from quotedesk.domain.shared.errors import PolicyViolation, ValidationError
from quotedesk.domain.shared.ids import PolicyVersionId

_ZONE = ZoneInfo("Africa/Johannesburg")


class BookInspection:
    def __init__(
        self,
        cases: CaseFileRepository,
        policies,
        capacity: CapacityRepository,
        settings: ScheduleSettings,
        clock: Clock,
        inspections,
        quotes=None,
        conversations=None,
    ) -> None:
        self._cases = cases
        self._policies = policies
        self._capacity = capacity
        self._settings = settings
        self._clock = clock
        self._inspections = inspections
        self._quotes = quotes
        self._conversations = conversations

    def execute(self, context: TenantContext | None, data: BookInspectionInput) -> BookInspectionResult:
        if context is None:
            raise TenantRequired()
        case = self._cases.get(context.tenant_id, data.conversation_id)
        if case is None:
            raise CaseNotFound()
        playbook, policy = _published(self._policies, context.tenant_id)
        from quotedesk.application.use_cases.tools.planner_inputs import planner_inputs

        text, asked = planner_inputs(self._conversations, context.tenant_id, data.conversation_id, playbook)
        step = plan_next_step(case, playbook, policy, asked=asked, customer_text=text)
        rule_id = step.rule_id if step.kind is StepKind.INSPECTION else ""
        fee = _fee(playbook, rule_id)
        window = _window(self._capacity, self._settings, self._clock, context.tenant_id)
        status = InspectionStatus.BOOKED if data.confirm else InspectionStatus.OFFERED
        now = self._clock.now()
        inspection = Inspection(
            inspection_id=uuid4(),
            tenant_id=context.tenant_id,
            conversation_id=data.conversation_id,
            job_id=data.job_id or step.job_id,
            address=data.address.strip(),
            rule_id=rule_id,
            fee=fee,
            window_start=window,
            window_end=window,
            status=status,
            summary=data.summary.strip(),
            at=now,
        )
        self._inspections.save(context.tenant_id, inspection)
        if status is InspectionStatus.BOOKED:
            _book_quote(self._quotes, context.tenant_id, data.conversation_id, now)
        sentence = _sentence(step.sentence if step.kind is StepKind.INSPECTION else "We'll book an inspection.", fee, window)
        return BookInspectionResult(
            inspection_id=inspection.inspection_id,
            status=status.value,
            rule_id=rule_id,
            fee=fee,
            window_start=window,
            window_end=window,
            sentence=sentence,
        )


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


def _fee(playbook: BusinessPlaybook, rule_id: str) -> str:
    for trigger in playbook.inspections:
        if rule_id and trigger.rule_id == rule_id:
            return trigger.fee
    if playbook.inspections:
        return playbook.inspections[0].fee
    return ""


def _window(capacity, settings: ScheduleSettings, clock: Clock, tenant_id):
    at = clock.now()
    today = civil_date(at, _ZONE)
    request = ScheduleRequest(kind="earliest", quote_issued=True, job_type="inspection")
    try:
        result = schedule(request, capacity.get(tenant_id), settings, DepositState(paid=False), today=today, at=at)
    except (PolicyViolation, ValidationError):
        return None
    return result.commitment.earliest_window


def _sentence(base: str, fee: str, window) -> str:
    parts = [base.strip()]
    if fee:
        parts.append(f"The visit fee is {fee}.")
    if window is not None:
        parts.append(f"The earliest window is {window.isoformat()}.")
    return " ".join(part for part in parts if part)


def _book_quote(quotes, tenant_id, conversation_id, at) -> None:
    if quotes is None:
        return
    getter = getattr(quotes, "get_quote", None)
    saver = getattr(quotes, "save_quote", None)
    if getter is None or saver is None:
        return
    found = getter(tenant_id, conversation_id)
    if found is None or found.current.state is not QuoteState.SITE_ASSESSMENT_OFFERED:
        return
    saver(tenant_id, conversation_id, found.transition(found.current.number, QuoteState.INSPECTION_BOOKED, at=at))
