from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from quotedesk.domain.policy.clauses import Condition
from quotedesk.domain.policy.rules import Outcome
from quotedesk.domain.shared.errors import InvalidTransition, PolicyViolation, StaleQuote, ValidationError
from quotedesk.domain.shared.ids import QuoteId
from quotedesk.domain.shared.money import Money

_FIXED = "An issued version cannot be changed."
_ILLEGAL = "That state change is not allowed."
_STALE = "That version is no longer the current quote."
_EXPIRY = "A quote expiry is a calendar date."
_OTHER_VERSION = "An approval applies to one version."
_AFTER_EXPIRY = "An approval after expiry does not apply."


class QuoteState(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    ISSUED = "ISSUED"
    SITE_ASSESSMENT_OFFERED = "SITE_ASSESSMENT_OFFERED"
    INSPECTION_BOOKED = "INSPECTION_BOOKED"
    ESCALATED = "ESCALATED"
    WAITING_FOR_DEPOSIT = "WAITING_FOR_DEPOSIT"
    DEPOSIT_PAID = "DEPOSIT_PAID"
    BOOKING_CONFIRMED = "BOOKING_CONFIRMED"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"
    REVISED = "REVISED"


_LEGAL: dict[QuoteState, frozenset[QuoteState]] = {
    QuoteState.DRAFT: frozenset(
        {
            QuoteState.ISSUED,
            QuoteState.SITE_ASSESSMENT_OFFERED,
            QuoteState.ESCALATED,
            QuoteState.PENDING_APPROVAL,
        }
    ),
    QuoteState.PENDING_APPROVAL: frozenset(
        {
            QuoteState.ISSUED,
            QuoteState.SITE_ASSESSMENT_OFFERED,
            QuoteState.ESCALATED,
            QuoteState.REJECTED,
            QuoteState.REVISED,
        }
    ),
    QuoteState.ISSUED: frozenset(
        {
            QuoteState.WAITING_FOR_DEPOSIT,
            QuoteState.EXPIRED,
            QuoteState.REVISED,
            QuoteState.PENDING_APPROVAL,
        }
    ),
    QuoteState.WAITING_FOR_DEPOSIT: frozenset(
        {
            QuoteState.DEPOSIT_PAID,
            QuoteState.EXPIRED,
            QuoteState.REVISED,
        }
    ),
    QuoteState.DEPOSIT_PAID: frozenset({QuoteState.BOOKING_CONFIRMED, QuoteState.EXPIRED}),
    QuoteState.SITE_ASSESSMENT_OFFERED: frozenset(
        {
            QuoteState.INSPECTION_BOOKED,
            QuoteState.EXPIRED,
            QuoteState.REVISED,
            QuoteState.PENDING_APPROVAL,
        }
    ),
    QuoteState.INSPECTION_BOOKED: frozenset({QuoteState.EXPIRED, QuoteState.REVISED}),
    QuoteState.ESCALATED: frozenset({QuoteState.PENDING_APPROVAL, QuoteState.EXPIRED, QuoteState.REVISED}),
    QuoteState.EXPIRED: frozenset({QuoteState.REVISED}),
}

_FROM_OUTCOME = {
    Outcome.FIXED_OFFER: QuoteState.ISSUED,
    Outcome.INDICATIVE_RANGE: QuoteState.ISSUED,
    Outcome.SITE_ASSESSMENT: QuoteState.SITE_ASSESSMENT_OFFERED,
    Outcome.ESCALATION: QuoteState.ESCALATED,
}


class QuoteLine(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    item_code: str
    description: str
    quantity: Decimal
    unit_price: Money
    total: Money


class Approval(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    applies_to_version: int
    expires_at: datetime


class QuoteVersion(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    number: int
    state: QuoteState
    expiry: date
    lines: tuple[QuoteLine, ...]
    clauses: tuple[Condition, ...]
    approvals: tuple[Approval, ...]
    at: datetime | None = None
    price_type: Literal["fixed", "range", "none"] | None = None
    range_min: Money | None = None
    range_max: Money | None = None
    deposit: Money | None = None
    site_visit_fee: Money | None = None
    outcome: str = ""
    rule_id: str = ""
    reasons: tuple[str, ...] = ()
    policy_version: str = ""
    facts_used: tuple[str, ...] = ()
    included: tuple[str, ...] = ()


def _expiry(value: Any) -> date:
    if type(value) is date:
        return value
    raise ValidationError(code="quote.expiry_not_a_date", sentence=_EXPIRY)


class Quote(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    quote_id: QuoteId
    versions: tuple[QuoteVersion, ...]

    @classmethod
    def open(cls, quote_id: QuoteId, expiry: date) -> "Quote":
        version = QuoteVersion(
            number=1,
            state=QuoteState.DRAFT,
            expiry=_expiry(expiry),
            lines=(),
            clauses=(),
            approvals=(),
            at=None,
        )
        return cls(quote_id=quote_id, versions=(version,))

    @property
    def current(self) -> QuoteVersion:
        return self.versions[-1]

    def version(self, number: int) -> QuoteVersion:
        for item in self.versions:
            if item.number == number:
                return item
        raise StaleQuote(code="quote.stale", sentence=_STALE)

    def issue(self, outcome: Outcome, *, version: int, at: datetime) -> "Quote":
        self._require_current(version)
        return self._move(version, _FROM_OUTCOME[outcome], at)

    def transition(self, version: int, to: QuoteState, *, at: datetime) -> "Quote":
        self._require_current(version)
        return self._move(version, to, at)

    def set_lines(self, version: int, lines: tuple[QuoteLine, ...]) -> "Quote":
        self._require_current(version)
        self._require_draft()
        return self._replace(self.current.model_copy(update={"lines": tuple(lines)}))

    def set_clauses(self, version: int, clauses: tuple[Condition, ...]) -> "Quote":
        self._require_current(version)
        self._require_draft()
        return self._replace(self.current.model_copy(update={"clauses": tuple(clauses)}))

    def set_expiry(self, version: int, expiry: date) -> "Quote":
        civil = _expiry(expiry)
        self._require_current(version)
        self._require_draft()
        return self._replace(self.current.model_copy(update={"expiry": civil}))

    def set_terms(
        self,
        version: int,
        *,
        price_type: Literal["fixed", "range", "none"],
        range_min: Money | None,
        range_max: Money | None,
        deposit: Money | None,
        site_visit_fee: Money | None,
        included: tuple[str, ...] = (),
    ) -> "Quote":
        self._require_current(version)
        self._require_draft()
        return self._replace(
            self.current.model_copy(
                update={
                    "price_type": price_type,
                    "range_min": range_min,
                    "range_max": range_max,
                    "deposit": deposit,
                    "site_visit_fee": site_visit_fee,
                    "included": tuple(included),
                }
            )
        )

    def record_decision(
        self,
        *,
        outcome: str,
        rule_id: str,
        reasons: tuple[str, ...],
        policy_version: str,
        facts_used: tuple[str, ...],
    ) -> "Quote":
        updated = self.current.model_copy(
            update={
                "outcome": outcome,
                "rule_id": rule_id,
                "reasons": tuple(reasons),
                "policy_version": policy_version,
                "facts_used": tuple(facts_used),
            }
        )
        return self._replace(updated)

    def revise(
        self,
        outcome: Outcome,
        *,
        line_items: tuple[QuoteLine, ...],
        clauses: tuple[Condition, ...],
        expiry: date,
        at: datetime,
        price_type: Literal["fixed", "range", "none"] | None = None,
        range_min: Money | None = None,
        range_max: Money | None = None,
        deposit: Money | None = None,
        site_visit_fee: Money | None = None,
        included: tuple[str, ...] = (),
    ) -> "Quote":
        current = self.current
        if QuoteState.REVISED not in _LEGAL.get(current.state, frozenset()):
            raise InvalidTransition(code="quote.invalid_transition", sentence=_ILLEGAL)
        revised = current.model_copy(update={"state": QuoteState.REVISED, "at": at})
        successor = QuoteVersion(
            number=current.number + 1,
            state=_FROM_OUTCOME[outcome],
            expiry=_expiry(expiry),
            lines=tuple(line_items),
            clauses=tuple(clauses),
            approvals=(),
            at=at,
            price_type=price_type,
            range_min=range_min,
            range_max=range_max,
            deposit=deposit,
            site_visit_fee=site_visit_fee,
            included=tuple(included),
        )
        kept = tuple(revised if item.number == current.number else item for item in self.versions)
        return self.model_copy(update={"versions": kept + (successor,)})

    def apply_approval(self, version: int, approval: Approval, *, at: datetime) -> "Quote":
        self._require_current(version)
        if approval.applies_to_version != version:
            raise PolicyViolation(code="policy.violation", sentence=_OTHER_VERSION)
        if at > approval.expires_at:
            raise PolicyViolation(code="policy.violation", sentence=_AFTER_EXPIRY)
        current = self.current
        updated = current.model_copy(
            update={"approvals": current.approvals + (approval,), "at": at}
        )
        return self._replace(updated)

    def _require_current(self, version: int) -> None:
        if version != self.current.number:
            raise StaleQuote(code="quote.stale", sentence=_STALE)

    def _require_draft(self) -> None:
        if self.current.state is not QuoteState.DRAFT:
            raise PolicyViolation(code="policy.violation", sentence=_FIXED)

    def _move(self, version: int, to: QuoteState, at: datetime) -> "Quote":
        if to not in _LEGAL.get(self.current.state, frozenset()):
            raise InvalidTransition(code="quote.invalid_transition", sentence=_ILLEGAL)
        updated = self.current.model_copy(update={"state": to, "at": at})
        return self._replace(updated)

    def _replace(self, updated: QuoteVersion) -> "Quote":
        versions = tuple(updated if item.number == updated.number else item for item in self.versions)
        return self.model_copy(update={"versions": versions})
