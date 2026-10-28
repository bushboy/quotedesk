from datetime import datetime, timedelta
from uuid import UUID

from quotedesk.application.dto.agent import Handover, ModelReply, TurnPrompt
from quotedesk.application.dto.tenant import TenantContext
from quotedesk.application.dto.tool_inputs import GetQuoteInput, UpdateCaseInput
from quotedesk.application.errors import ModelTimeout, TenantRequired
from quotedesk.application.ports.agent import AgentModel, ConversationLock
from quotedesk.application.ports.gate import ChannelSender
from quotedesk.application.ports.repositories import CaseFileRepository, ConversationRepository
from quotedesk.application.ports.runtime import Clock
from quotedesk.domain.conversation.events import ConversationEvent
from quotedesk.domain.services.commitments import TurnFacts, check_reply
from quotedesk.domain.shared.money import Money

_REFUSAL = "I can only repeat what the quote says."
_VIDEO = "Got your video, having a look."
_HANDOVER = "I'll ask someone from the business to pick this up. You can keep sending details here."
_PHRASE = "can i speak to a person?"
_PHRASE_REASON = "Can I speak to a person?"
_TIMEOUT_REASON = "model timeout"


def close_batch(
    events: tuple[ConversationEvent, ...] | list[ConversationEvent],
    *,
    window: timedelta,
    now: datetime,
) -> tuple[ConversationEvent, ...] | None:
    if not events:
        return None
    ordered = tuple(sorted(events, key=lambda event: event.at))
    start = ordered[0].at
    if now - start < window:
        return None
    return tuple(event for event in ordered if event.at - start <= window)


class HandoverToHuman:
    def __init__(self, cases: CaseFileRepository) -> None:
        self._cases = cases
        self.records: list[Handover] = []

    def execute(self, context: TenantContext | None, conversation_id: UUID, *, reason: str) -> Handover:
        if context is None:
            raise TenantRequired()
        case = self._cases.get(context.tenant_id, conversation_id)
        if case is None:
            from quotedesk.application.errors import CaseNotFound

            raise CaseNotFound()
        record = Handover(conversation_id=conversation_id, case=case, reason=reason)
        self.records.append(record)
        return record


class RunAgentTurn:
    def __init__(
        self,
        conversations: ConversationRepository,
        sender: ChannelSender,
        model: AgentModel,
        lock: ConversationLock,
        update_case,
        get_quote,
        handover: HandoverToHuman,
        clock: Clock,
        *,
        window: timedelta = timedelta(seconds=5),
        card_base: str | None = None,
        card_code: str | None = None,
    ) -> None:
        self._conversations = conversations
        self._sender = sender
        self._model = model
        self._lock = lock
        self._update_case = update_case
        self._get_quote = get_quote
        self._handover = handover
        self._clock = clock
        self._window = window
        self._card_base = card_base
        self._card_code = card_code
        self._closed: set[str] = set()

    def execute(self, context: TenantContext | None, conversation_id: UUID) -> None:
        if context is None:
            raise TenantRequired()
        if not self._lock.acquire(conversation_id):
            return
        try:
            conversation = self._conversations.get(context.tenant_id, conversation_id)
            if conversation is None:
                return
            pending = tuple(
                event for event in conversation.events if event.provider_message_id not in self._closed
            )
            batch = close_batch(pending, window=self._window, now=self._clock.now())
            if batch is None:
                return
            prompt = TurnPrompt(event_ids=tuple(event.provider_message_id for event in conversation.events))
            wa_id = _wa_id(self._conversations, context.tenant_id, conversation_id)
            if _unfinished_video(batch, self._conversations.messages(context.tenant_id, conversation_id)):
                self._sender.send(wa_id, _VIDEO)
                self._close(batch)
                return
            if _PHRASE in "\n".join(event.body for event in batch).casefold():
                self._handover.execute(context, conversation_id, reason=_PHRASE_REASON)
                self._sender.send(wa_id, _HANDOVER)
                self._close(batch)
                return
            reply = self._complete(prompt)
            if reply is None:
                self._handover.execute(context, conversation_id, reason=_TIMEOUT_REASON)
                self._sender.send(wa_id, _HANDOVER)
                self._close(batch)
                return
            facts, answered = self._run_tools(context, reply, prompt)
            text = reply.text
            if not check_reply(text, facts).ok:
                second = self._model.complete(answered)
                if second.text and check_reply(second.text, facts).ok:
                    text = second.text
                else:
                    text = _REFUSAL
            self._sender.send(wa_id, text)
            self._close(batch)
        finally:
            self._lock.release(conversation_id)

    def _complete(self, prompt: TurnPrompt) -> ModelReply | None:
        try:
            return self._model.complete(prompt)
        except ModelTimeout:
            try:
                return self._model.complete(prompt)
            except ModelTimeout:
                return None

    def _run_tools(self, context: TenantContext, reply: ModelReply, prompt: TurnPrompt) -> TurnFacts:
        amounts: list[Money] = []
        clauses: list = []
        price_kind = "fixed"
        card_link = None
        names: list[str] = []
        for call in reply.tool_calls:
            names.append(call.name)
            if call.name == "update_case":
                self._update_case.execute(context, UpdateCaseInput(**call.arguments))
            elif call.name == "get_quote":
                result = self._get_quote.execute(context, GetQuoteInput(**call.arguments))
                if result.total is not None:
                    amounts.append(result.total)
                clauses.extend(result.clauses)
                price_kind = result.price_type
                if self._card_base is not None:
                    card_link = f"{self._card_base}/{result.quote_id.value}"
                    if self._card_code:
                        card_link = f"{card_link}?code={self._card_code}"
        answered = prompt.model_copy(update={"tool_results": tuple(names)})
        return (
            TurnFacts(
                amounts=tuple(amounts),
                clauses=tuple(clauses),
                price_kind=price_kind if price_kind in ("fixed", "range", "none") else "fixed",
                card_link=card_link,
            ),
            answered,
        )

    def _close(self, batch: tuple[ConversationEvent, ...]) -> None:
        for event in batch:
            self._closed.add(event.provider_message_id)


def _wa_id(conversations: ConversationRepository, tenant_id, conversation_id: UUID) -> str:
    messages = conversations.messages(tenant_id, conversation_id)
    if not messages:
        return ""
    return messages[-1].wa_id


def _unfinished_video(batch: tuple[ConversationEvent, ...], messages) -> bool:
    kinds = {message.provider_message_id: message.kind for message in messages}
    return any(
        kinds.get(event.provider_message_id) == "video"
        and event.transcript_id is None
        and event.extraction_id is None
        for event in batch
    )
