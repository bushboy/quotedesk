from quotedesk.application.dto.tenant import TenantContext
from quotedesk.application.dto.tool_inputs import RollbackInput
from quotedesk.application.errors import TenantRequired
from quotedesk.application.ports.runtime import Clock, UnitOfWork
from quotedesk.application.use_cases.editor.publish_policy import _require_reason, next_version
from quotedesk.domain.shared.errors import PolicyViolation
from quotedesk.domain.shared.ids import PolicyVersionId

_MISSING = "That policy version is not on file."


class RollbackPolicy:
    def __init__(self, policies, unit_of_work: UnitOfWork, clock: Clock) -> None:
        self._policies = policies
        self._unit = unit_of_work
        self._clock = clock

    def execute(self, context: TenantContext | None, data: RollbackInput) -> PolicyVersionId:
        if context is None:
            raise TenantRequired()
        _require_reason(data.reason)
        existing = self._policies.find_publish(context.tenant_id, data.idempotency_key)
        if existing is not None:
            return existing
        source = self._policies.get(context.tenant_id, data.source_version)
        current = self._policies.published(context.tenant_id)
        if source is None or current is None:
            raise PolicyViolation(code="policy.violation", sentence=_MISSING)
        version = next_version(current.policy.version)
        bundle = source.model_copy(update={"policy": source.policy.model_copy(update={"version": version})})
        try:
            self._policies.save_published(context.tenant_id, bundle)
            self._policies.remember_publish(context.tenant_id, data.idempotency_key, version)
            self._unit.commit()
        except Exception:
            self._unit.rollback()
            raise
        return version
