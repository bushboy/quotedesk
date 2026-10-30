from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

FactType = Literal["number", "choice", "yes_no", "text"]


class FactDefinition(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    type: FactType = "text"
    unit: str = ""
    allowed: tuple[str, ...] = ()
    question: str = ""
    photo_can_answer: bool = False
    required: bool = False


class JobTypePlay(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    description: str = ""
    item_codes: tuple[str, ...] = ()
    pricing: str = ""
    installation: str = ""
    delivery: str = ""
    facts: tuple[FactDefinition, ...] = ()


class InspectionTrigger(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    condition: str
    rule_id: str
    fee: str = ""


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
