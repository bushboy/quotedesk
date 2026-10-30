from datetime import timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from quotedesk.application.dto.audit import AuditEvent
from quotedesk.application.dto.published import PublishedPolicy
from quotedesk.application.dto.tenant import TenantContext
from quotedesk.application.dto.tool_inputs import GetQuoteInput
from quotedesk.application.dto.tool_outputs import GetQuoteResult
from quotedesk.application.errors import CaseNotFound, TenantRequired
from quotedesk.application.ports.repositories import CaseFileRepository, PolicyRepository, VerificationCodes
from quotedesk.application.ports.runtime import Clock, IdGenerator, UnitOfWork
from quotedesk.domain.case.case_file import CaseFile
from quotedesk.domain.case.facts import CaseFacts, ExtractionFacts, JobKind, SegmentationFacts
from quotedesk.domain.policy.clauses import ClauseFacts, ClauseSelection
from quotedesk.domain.policy.rules import Decision, Outcome
from quotedesk.domain.quotes.quote import Quote, QuoteLine
from quotedesk.domain.services.confidence import ConfidenceChecks, SizeSource
from quotedesk.domain.services.decide import decide
from quotedesk.domain.services.price import PriceFacts, PricedQuote, RequestedItem, price
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
        codes: VerificationCodes | None = None,
    ) -> None:
        self._cases = cases
        self._policies = policies
        self._unit = unit_of_work
        self._clock = clock
        self._ids = ids
        self._codes = codes

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
        if not case.jobs:
            raise CaseNotFound()
        quoted = [
            _quote_job(case, job, bundle)
            for job in case.jobs
        ]
        decision, case_facts, priced = _primary(quoted)
        priced = _combine(quoted, priced)
        deposit = _deposit(priced, int(bundle.clause_policy.settings["deposit_percent"]))
        priced = priced.model_copy(update={"deposit": deposit})
        try:
            selection = select_clauses(
                decision,
                ClauseFacts(width_m=case_facts.width_m, length_m=case_facts.length_m),
                case_facts.job_type if case_facts.job_type is not None else case_facts.job.value,
                bundle.clause_policy,
            )
        except PolicyViolation:
            if bundle.clause_policy.templates:
                raise
            selection = ClauseSelection(conditions=(), customer_template=decision.customer_template)
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
            quote = quote.set_terms(1, **_terms(priced))
            quote = quote.issue(decision.outcome, version=1, at=at)
            action = "quote.issued"
        else:
            quote = stored.revise(
                decision.outcome,
                line_items=lines,
                clauses=selection.conditions,
                expiry=expiry,
                at=at,
                **_terms(priced),
            )
            action = "quote.revised"
        quote = quote.record_decision(
            outcome=decision.outcome.value,
            rule_id=decision.rule_id.value,
            reasons=decision.reasons,
            policy_version=decision.policy_version.value,
            facts_used=_facts_used(case),
        )
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
            verification_code=None if self._codes is None else self._codes.issue(context.tenant_id, quote.quote_id),
        )


_RANK = {
    Outcome.ESCALATION: 0,
    Outcome.SITE_ASSESSMENT: 1,
    Outcome.INDICATIVE_RANGE: 2,
    Outcome.FIXED_OFFER: 3,
}


def _quote_job(case: CaseFile, job, bundle):
    case_facts, extraction = _facts(case, job)
    decision = decide(case_facts, extraction, SegmentationFacts(), bundle.policy)
    priced = price(decision, _price_facts(case_facts, bundle.rate_card, bundle.playbook), bundle.rate_card)
    return decision, case_facts, priced


def _primary(quoted: list[tuple[Decision, CaseFacts, PricedQuote]]):
    return min(quoted, key=lambda row: _RANK[row[0].outcome])


def _combine(quoted, priced: PricedQuote) -> PricedQuote:
    if priced.price_type == "fixed":
        lines = tuple(line for _decision, _facts, item in quoted for line in item.lines)
        return priced.model_copy(update={"lines": lines}) if lines else priced
    if priced.price_type != "range":
        return priced
    lows = [item.range_min for _decision, _facts, item in quoted if item.range_min is not None]
    highs = [item.range_max for _decision, _facts, item in quoted if item.range_max is not None]
    if not lows or not highs:
        return priced
    return priced.model_copy(
        update={
            "range_min": min(lows, key=lambda amount: amount.amount),
            "range_max": max(highs, key=lambda amount: amount.amount),
        }
    )


