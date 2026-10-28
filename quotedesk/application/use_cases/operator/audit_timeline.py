from uuid import UUID

from quotedesk.application.dto.audit import AuditEvent
from quotedesk.application.dto.tenant import TenantContext
from quotedesk.application.errors import TenantRequired
from quotedesk.application.ports.runtime import UnitOfWork


class AuditTimeline:
    def __init__(self, unit_of_work: UnitOfWork) -> None:
        self._unit = unit_of_work

    def execute(self, context: TenantContext | None, conversation_id: UUID) -> tuple[AuditEvent, ...]:
        if context is None:
            raise TenantRequired()
        return tuple(
            event
            for event in self._unit.list_audits(context.tenant_id)
            if event.conversation_id == conversation_id
        )
