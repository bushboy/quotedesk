import re
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
        case_facts, extraction = _facts(case, bundle.rate_card)
        decision = decide(case_facts, extraction, SegmentationFacts(), bundle.policy)
        priced = price(decision, _price_facts(case_facts, bundle.rate_card), bundle.rate_card)
        priced = _scale_carport(priced, case_facts)
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


_SPAN = re.compile(r"(\d+(?:\.\d+)?)\s*(?:x|×|by)\s*(\d+(?:\.\d+)?)", re.IGNORECASE)


def _facts(case: CaseFile, rate_card=None) -> tuple[CaseFacts, ExtractionFacts]:
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

    size = values.get("size_litres") or values.get("tank_size")
    stand = values.get("stand_condition")
    width = _decimal(values.get("width_m"))
    length = _decimal(values.get("length_m"))
    spanned = _span(values.get("size") or values.get("dimensions"))
    if width is None:
        width = spanned[0]
    if length is None:
        length = spanned[1]
    finish = values.get("finish")
    codes = _codes(values.get("item_codes"))
    matched = _match_card(values.get("item") or finish, rate_card)
    if not codes and matched is not None:
        codes = (matched,)
    if not finish and matched is not None and rate_card is not None:
        finish = next(item.description for item in rate_card.items if item.item_code == matched)
    opening = values.get("opening")
    case_facts = CaseFacts(
        checks=ConfidenceChecks(
            required_fields=flag("required_fields", False),
            agreement=flag("agreement", False),
            measurement=flag("measurement", False),
            media_usable=flag("media_usable", False),
            rate_card=flag("rate_card", False),
        ),
        job=_job_kind(values.get("job") or values.get("job_type") or job.job_type),
        customer_text=values.get("customer_text"),
        size_litres=_litres(size),
        size_source=SizeSource(values["size_source"]) if "size_source" in values else None,
        existing_level_base=flag("existing_level_base", False),
        installation_damaged=flag("installation_damaged", False),
        simple_swap=_optional_flag(values.get("simple_swap")),
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
    extraction = ExtractionFacts(stand_condition=stand) if stand is not None else ExtractionFacts()
    return case_facts, extraction


def _span(raw: str | None) -> tuple[Decimal | None, Decimal | None]:
    if raw is None:
        return None, None
    match = _SPAN.search(raw)
    if match is None:
        return None, None
    return Decimal(match.group(1)), Decimal(match.group(2))


def _match_card(raw: str | None, rate_card) -> str | None:
    if raw is None or rate_card is None:
        return None
    folded = " ".join(raw.casefold().split())
    for item in rate_card.items:
        description = item.description.casefold()
        if folded in (item.item_code.casefold(), description) or description in folded:
            return item.item_code
    return None


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


def _price_facts(case_facts: CaseFacts, rate_card=None) -> PriceFacts:
    codes = case_facts.item_codes or _tank_codes(case_facts.size_litres, rate_card) or _sheet_codes(case_facts, rate_card)
    quantity = _area(case_facts) or Decimal("1")
    return PriceFacts(
        items=tuple(RequestedItem(item_code=code, quantity=quantity) for code in codes),
        discount_percent=Decimal("0"),
    )


def _area(case_facts: CaseFacts) -> Decimal | None:
    if case_facts.width_m is None or case_facts.length_m is None:
        return None
    sheets = any(code.startswith("SHEET-") for code in case_facts.item_codes)
    if case_facts.job_type == "carport" or sheets:
        return case_facts.width_m * case_facts.length_m
    return None


def _scale_carport(priced, case_facts: CaseFacts):
    area = _area(case_facts)
    if area is None or priced.price_type != "range" or priced.range_min is None:
        return priced
    return priced.model_copy(
        update={
            "range_min": priced.range_min * area,
            "range_max": None if priced.range_max is None else priced.range_max * area,
        }
    )


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
