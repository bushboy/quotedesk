import re

from quotedesk.application.dto.published import PublishedPolicy
from quotedesk.application.dto.tenant import TenantContext
from quotedesk.application.dto.tool_inputs import PublishInput
from quotedesk.application.errors import TenantRequired
from quotedesk.application.ports.runtime import Clock, UnitOfWork
from quotedesk.domain.policy.clauses import ClausePolicy
from quotedesk.domain.policy.draft import PolicyDraft
from quotedesk.domain.services.price import RateCard, RateCardItem
from quotedesk.domain.services.validate_policy import validate_policy
from quotedesk.domain.shared.errors import PolicyViolation, ValidationError
from quotedesk.domain.shared.ids import PolicyVersionId
from quotedesk.domain.shared.money import Money

_VERSION = re.compile(r"^(?P<head>.+-policy-v)(?P<major>\d+)\.(?P<minor>\d+)$")
_REASON = "A publish needs a reason."
_NO_DRAFT = "There is no draft to publish."


class PublishPolicy:
    def __init__(self, policies, unit_of_work: UnitOfWork, clock: Clock) -> None:
        self._policies = policies
        self._unit = unit_of_work
        self._clock = clock

    def execute(self, context: TenantContext | None, data: PublishInput) -> PolicyVersionId:
        if context is None:
            raise TenantRequired()
        _require_reason(data.reason)
        existing = self._policies.find_publish(context.tenant_id, data.idempotency_key)
        if existing is not None:
            return existing
        draft = self._policies.draft(context.tenant_id)
        if draft is None:
            raise PolicyViolation(code="policy.violation", sentence=_NO_DRAFT)
        errors = validate_policy(draft)
        if errors:
            raise PolicyViolation(code="policy.violation", sentence=errors[0].sentence)
        current = self._policies.published(context.tenant_id)
        if current is None:
            raise PolicyViolation(code="policy.violation", sentence=_NO_DRAFT)
        version = next_version(current.policy.version)
        bundle = _bundle(current, draft, version)
        try:
            self._policies.save_published(context.tenant_id, bundle)
            self._policies.remember_publish(context.tenant_id, data.idempotency_key, version)
            self._unit.commit()
        except Exception:
            self._unit.rollback()
            raise
        return version


def next_version(current: PolicyVersionId) -> PolicyVersionId:
    match = _VERSION.fullmatch(current.value)
    if match is None:
        raise PolicyViolation(code="policy.violation", sentence="That policy version cannot be published.")
    minor = int(match.group("minor")) + 1
    return PolicyVersionId(f"{match.group('head')}{match.group('major')}.{minor}")


def _enabled(edit) -> bool:
    return True if edit is None else edit.enabled


def _edited(rule, edit):
    if edit is None:
        return rule
    updates = {}
    if edit.customer_template is not None:
        updates["customer_template"] = edit.customer_template
    if edit.reason is not None:
        updates["reason"] = edit.reason
    if edit.when is not None:
        updates["when"] = edit.when
    return rule.model_copy(update=updates) if updates else rule


def _require_reason(reason: str) -> None:
    if reason.strip() == "":
        raise ValidationError(code="publish.reason", sentence=_REASON)


def _bundle(current: PublishedPolicy, draft: PolicyDraft, version: PolicyVersionId) -> PublishedPolicy:
    edits = {rule.rule_id: rule for rule in draft.rules}
    rules = tuple(
        _edited(rule, edits.get(rule.rule_id.value))
        for rule in current.policy.rules
        if _enabled(edits.get(rule.rule_id.value))
    )
    codes = tuple(row.item_code for row in draft.rate_rows)
    settings = dict(current.clause_policy.settings)
    settings["deposit_percent"] = draft.deposit_percent
    settings["validity_days"] = draft.validity_days
    return PublishedPolicy(
        policy=current.policy.model_copy(update={"version": version, "rules": rules, "rate_card_codes": codes}),
        rate_card=RateCard(
            vat_inclusive=draft.vat_inclusive,
            site_visit_fee=current.rate_card.site_visit_fee,
            items=tuple(
                RateCardItem(
                    item_code=row.item_code,
                    description=row.description or row.item_code,
                    unit_price=Money(row.unit_price),
                    unit=row.unit if row.unit in ("each", "per m²", "per metre") else "each",
                    role=row.role if row.role in ("product", "frame", "hardware", "installation", "delivery", "inspection") else "product",
                )
                for row in draft.rate_rows
            ),
        ),
        clause_policy=ClausePolicy(
            templates=current.clause_policy.templates,
            settings=settings,
            rate_card_codes=codes,
        ),
        playbook=draft.playbook if draft.playbook.populated() else current.playbook,
    )
