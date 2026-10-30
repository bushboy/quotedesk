"""The note an owner can call from, built from the case rather than the chat."""

from pydantic import BaseModel, ConfigDict


class OwnerBrief(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    customer_number: str = ""
    customer_name: str = ""
    summary: str = ""
    jobs: tuple[str, ...] = ()
    known: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    unknown: tuple[str, ...] = ()
    media: tuple[str, ...] = ()
    outcome: str = ""
    rule_id: str = ""
    reason: str = ""
    quote: str = ""
    inspection: str = ""
    next_action: str = ""
    last_message: str = ""
    last_at: str = ""


def render_brief(brief: OwnerBrief) -> str:
    """Every field is present, so a missing one still reads as none."""
    who = " ".join(part for part in (brief.customer_name, brief.customer_number) if part).strip() or "not given"
    lines = [
        f"Customer: {who}",
        f"Wants: {brief.summary.strip() or 'not said'}",
        f"Jobs: {', '.join(brief.jobs) or 'none'}",
        f"Known: {_lines(brief.known)}",
        f"Missing: {', '.join(brief.missing) or 'none'}",
        f"Unknown: {', '.join(brief.unknown) or 'none'}",
        f"Photos and voice notes: {_lines(brief.media)}",
        f"Outcome: {brief.outcome or 'none'} {brief.rule_id}".strip(),
        f"Reason: {brief.reason.strip() or 'none'}",
        f"Quote: {brief.quote or 'none'}",
        f"Inspection: {brief.inspection or 'none'}",
        f"Next: {brief.next_action.strip() or 'none'}",
        f"Last: {brief.last_message.strip() or 'none'} at {brief.last_at or 'unknown'}",
    ]
    return "\n".join(lines)


def _lines(items: tuple[str, ...]) -> str:
    if not items:
        return "none"
    return "; ".join(items)
