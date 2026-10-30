"""An inspection the business can carry out. The quote state records when it is booked."""

from datetime import date, datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class InspectionStatus(str, Enum):
    OFFERED = "offered"
    BOOKED = "booked"
    COMPLETED = "completed"


class Inspection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    inspection_id: UUID
    tenant_id: UUID
    conversation_id: UUID
    job_id: str
    address: str = ""
    rule_id: str = ""
    fee: str = ""
    window_start: date | None = None
    window_end: date | None = None
    status: InspectionStatus = InspectionStatus.OFFERED
    summary: str = ""
    at: datetime
