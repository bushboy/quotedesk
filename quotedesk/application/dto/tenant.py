from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class TenantContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    tenant_id: UUID


class CommercialSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    discount_cap_percent: Decimal
