from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

FactType = Literal["number", "choice", "yes_no", "text"]
Decides = Literal["price", "outcome", "both"]
Ease = Literal["easy", "needs_tape", "needs_expert"]
IfUnsure = Literal["ask_photo", "range", "inspection", "photo_then_range"]


class FactOption(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    value: str
    label: str
    hint: str = ""
    item_codes: tuple[str, ...] = ()


class FactDefinition(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    type: FactType = "text"
    unit: str = ""
    allowed: tuple[str, ...] = ()
    question: str = ""
    photo_can_answer: bool = False
    required: bool = False
    label: str = ""
    options: tuple[FactOption, ...] = ()
    look_for: str = ""
    min_confidence: Decimal | None = None
    decides: Decides = "price"
    ease: Ease = "easy"
    if_unsure: IfUnsure = "inspection"


class JobTypePlay(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    description: str = ""
    label: str = ""
    item_codes: tuple[str, ...] = ()
    roles: tuple[str, ...] = ()
    pricing: str = ""
    installation: str = ""
    delivery: str = ""
    facts: tuple[FactDefinition, ...] = ()


class InspectionTrigger(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    condition: str
    rule_id: str
    fee: str = ""
    fee_item: str = ""


class EscalationTrigger(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    condition: str
    rule_id: str


class CommonQuestion(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    topic: str
    answer: str


class BusinessPlaybook(BaseModel):
    """Owner-written business knowledge. It is data on a policy version, not a prompt constant."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = ""
    trade: str = ""
    area: str = ""
    hours: str = ""
    tone: str = ""
    languages: str = ""
    does_not: str = ""
    guidance: str = ""
    owner_whatsapp: str = ""
    owner_email: str = ""
    job_types: tuple[JobTypePlay, ...] = ()
    inspections: tuple[InspectionTrigger, ...] = ()
    escalations: tuple[EscalationTrigger, ...] = ()
    questions: tuple[CommonQuestion, ...] = Field(default=())

    def required(self, job_type: str) -> tuple[str, ...]:
        for job in self.job_types:
            if job.key == job_type:
                return tuple(fact.key for fact in job.facts if fact.required)
        return ()

    def populated(self) -> bool:
        return bool(self.guidance.strip() or self.job_types or self.questions or self.inspections or self.escalations)
