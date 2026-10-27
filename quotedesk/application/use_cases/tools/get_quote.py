from datetime import timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from quotedesk.application.dto.audit import AuditEvent
from quotedesk.application.dto.published import PublishedPolicy
from quotedesk.application.dto.tenant import TenantContext
from quotedesk.application.dto.tool_inputs import GetQuoteInput
from quotedesk.application.dto.tool_outputs import GetQuoteResult
from quotedesk.application.errors import CaseNotFound, TenantRequired
from quotedesk.application.ports.repositories import CaseFileRepository, PolicyRepository
from quotedesk.application.ports.runtime import Clock, IdGenerator, UnitOfWork
from quotedesk.domain.case.case_file import CaseFile
from quotedesk.domain.case.facts import CaseFacts, ExtractionFacts, JobKind, SegmentationFacts
from quotedesk.domain.policy.clauses import ClauseFacts
from quotedesk.domain.quotes.quote import Quote, QuoteLine
from quotedesk.domain.services.confidence import ConfidenceChecks, SizeSource
from quotedesk.domain.services.decide import decide
from quotedesk.domain.services.price import PriceFacts, RequestedItem, price
from quotedesk.domain.services.schedule import civil_date
from quotedesk.domain.services.select_clauses import select_clauses
from quotedesk.domain.shared.errors import PolicyViolation

_ZONE = ZoneInfo("Africa/Johannesburg")
_NOT_A_FLAG = "That fact is not true or false."


class GetQuote:
    def __init__(
        self,
        cases: CaseFileRepository,
        policies: PolicyRepository,
        unit_of_work: UnitOfWork,
        clock: Clock,
        ids: IdGenerator,
    ) -> None:
        self._cases = cases
        self._policies = policies
        self._unit = unit_of_work
        self._clock = clock
        self._ids = ids

    def execute(self, context: TenantContext | None, data: GetQuoteInput) -> GetQuoteResult:
        if context is None:
            raise TenantRequired()
        case = self._cases.get(context.tenant_id, data.conversation_id)
        if case is None:
            raise CaseNotFound()
        bundle = self._policies.published(context.tenant_id)
        if bundle is None:
            raise CaseNotFound()
        at = self._clock.now()
        expiry = civil_date(at, _ZONE) + timedelta(days=bundle.clause_policy.settings["validity_days"])
        case_facts, extraction = _facts(case)
        decision = decide(case_facts, extraction, SegmentationFacts(), bundle.policy)
        priced = price(decision, _price_facts(case_facts), bundle.rate_card)
        selection = select_clauses(decision, ClauseFacts(), case_facts.job.value, bundle.clause_policy)
        lines = tuple(
            QuoteLine(
                item_code=line.item_code,
                description=line.description,
                quantity=line.quantity,
                unit_price=line.unit_price,
                total=line.total,
            )
            for line in priced.lines
        )
        stored = self._unit.get_quote(context.tenant_id, data.conversation_id)
        if stored is None:
            quote_id = self._ids.next_quote_id()
            quote = Quote.open(quote_id, expiry)
            quote = quote.set_lines(1, lines)
            quote = quote.set_clauses(1, selection.conditions)
            quote = quote.issue(decision.outcome, version=1, at=at)
            action = "quote.issued"
        else:
            quote = stored.revise(
                decision.outcome,
                line_items=lines,
                clauses=selection.conditions,
                expiry=expiry,
                at=at,
            )
            action = "quote.revised"
        current = quote.current
        event = AuditEvent(
            tenant_id=context.tenant_id,
            action=action,
            quote_id=quote.quote_id,
            version=current.number,
        )
        try:
            self._unit.save_quote(context.tenant_id, data.conversation_id, quote)
            self._unit.record_audit(event)
            self._unit.commit()
        except Exception:
            self._unit.rollback()
            raise
        return GetQuoteResult(
            quote_id=quote.quote_id,
            version=current.number,
            state=current.state,
            policy_version=decision.policy_version,
            rule_id=decision.rule_id,
            outcome=decision.outcome,
            customer_template=decision.customer_template,
            lines=current.lines,
            clauses=current.clauses,
            price_type=priced.price_type,
            total=current.lines[0].total if len(current.lines) == 1 else None,
            range_min=priced.range_min,
            range_max=priced.range_max,
            site_visit_fee=priced.site_visit_fee,
            deposit=priced.deposit,
            schedule_status="none",
            expiry=current.expiry,
        )


def _facts(case: CaseFile) -> tuple[CaseFacts, ExtractionFacts]:
    job = case.jobs[0]
    values = {
        fact.key: fact.value
        for fact in case.facts(job.job_id)
        if fact.superseded_by is None and not fact.contested
    }

    def flag(key: str, default: bool) -> bool:
        raw = values.get(key)
        if raw is None:
            return default
        if raw == "true":
            return True
        if raw == "false":
            return False
        raise PolicyViolation(code="policy.violation", sentence=_NOT_A_FLAG)

    size = values.get("size_litres")
    stand = values.get("stand_condition")
    case_facts = CaseFacts(
        checks=ConfidenceChecks(
            required_fields=flag("required_fields", False),
            agreement=flag("agreement", False),
            measurement=flag("measurement", False),
            media_usable=flag("media_usable", False),
            rate_card=flag("rate_card", False),
        ),
        job=JobKind(values["job"]) if "job" in values else JobKind.UNKNOWN,
        customer_text=values.get("customer_text"),
        size_litres=int(size) if size is not None else None,
        size_source=SizeSource(values["size_source"]) if "size_source" in values else None,
        existing_level_base=flag("existing_level_base", False),
        item_codes=_codes(values.get("item_codes")),
    )
    extraction = ExtractionFacts(stand_condition=stand) if stand is not None else ExtractionFacts()
    return case_facts, extraction


def _codes(raw: str | None) -> tuple[str, ...]:
    if raw is None or raw.strip() == "":
        return ()
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def _price_facts(case_facts: CaseFacts) -> PriceFacts:
    return PriceFacts(
        items=tuple(
            RequestedItem(item_code=code, quantity=Decimal("1")) for code in case_facts.item_codes
        ),
        discount_percent=Decimal("0"),
    )
