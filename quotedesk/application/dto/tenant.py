"""The tenant DTOs. Every use case takes a tenant context, and settings carry the commercial caps."""

from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class TenantContext(BaseModel):
    """The TenantContext."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    tenant_id: UUID


class CommercialSettings(BaseModel):
    """The CommercialSettings."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    discount_cap_percent: Decimal
