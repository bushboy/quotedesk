from uuid import UUID

from pydantic import BaseModel, ConfigDict


class TenantContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    tenant_id: UUID
