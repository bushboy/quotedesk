"""The customer text and ask counts the planner needs, read from the conversation."""

from quotedesk.domain.policy.playbook import BusinessPlaybook


def planner_inputs(conversations, tenant_id, conversation_id, playbook: BusinessPlaybook) -> tuple[str, dict[str, int]]:
    return _text(conversations, tenant_id, conversation_id), _asked(conversations, tenant_id, conversation_id, playbook)


def _text(conversations, tenant_id, conversation_id) -> str:
    if conversations is None:
        return ""
    getter = getattr(conversations, "get", None)
    if getter is not None:
        conversation = getter(tenant_id, conversation_id)
        if conversation is not None and getattr(conversation, "events", None):
            return conversation.events[-1].body or ""
    reader = getattr(conversations, "messages", None)
    if reader is None:
        return ""
    spoken = [message for message in reader(tenant_id, conversation_id) if (message.body or "").strip()]
    if not spoken:
        return ""
    return spoken[-1].body or ""


def _asked(conversations, tenant_id, conversation_id, playbook: BusinessPlaybook) -> dict[str, int]:
    replies = None if conversations is None else getattr(conversations, "replies", None)
    rows = () if replies is None else replies(tenant_id, conversation_id)
    counts: dict[str, int] = {}
    for job in playbook.job_types:
        for fact in job.facts:
            question = fact.question.strip()
            if question:
                counts[fact.key] = sum(1 for _, body in rows if question in (body or ""))
    return counts