def _facts(case: CaseFile, job) -> tuple[CaseFacts, ExtractionFacts]:
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
    width = _decimal(values.get("width_m"))
    length = _decimal(values.get("length_m"))
    finish = values.get("finish")
    codes = _codes(values.get("item_codes"))
    opening = values.get("opening")
    stated = _size_source(case, job.job_id)
    case_facts = CaseFacts(
        checks=ConfidenceChecks(
            required_fields=flag("required_fields", False),
            agreement=flag("agreement", False),
            measurement=flag("measurement", False),
            media_usable=flag("media_usable", False),
            rate_card=flag("rate_card", False),
        ),
        job=_job_kind(job.job_type or values.get("job_type")),
        customer_text=values.get("customer_text"),
        size_litres=_litres(size),
        size_source=stated,
        existing_level_base=flag("existing_level_base", False),
        installation_damaged=flag("installation_damaged", False),
        simple_swap=_optional_flag(values.get("simple_swap")),
        base_unconfirmed=flag("base_unconfirmed", False),
        new_tank_and_pump=flag("new_tank_and_pump", False),
        sloped_ground=flag("sloped_ground", False),
        pipe_run_unknown=flag("pipe_run_unknown", False),
        item_codes=codes,
        width_m=width,
        length_m=length,
        finish=finish,
        opening=opening if opening in ("existing", "new", "widened") else None,
        above_ground_floor=flag("above_ground_floor", False),
        multi_unit=flag("multi_unit", False),
        standard_band=flag("standard_band", False),
        budget=_decimal(values.get("budget")),
        job_type=_job_type(values.get("job_type") or job.job_type),
    )
    stand_value = stand if stand in ("sound", "leaning", "cracked", "sagging") else None
    extraction = ExtractionFacts(
        stand_condition=stand_value,
        elevated=flag("elevated", False),
        structure_damage=flag("structure_damage", False),
        exposed_wiring=flag("exposed_wiring", False),
        active_flooding=flag("active_flooding", False),
        lintel_cracked=flag("lintel_cracked", False),
        glass_broken=flag("glass_broken", False),
        possible_asbestos=flag("possible_asbestos", False),
    )
    return case_facts, extraction


def _size_source(case: CaseFile, job_id: str):
    stated = None
    for fact in case.facts(job_id):
        if fact.superseded_by is not None or fact.contested:
            continue
        if fact.key == "size_source" and fact.value in ("photo_inferred", "customer_stated", "reference_object"):
            return SizeSource(fact.value)
        if fact.key == "size_litres" and fact.source == "customer_text":
            stated = SizeSource.CUSTOMER_STATED
    return stated


def _decimal(raw: str | None) -> Decimal | None:
    if raw is None or raw.strip() == "":
        return None
    return Decimal(raw)


def _litres(raw: str | None) -> int | None:
    if raw is None:
        return None
    digits = "".join(character for character in raw if character.isdigit())
    if digits == "":
        return None
    return int(digits)


def _job_kind(raw: str | None) -> JobKind:
    if raw is None:
        return JobKind.UNKNOWN
    folded = raw.casefold().replace("-", "_").replace(" ", "_")
    if folded in ("replacement", "swap", "tank_swap"):
        return JobKind.REPLACEMENT
    if folded in ("new_system", "new", "installation", "new_installation", "new_install"):
        return JobKind.NEW_SYSTEM
    if folded == "borehole":
        return JobKind.BOREHOLE
    return JobKind.UNKNOWN


def _optional_flag(raw: str | None) -> bool | None:
    if raw is None:
        return None
    if raw == "true":
        return True
    if raw == "false":
        return False
    raise PolicyViolation(code="policy.violation", sentence=_NOT_A_FLAG)


def _job_type(raw: str | None) -> str | None:
    if raw in ("carport", "window", "door", "shutter"):
        return raw
    return None


def _codes(raw: str | None) -> tuple[str, ...]:
    if raw is None or raw.strip() == "":
        return ()
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def _price_facts(case_facts: CaseFacts, rate_card=None, playbook=None) -> PriceFacts:
    codes = case_facts.item_codes or _tank_codes(case_facts.size_litres, rate_card) or _sheet_codes(case_facts, rate_card)
    return PriceFacts(
        items=tuple(RequestedItem(item_code=code, quantity=Decimal("1")) for code in codes),
        discount_percent=Decimal("0"),
        width_m=case_facts.width_m,
        length_m=case_facts.length_m,
        roles=_roles(playbook, case_facts.job_type),
    )


def _roles(playbook, job_type: str | None) -> tuple[str, ...]:
    if playbook is None or not job_type:
        return ()
    for job in playbook.job_types:
        if job.key == job_type:
            return tuple(role for role in job.roles if role in ("product", "frame", "hardware", "installation", "delivery", "inspection"))
    return ()


def _facts_used(case: CaseFile) -> tuple[str, ...]:
    used = []
    for job in case.jobs:
        for fact in case.facts(job.job_id):
            if fact.superseded_by is not None or fact.contested or not fact.value.strip():
                continue
            used.append(f"{fact.key}={fact.value}")
    return tuple(used)


def _deposit(priced, percent: int):
    if percent <= 0:
        return None
    if priced.price_type == "fixed" and priced.lines:
        total = priced.lines[0].total
        for line in priced.lines[1:]:
            total = total + line.total
        return total * (Decimal(percent) / Decimal("100"))
    if priced.price_type == "range" and priced.range_min is not None:
        return priced.range_min * (Decimal(percent) / Decimal("100"))
    return None


def _terms(priced) -> dict:
    return {
        "price_type": priced.price_type,
        "range_min": priced.range_min,
        "range_max": priced.range_max,
        "deposit": priced.deposit,
        "site_visit_fee": priced.site_visit_fee,
    }


def _sheet_codes(case_facts: CaseFacts, rate_card) -> tuple[str, ...]:
    if case_facts.width_m is None or case_facts.length_m is None or rate_card is None:
        return ()
    return tuple(item.item_code for item in rate_card.items if item.item_code.startswith("SHEET-"))


def _tank_codes(litres: int | None, rate_card) -> tuple[str, ...]:
    if litres is None or rate_card is None:
        return ()
    exact = {2500: "TANK-2500", 5000: "TANK-5000", 10000: "TANK-10000"}.get(litres)
    published = tuple(item.item_code for item in rate_card.items)
    if exact in published:
        return (exact,)
    tanks = tuple(code for code in published if code.startswith("TANK-"))
    return tanks
