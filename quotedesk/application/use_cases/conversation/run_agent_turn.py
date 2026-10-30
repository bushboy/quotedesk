import logging
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import NAMESPACE_OID, UUID, uuid5

_log = logging.getLogger(__name__)

from pydantic import ValidationError as ModelError

from quotedesk.application.dto.agent import (
    BusinessView,
    CaseView,
    Handover,
    HandoverNote,
    ModelReply,
    ExtractionResult,
    PromptExtraction,
    PromptFact,
    PromptMessage,
    PromptRateItem,
    ToolPayload,
    TurnPrompt,
)
from quotedesk.application.dto.tenant import TenantContext
from quotedesk.application.dto.tool_inputs import (
    AcceptQuoteInput,
    CheckAvailabilityInput,
    CreateDepositLinkInput,
    FactInput,
    GetQuoteInput,
    HoldSlotInput,
    RequestChangeInput,
    UpdateCaseInput,
)
from quotedesk.application.errors import CaseNotFound, ModelTimeout, QuoteNotFound, TenantRequired
from quotedesk.application.ports.agent import AgentModel, ConversationLock
from quotedesk.application.ports.gate import ChannelSender
from quotedesk.application.ports.repositories import CaseFileRepository, ConversationRepository
from quotedesk.application.ports.runtime import Clock
from quotedesk.domain.conversation.events import ConversationEvent
from quotedesk.domain.policy.rules import Outcome
from quotedesk.domain.services.commitments import TurnFacts, check_reply
from quotedesk.domain.services.confidence import (
    MediaUsability,
    SizeFact,
    SizeSource,
    cross_model_agreement,
    measurement_acceptable,
    media_is_usable,
    rate_card_match,
    required_fields_complete,
)
from quotedesk.domain.shared.errors import PolicyViolation, ValidationError
from quotedesk.domain.shared.money import Money

_REFUSAL = "I can only repeat what the quote says."


def _log_model_reply(model, reply: ModelReply) -> None:
    """Script replies are logged here. Spark logs its own text next to the call."""
    if type(model).__name__ == "SparkTurn":
        return
    tools = ", ".join(call.name for call in reply.tool_calls) or "none"
    _log.info("Handler %s response text=%s tools=%s", type(model).__name__, reply.text, tools)


AGENT_TASK = (
    "You are the owner, texting on WhatsApp. Read the conversation and answer what they just said.\n"
    "A hello gets a short polite reply. When a detail is missing, ask one question. Do not stay silent.\n"
    "When they have not chosen an item, offer the descriptions on the rate card and ask which one they want. Do not state a price.\n"
    "Lead the conversation to one outcome. Ask the one question that decides it.\n"
    "When the facts for a priced job are known, call get_quote in that same turn. Say the result from that call. "
    "Do not stop after only recording the conversation.\n"
    "If it cannot be quoted, call get_quote and use its customer_template.\n"
    "Record facts they stated with update_case. Use the latest message id as event_id and source customer_text.\n"
    "A new job on update_case sets job_type.\n"
    "Do not write required_fields, agreement, measurement, media_usable, rate_card, unit_price, outcome, or clause_text.\n"
    "Call get_quote when the case can be priced. When they ask how soon, call check_availability and answer with its turnaround. "
    "That is working days after the deposit, not a reserved day. "
    "When they accept or ask how to pay the deposit, call accept_quote and then create_deposit_link. Say the link.\n"
    "When they ask to book a day and a quote exists, call hold_slot with that quote id and the job type. Say its sentence.\n"
    "Call request_change when they ask to change a quote, using the quote id from an earlier payload.\n"
    "When the reply depends on a tool, return the tool calls and no text.\n"
    "When you can greet them or ask a question, return the text and no tool call.\n"
    "When tool_payloads is filled, write the reply from those payloads. Do not invent a second total.\n"
    "Use each extraction with the message it names.\n"
    "When the photo and the customer disagree, ask one question.\n"
    "A size that appears only in an extraction is not customer_stated.\n"
    "The business in the prompt is who you speak for. Use its name, and do not mention another business."
)
WATER_HINTS = (
    "This business installs and replaces water tanks.\n"
    "When they have not stated a tank size, offer the tank descriptions on the rate card and ask which one they want. Do not state a price.\n"
    "When the tank size is known and the job is a new installation or a swap, call get_quote in that same turn. "
    "Record size_litres and job as replacement or new_system. The result is an indicative range. Say range_min and range_max, and use the word range. "
    "Do not stop after only recording the conversation.\n"
    "A fixed quote still needs a simple replacement: size_litres, size_source customer_stated, existing_level_base true, job replacement, and item_codes for that size.\n"
    "If the installation is damaged and they have not confirmed a simple tank swap, record installation_damaged true and simple_swap false, then call get_quote. That books an inspection.\n"
    "If it cannot be quoted and it is not that inspection, call get_quote. Tell them their message is recorded for further consultation and they will be contacted.\n"
    "A tank replacement sets job_type to replacement."
)
FRAME_HINTS = (
    "This business builds carports and replaces sheeting.\n"
    "When they have not chosen a sheet, offer the descriptions on the rate card and ask which one they want. Do not state a price.\n"
    "When they give a size, record width_m and length_m in metres, and record the chosen sheet as item_codes.\n"
    "When the width and length are known, including from an earlier message, call get_quote in that same turn. "
    "The result is an indicative range. Say range_min and range_max, and use the word range.\n"
    "Do not reply that you will record the choice. If the size is still missing, ask for the width and length.\n"
    "A fixed quote still needs an existing opening, a stated size, a standard size, and a chosen finish.\n"
    "A new or widened opening, work above the ground floor, or more than one opening is a site measure. Use the customer_template.\n"
    "A carport job sets job_type to carport."
)


def _task(conversations, context: TenantContext, conversation, business: BusinessView) -> str:
    task = task_for(business)
    known = _known_name(conversations, context.tenant_id, conversation.conversation_id)
    if not known:
        return task
    return f"{task}\nThe customer's name is {known}. Use that name."


def task_for(business: BusinessView) -> str:
    trade = business.trade.casefold()
    if "water tank" in trade:
        return f"{AGENT_TASK}\n{WATER_HINTS}"
    if "carport" in trade or "sheeting" in trade:
        return f"{AGENT_TASK}\n{FRAME_HINTS}"
    return AGENT_TASK


NAME_ASK = "What name should I use for you?"
_NOT_A_NAME = frozenset(
    {
        "yes",
        "no",
        "ok",
        "okay",
        "thanks",
        "thank",
        "hi",
        "hello",
        "hey",
        "please",
        "sure",
        "accept",
        "quote",
        "the",
        "a",
        "i",
        "me",
        "you",
        "deposit",
        "pay",
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    }
)
_INTRODUCED = re.compile(
    r"(?i)\b(?:my name is|name is|call me)\s+"
    r"([A-Za-z][A-Za-z'’\-]*(?:\s+[A-Za-z][A-Za-z'’\-]*){0,3})"
)


def remember_name(conversations, tenant_id, conversation_id: UUID, wa_id: str, events) -> None:
    """Keep a name the customer stated, or a short reply after we asked."""
    rename = getattr(conversations, "rename", None)
    named = getattr(conversations, "name", None)
    if rename is None or named is None or not wa_id or named(tenant_id, wa_id):
        return
    text = "\n".join(getattr(event, "body", "") or "" for event in events).strip()
    found = _introduced_name(text)
    if found is None and _asked_for_name(conversations, tenant_id, conversation_id):
        found = _bare_name(text)
    if found:
        rename(tenant_id, wa_id, found)


def with_name(conversations, tenant_id, wa_id: str, text: str) -> str:
    """Ask once we still do not know who the number belongs to."""
    named = getattr(conversations, "name", None)
    if named is None or not wa_id or named(tenant_id, wa_id) or NAME_ASK in text:
        return text
    return f"{text.rstrip()} {NAME_ASK}".strip()


def _introduced_name(text: str) -> str | None:
    found = _INTRODUCED.search(text)
    if found is None:
        return None
    return _bare_name(found.group(1))


def _bare_name(text: str) -> str | None:
    words = text.strip().split()
    if not 1 <= len(words) <= 4 or len(text.strip()) > 40:
        return None
    if any(not re.fullmatch(r"[A-Za-z][A-Za-z'’\-]*", word) for word in words):
        return None
    if any(word.casefold() in _NOT_A_NAME for word in words):
        return None
    if len(words[0]) < 2:
        return None
    return " ".join(words)


def _asked_for_name(conversations, tenant_id, conversation_id: UUID) -> bool:
    replies = getattr(conversations, "replies", None)
    if replies is None:
        return False
    rows = replies(tenant_id, conversation_id)
    return bool(rows) and NAME_ASK in rows[-1][1]


def _known_name(conversations, tenant_id, conversation_id: UUID) -> str | None:
    named = getattr(conversations, "name", None)
    if named is None:
        return None
    wa_id = _wa_id(conversations, tenant_id, conversation_id)
    if not wa_id:
        return None
    return named(tenant_id, wa_id)


_VIDEO = "Got your video, having a look."
_HANDOVER = "I'll ask someone from the business to pick this up. You can keep sending details here."
_PHRASE = "can i speak to a person?"
_PHRASE_REASON = "Can I speak to a person?"
_TIMEOUT_REASON = "model timeout"
_UNAVAILABLE = "That tool is not available."
_DROPPED = frozenset({"required_fields", "agreement", "measurement", "media_usable", "rate_card"})
_THRESHOLD = Decimal("0.80")
_SOURCES = frozenset({"customer_stated", "reference_object", "photo_inferred"})


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
    def __init__(self, cases: CaseFileRepository, handovers=None, clock: Clock | None = None) -> None:
        self._cases = cases
        self._handovers = handovers
        self._clock = clock
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
        if self._handovers is not None:
            brief = ", ".join(job.job_type or job.job_id for job in case.jobs) or reason
            at = self._clock.now() if self._clock is not None else datetime.now(timezone.utc)
            self._handovers.append(
                context.tenant_id,
                HandoverNote(conversation_id=conversation_id, reason=reason, brief=brief, at=at),
            )
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
        request_change=None,
        check_availability=None,
        accept_quote=None,
        create_deposit_link=None,
        hold_slot=None,
        catalog=None,
        policies=None,
        ids=None,
        window: timedelta = timedelta(seconds=5),
        card_base: str | None = None,
        card_code: str | None = None,
        enricher=None,
        business: BusinessView | None = None,
    ) -> None:
        self._conversations = conversations
        self._sender = sender
        self._model = model
        self._lock = lock
        self._update_case = update_case
        self._get_quote = get_quote
        self._handover = handover
        self._clock = clock
        self._request_change = request_change
        self._check_availability = check_availability
        self._accept_quote = accept_quote
        self._create_deposit_link = create_deposit_link
        self._hold_slot = hold_slot
        self._catalog = catalog
        self._policies = policies
        self._ids = ids
        self._window = window
        self._card_base = card_base
        self._card_code = card_code
        self.enricher = enricher
        self._closed: set[str] = set()
        self._change_key: str | None = None
        self._seen: dict[str, ExtractionResult] = {}
        self._business = business or BusinessView()

    def acknowledge(self, provider_message_ids) -> None:
        """Messages already stored before this process started are not answered again."""
        self._closed.update(provider_message_ids)

    def execute(self, context: TenantContext | None, conversation_id: UUID) -> None:
        if context is None:
            raise TenantRequired()
        if not self._lock.acquire(conversation_id):
            return
        try:
            self._change_key = None
            conversation = self._conversations.get(context.tenant_id, conversation_id)
            if conversation is None:
                return
            pending = tuple(
                event for event in conversation.events if event.provider_message_id not in self._closed
            )
            batch = close_batch(pending, window=self._window, now=self._clock.now())
            if batch is None:
                return
            wa_id = _wa_id(self._conversations, context.tenant_id, conversation_id)
            remember_name(self._conversations, context.tenant_id, conversation_id, wa_id, batch)
            prompt = self._prompt(context, conversation)
            if _unfinished_video(batch, self._conversations.messages(context.tenant_id, conversation_id)):
                _log.info("Turn handled by video acknowledgement")
                self._speak(context, conversation_id, wa_id, _VIDEO)
                self._close(batch)
                return
            if _PHRASE in "\n".join(event.body for event in batch).casefold():
                _log.info("Turn handled by handover")
                self._handover.execute(context, conversation_id, reason=_PHRASE_REASON)
                self._speak(context, conversation_id, wa_id, _HANDOVER)
                self._close(batch)
                return
            _log.info("Turn handled by %s", type(self._model).__name__)
            reply = self._complete(prompt)
            if reply is None:
                self._handover.execute(context, conversation_id, reason=_TIMEOUT_REASON)
                self._speak(context, conversation_id, wa_id, _HANDOVER)
                self._close(batch)
                return
            if not reply.tool_calls and not reply.text.strip():
                _log.info("Turn produced no front-end reply")
                self._close(batch)
                return
            facts, answered = self._run_tools(context, reply, prompt, batch, conversation_id)
            text = reply.text
            needs_follow_up = bool(reply.tool_calls) and (not text.strip() or _payload_failed(answered))
            if needs_follow_up:
                spoken = self._complete(answered)
                if spoken is None:
                    self._handover.execute(context, conversation_id, reason=_TIMEOUT_REASON)
                    self._speak(context, conversation_id, wa_id, _HANDOVER)
                    self._close(batch)
                    return
                if spoken.tool_calls and _payload_failed(answered):
                    facts, answered = self._run_tools(context, spoken, answered, batch, conversation_id)
                text = spoken.text
                if not text.strip():
                    if not spoken.tool_calls:
                        _log.info("Turn produced no front-end reply")
                        self._close(batch)
                        return
                    follow = self._complete(answered)
                    if follow is None:
                        self._handover.execute(context, conversation_id, reason=_TIMEOUT_REASON)
                        self._speak(context, conversation_id, wa_id, _HANDOVER)
                        self._close(batch)
                        return
                    if not follow.text.strip():
                        _log.info("Turn produced no front-end reply")
                        self._close(batch)
                        return
                    text = follow.text
            elif reply.text.strip():
                heard = _availability_sentence(answered) or _named_sentence(answered, "hold_slot")
                if heard and heard not in text:
                    text = heard
            deposit_url = _named_sentence(answered, "create_deposit_link")
            if deposit_url and deposit_url not in text:
                text = f"{text.rstrip()} {deposit_url}".strip()
            priced = _indicative_reply(answered)
            if priced and not _states_indicative(text, priced):
                text = priced
            elif _fabrication(self._business) and "?" not in text:
                question = _carport_question(answered)
                heard = _customer_template(answered)
                if question:
                    text = question
                elif heard and _recording(text):
                    text = heard
            text = _with_card(text, facts.card_link)
            if reply.tool_calls and not check_reply(text, facts).ok:
                second = self._model.complete(answered)
                _log_model_reply(self._model, second)
                if second.text and check_reply(second.text, facts).ok:
                    text = second.text
                else:
                    _log.info("Checked reply replaced the model text")
                    text = _REFUSAL
            self._speak(context, conversation_id, wa_id, text)
            self._close(batch)
        finally:
            self._lock.release(conversation_id)

    def _complete(self, prompt: TurnPrompt) -> ModelReply | None:
        try:
            reply = self._model.complete(prompt)
        except ModelTimeout:
            try:
                reply = self._model.complete(prompt)
            except ModelTimeout:
                _log.warning("Model %s timed out", type(self._model).__name__)
                return None
        _log_model_reply(self._model, reply)
        return reply

    def _prompt(self, context: TenantContext, conversation) -> TurnPrompt:
        ordered = conversation.events
        kinds = {
            message.provider_message_id: message.kind
            for message in self._conversations.messages(context.tenant_id, conversation.conversation_id)
        }
        messages = self._trail(context, conversation, kinds)
        return TurnPrompt(
            event_ids=tuple(event.provider_message_id for event in ordered),
            messages=messages,
            case=self._case_view(context, conversation.conversation_id),
            rate_card=self._rate_card(context),
            extractions=self._extractions(context, conversation.conversation_id, ordered[-20:], kinds),
            business=self._business,
            task=_task(self._conversations, context, conversation, self._business),
        )

    def _trail(self, context: TenantContext, conversation, kinds: dict[str, str]) -> tuple[PromptMessage, ...]:
        rows: list[tuple[datetime, int, PromptMessage]] = []
        for event in conversation.events:
            rows.append(
                (
                    event.at,
                    0,
                    PromptMessage(
                        provider_message_id=event.provider_message_id,
                        kind=kinds.get(event.provider_message_id, "text"),
                        body=event.body,
                        role="customer",
                    ),
                )
            )
        replies = getattr(self._conversations, "replies", None)
        if replies is not None:
            for index, (at, body) in enumerate(replies(context.tenant_id, conversation.conversation_id)):
                rows.append(
                    (
                        at,
                        1,
                        PromptMessage(
                            provider_message_id=f"reply-{index}",
                            kind="text",
                            body=body,
                            role="assistant",
                        ),
                    )
                )
        rows.sort(key=lambda item: (item[0], item[1]))
        return tuple(item[2] for item in rows[-20:])

    def _speak(self, context: TenantContext, conversation_id: UUID, wa_id: str, body: str) -> None:
        body = with_name(self._conversations, context.tenant_id, wa_id, body)
        buttons = ("Accept quote",) if "/card/" in body and "deposit/" not in body else ()
        image_url = None
        try:
            self._sender.send(wa_id, body, buttons=buttons, image_url=image_url)
        except TypeError:
            self._sender.send(wa_id, body)
        record = getattr(self._conversations, "record_reply", None)
        if record is not None:
            record(context.tenant_id, conversation_id, self._clock.now(), body)

    def _case_view(self, context: TenantContext, conversation_id: UUID) -> CaseView:
        case = self._handover._cases.get(context.tenant_id, conversation_id)
        if case is None:
            return CaseView()
        facts = tuple(
            PromptFact(
                job_id=job.job_id,
                key=fact.key,
                value=fact.value,
                source=fact.source,
                event_id=fact.event_id,
            )
            for job in case.jobs
            for fact in job.facts
            if fact.superseded_by is None and not fact.contested
        )
        missing: tuple[str, ...] = ()
        if self._catalog is not None and case.jobs:
            job = case.jobs[0]
            current = {fact.key for fact in facts if fact.job_id == job.job_id}
            required = self._catalog.required(job.job_type or "")
            missing = tuple(name for name in required if name not in current)
        return CaseView(
            facts=facts,
            missing_required=missing,
            contradiction_count=len(case.contradictions),
        )

    def _extractions(
        self,
        context: TenantContext,
        conversation_id: UUID,
        events: tuple[ConversationEvent, ...],
        kinds: dict[str, str],
    ) -> tuple[PromptExtraction, ...]:
        rows: list[PromptExtraction] = []
        for event in events:
            if kinds.get(event.provider_message_id) != "image":
                continue
            result = self._read_image(context, conversation_id, event)
            if result is None:
                continue
            rows.append(
                PromptExtraction(
                    provider_message_id=event.provider_message_id,
                    summary=result.summary,
                    objects=result.objects,
                )
            )
        return tuple(rows)

    def _read_image(
        self,
        context: TenantContext,
        conversation_id: UUID,
        event: ConversationEvent,
    ) -> ExtractionResult | None:
        cached = self._seen.get(event.provider_message_id)
        if cached is not None:
            return cached
        if self.enricher is None:
            return None
        result = self.enricher.for_image(event.provider_message_id)
        if result is None:
            return None
        self._seen[event.provider_message_id] = result
        if event.extraction_id is None:
            conversation = self._conversations.get(context.tenant_id, conversation_id)
            if conversation is not None:
                self._conversations.save(
                    context.tenant_id,
                    conversation.attach(event.provider_message_id, extraction_id=event.provider_message_id),
                )
        return result

    def _rate_card(self, context: TenantContext) -> tuple[PromptRateItem, ...]:
        if self._policies is None:
            return ()
        bundle = self._policies.published(context.tenant_id)
        if bundle is None:
            return ()
        return tuple(
            PromptRateItem(item_code=item.item_code, description=item.description)
            for item in bundle.rate_card.items
        )

    def _run_tools(
        self,
        context: TenantContext,
        reply: ModelReply,
        prompt: TurnPrompt,
        batch: tuple[ConversationEvent, ...],
        conversation_id: UUID,
    ) -> tuple[TurnFacts, TurnPrompt]:
        amounts: list[Money] = []
        clauses: list = []
        civil_dates = []
        price_kind = "fixed"
        schedule_status = "none"
        card_link = None
        names: list[str] = []
        payloads: list[ToolPayload] = []
        for call in reply.tool_calls:
            names.append(call.name)
            arguments = _on_conversation(call.name, call.arguments, conversation_id)
            if call.name == "update_case":
                payloads.append(self._update(context, _with_message_ids(arguments, batch)))
            elif call.name == "get_quote":
                payloads.append(self._quote(context, arguments, batch, amounts, clauses))
                price_kind, card_link = _quote_facts(payloads[-1], self._card_base, self._card_code, price_kind, card_link)
                self._handover_escalation(context, conversation_id, payloads[-1])
            elif call.name == "request_change":
                payloads.append(self._change(context, call.arguments, amounts, clauses))
            elif call.name == "check_availability":
                payloads.append(self._availability(context, call.arguments, civil_dates))
                if payloads[-1].body.get("earliest_window"):
                    schedule_status = "indicative"
            elif call.name == "accept_quote":
                payloads.append(self._accept(context, call.arguments))
            elif call.name == "create_deposit_link":
                payloads.append(self._deposit_link(context, call.arguments))
            elif call.name == "hold_slot":
                payloads.append(self._hold(context, call.arguments))
            else:
                payloads.append(_refused(call.name))
            _log_tool(payloads[-1])
        if "get_quote" not in names and "check_availability" not in names and self._should_quote(reply, payloads):
            payloads.append(
                self._quote(context, {"conversation_id": str(conversation_id)}, batch, amounts, clauses)
            )
            names.append("get_quote")
            price_kind, card_link = _quote_facts(
                payloads[-1], self._card_base, self._card_code, price_kind, card_link
            )
            self._handover_escalation(context, conversation_id, payloads[-1])
            _log_tool(payloads[-1])
        answered = prompt.model_copy(
            update={"tool_results": tuple(names), "tool_payloads": tuple(payloads)}
        )
        return (
            TurnFacts(
                amounts=tuple(amounts),
                civil_dates=tuple(civil_dates),
                clauses=tuple(clauses),
                schedule_status=schedule_status,
                price_kind=price_kind if price_kind in ("fixed", "range", "none") else "fixed",
                card_link=card_link,
            ),
            answered,
        )

    def _should_quote(self, reply: ModelReply, payloads: list[ToolPayload]) -> bool:
        if _recorded_sized_install(reply, payloads):
            return True
        return _fabrication(self._business) and _carport_measured(payloads)

    def _update(self, context: TenantContext, arguments: dict) -> ToolPayload:
        try:
            data = UpdateCaseInput(**_without_confidence(arguments))
        except (ModelError, ValidationError) as error:
            detail = _invalid(error)
            _log.info("Tool update_case rejected %s", detail)
            return ToolPayload(name="update_case", body={"error": detail})
        _log.info(
            "Tool update_case request job_id=%s job_type=%s facts=%s",
            data.job_id,
            data.job_type or "none",
            ",".join(fact.key for fact in data.facts) or "none",
        )
        try:
            result = self._update_case.execute(context, data)
        except (CaseNotFound, ValidationError) as error:
            return ToolPayload(name="update_case", body={"error": error.sentence})
        return ToolPayload(name="update_case", body=_body(result))

    def _quote(self, context, arguments: dict, batch, amounts: list, clauses: list) -> ToolPayload:
        try:
            data = GetQuoteInput(**arguments)
        except (ModelError, ValidationError):
            return _refused("get_quote")
        self._write_confidence(context, data.conversation_id, batch)
        try:
            result = self._get_quote.execute(context, data)
        except CaseNotFound as error:
            return ToolPayload(name="get_quote", body={"error": error.sentence})
        if result.total is not None:
            amounts.append(result.total)
        low = getattr(result, "range_min", None)
        high = getattr(result, "range_max", None)
        if low is not None:
            amounts.append(low)
        if high is not None and high != low:
            amounts.append(high)
        clauses.extend(result.clauses)
        return ToolPayload(name="get_quote", body=_body(result))

    def _change(self, context, arguments: dict, amounts: list, clauses: list) -> ToolPayload:
        if self._request_change is None or not str(arguments.get("quote_id") or "").strip():
            return _refused("request_change")
        try:
            data = RequestChangeInput(**self._with_key(arguments))
        except (ModelError, ValidationError):
            return _refused("request_change")
        result = self._request_change.execute(context, data)
        for line in result.lines:
            amounts.append(line.total)
        clauses.extend(result.clauses)
        return ToolPayload(name="request_change", body=_body(result))

    def _availability(self, context, arguments: dict, civil_dates: list) -> ToolPayload:
        if self._check_availability is None:
            return _refused("check_availability")
        try:
            data = CheckAvailabilityInput(**arguments)
        except (ModelError, ValidationError):
            return _refused("check_availability")
        try:
            result = self._check_availability.execute(context, data)
        except (PolicyViolation, ValidationError) as error:
            _log.info("Tool check_availability failed %s", error.sentence)
            return ToolPayload(
                name="check_availability",
                body={"status": "none", "sentence": error.sentence},
            )
        if result.earliest_window is not None:
            civil_dates.append(result.earliest_window)
        return ToolPayload(name="check_availability", body=_body(result))

    def _accept(self, context, arguments: dict) -> ToolPayload:
        if self._accept_quote is None:
            return _refused("accept_quote")
        try:
            data = AcceptQuoteInput(**_quote_arg(arguments))
        except (ModelError, ValidationError):
            return _refused("accept_quote")
        try:
            result = self._accept_quote.execute(context, data)
        except (PolicyViolation, ValidationError, QuoteNotFound) as error:
            return ToolPayload(name="accept_quote", body={"error": error.sentence})
        return ToolPayload(name="accept_quote", body=_body(result))

    def _deposit_link(self, context, arguments: dict) -> ToolPayload:
        if self._create_deposit_link is None:
            return _refused("create_deposit_link")
        try:
            data = CreateDepositLinkInput(**self._with_key(_quote_arg(arguments)))
        except (ModelError, ValidationError):
            return _refused("create_deposit_link")
        try:
            result = self._create_deposit_link.execute(context, data)
        except (PolicyViolation, ValidationError, QuoteNotFound) as error:
            return ToolPayload(name="create_deposit_link", body={"error": error.sentence, "sentence": error.sentence})
        return ToolPayload(name="create_deposit_link", body=_body(result))

    def _hold(self, context, arguments: dict) -> ToolPayload:
        if self._hold_slot is None:
            return _refused("hold_slot")
        try:
            data = HoldSlotInput(**self._with_key(_quote_arg(arguments)))
        except (ModelError, ValidationError):
            return _refused("hold_slot")
        try:
            result = self._hold_slot.execute(context, data)
        except (PolicyViolation, ValidationError) as error:
            return ToolPayload(name="hold_slot", body={"error": error.sentence, "sentence": error.sentence})
        body = _body(result)
        body["sentence"] = "That window is held until the deposit hold expires."
        return ToolPayload(name="hold_slot", body=body)

    def _handover_escalation(self, context, conversation_id: UUID, payload: ToolPayload) -> None:
        outcome = payload.body.get("outcome")
        if outcome in (Outcome.ESCALATION, "escalation"):
            self._handover.execute(context, conversation_id, reason="The quote needs a person.")

    def _with_key(self, arguments: dict) -> dict:
        raw = dict(arguments)
        if isinstance(raw.get("quote_id"), str):
            raw["quote_id"] = {"value": raw["quote_id"]}
        if raw.get("idempotency_key"):
            return raw
        if self._ids is None:
            return raw
        if self._change_key is None:
            self._change_key = self._ids.next_idempotency_key()
        raw["idempotency_key"] = self._change_key
        return raw

    def _write_confidence(
        self,
        context: TenantContext,
        conversation_id: UUID,
        batch: tuple[ConversationEvent, ...],
    ) -> None:
        if self._catalog is None or self._policies is None or not batch:
            return
        bundle = self._policies.published(context.tenant_id)
        case = self._handover._cases.get(context.tenant_id, conversation_id)
        if bundle is None or case is None or not case.jobs:
            return
        job = case.jobs[0]
        current = {
            fact.key: fact.value
            for fact in case.facts(job.job_id)
            if fact.superseded_by is None and not fact.contested
        }
        kinds = {
            message.provider_message_id: message.kind
            for message in self._conversations.messages(context.tenant_id, conversation_id)
        }
        stored = self._conversations.get(context.tenant_id, conversation_id)
        recent = stored.events[-20:] if stored is not None else ()
        has_image, has_video, objects, sam_error, masks, usability = _evidence(
            self, context, conversation_id, recent, kinds
        )
        sizes = _sizes(current)
        flags = {
            "required_fields": required_fields_complete(current, self._catalog.required(job.job_type or "")),
            "agreement": cross_model_agreement(
                has_image=has_image,
                has_video=has_video,
                spark_objects=objects,
                sam_error=sam_error,
                masks=masks,
                threshold=_THRESHOLD,
            ),
            "measurement": False if sizes is None else measurement_acceptable(sizes),
            "media_usable": media_is_usable(usability),
            "rate_card": rate_card_match(_item_codes(current.get("item_codes")), set(bundle.policy.rate_card_codes)),
        }
        self._update_case.execute(
            context,
            UpdateCaseInput(
                conversation_id=conversation_id,
                job_id=job.job_id,
                facts=tuple(
                    FactInput(
                        key=key,
                        value="true" if flag else "false",
                        source="customer_text",
                        event_id=_event_uuid(batch[-1].provider_message_id),
                    )
                    for key, flag in flags.items()
                ),
            ),
        )

    def _close(self, batch: tuple[ConversationEvent, ...]) -> None:
        for event in batch:
            self._closed.add(event.provider_message_id)


def _evidence(turn: RunAgentTurn, context: TenantContext, conversation_id: UUID, events, kinds: dict[str, str]):
    has_image = any(kinds.get(event.provider_message_id) == "image" for event in events)
    has_video = any(kinds.get(event.provider_message_id) == "video" for event in events)
    empty = MediaUsability(has_media=False)
    if turn.enricher is None or not has_image:
        return has_image, has_video, (), False, (), empty
    found: list[ExtractionResult | None] = [
        turn._read_image(context, conversation_id, event)
        for event in events
        if kinds.get(event.provider_message_id) == "image"
    ]
    usable = MediaUsability(has_media=True)
    if not found or any(item is None for item in found):
        return has_image, has_video, (), False, (), usable
    present = [item for item in found if item is not None]
    objects = tuple(name for item in present for name in item.objects)
    masks = tuple(mask for item in present for mask in item.masks)
    return (
        has_image,
        has_video,
        objects,
        any(item.sam_error for item in present),
        masks,
        MediaUsability(
            has_media=True,
            blur=any(item.blur for item in present),
            darkness=any(item.darkness for item in present),
            wrong_subject=any(item.wrong_subject for item in present),
        ),
    )


def _quote_facts(payload, card_base, card_code, price_kind, card_link):
    if payload.body.get("error"):
        return price_kind, card_link
    outcome = payload.body.get("outcome")
    if outcome == Outcome.INDICATIVE_RANGE or outcome == "indicative_range":
        price_kind = "range"
    elif outcome in (Outcome.SITE_ASSESSMENT, Outcome.ESCALATION, "site_assessment", "escalation"):
        price_kind = "none"
    elif outcome in (Outcome.FIXED_OFFER, "fixed_offer"):
        price_kind = "fixed"
    else:
        kind = payload.body.get("price_type", price_kind)
        price_kind = kind if kind in ("fixed", "range", "none") else "fixed"
    quote_id = payload.body.get("quote_id")
    if (
        card_base is not None
        and price_kind in ("fixed", "range")
        and isinstance(quote_id, dict)
        and quote_id.get("value")
    ):
        card_link = f"{card_base}/{quote_id['value']}"
        code = payload.body.get("verification_code") or card_code
        if code:
            card_link = f"{card_link}?code={code}"
    return price_kind, card_link


def _with_card(text: str, card_link: str | None) -> str:
    if not card_link or card_link in text:
        return text
    replaced = re.sub(r"/card/QD-\d+(?:\?code=[^ \n]+)?", card_link, text)
    if card_link in replaced:
        return replaced
    return f"{text.rstrip()} {card_link}"


def _quote_arg(arguments: dict) -> dict:
    raw = dict(arguments)
    if isinstance(raw.get("quote_id"), str):
        raw["quote_id"] = {"value": raw["quote_id"]}
    return raw


def _named_sentence(prompt: TurnPrompt, name: str) -> str | None:
    for item in prompt.tool_payloads:
        if item.name != name:
            continue
        sentence = item.body.get("url") if name == "create_deposit_link" else item.body.get("sentence")
        if isinstance(sentence, str) and sentence.strip():
            return sentence
    return None


def _log_tool(payload: ToolPayload) -> None:
    _log.info("Tool %s outcome %s", payload.name, _tool_outcome(payload))


def _tool_outcome(payload: ToolPayload) -> str:
    body = payload.body
    if body.get("error"):
        return f"error={body['error']}"
    if payload.name == "update_case":
        missing = body.get("missing_required") or ()
        return (
            f"job={body.get('job_id')} created={body.get('created')} "
            f"current={body.get('current')} "
            f"missing={', '.join(missing) if missing else 'none'} "
            f"contradictions={body.get('contradiction_count')}"
        )
    if payload.name == "get_quote":
        total = body.get("total")
        amount = total.get("amount") if isinstance(total, dict) else None
        rule = body.get("rule_id")
        rule_id = rule.get("value") if isinstance(rule, dict) else rule
        return f"outcome={body.get('outcome')} rule={rule_id} total={amount or 'none'}"
    if payload.name == "request_change":
        return f"state={body.get('state')} discount={body.get('discount_percent')}"
    if payload.name == "check_availability":
        return f"status={body.get('status')} earliest={body.get('earliest_window')} sentence={body.get('sentence')}"
    return str(body)


_SPAN = re.compile(r"(\d+(?:\.\d+)?)\s*(?:x|×|by)\s*(\d+(?:\.\d+)?)", re.IGNORECASE)
_SIZE_QUESTION = "What is the width and length in metres?"


def _fabrication(business: BusinessView) -> bool:
    trade = business.trade.casefold()
    return "carport" in trade or "sheeting" in trade


def _case_values(payloads: list[ToolPayload]) -> dict | None:
    for item in payloads:
        if item.name != "update_case" or item.body.get("error"):
            continue
        current = item.body.get("current")
        if isinstance(current, dict):
            return current
    return None


def _has_span(values: dict) -> bool:
    if values.get("width_m") and values.get("length_m"):
        return True
    raw = values.get("size") or values.get("dimensions") or ""
    return _SPAN.search(str(raw)) is not None


def _has_sheet(values: dict) -> bool:
    return bool(values.get("item") or values.get("item_codes") or values.get("finish"))


def _carport_measured(payloads: list[ToolPayload]) -> bool:
    values = _case_values(payloads)
    return values is not None and _has_span(values)


def _carport_question(prompt: TurnPrompt) -> str | None:
    values = _case_values(list(prompt.tool_payloads))
    if values is None or _has_span(values) or not _has_sheet(values):
        return None
    return _SIZE_QUESTION


def _customer_template(prompt: TurnPrompt) -> str | None:
    for item in prompt.tool_payloads:
        if item.name == "get_quote":
            template = item.body.get("customer_template")
            if isinstance(template, str) and template.strip():
                return template
    return None


def _recording(text: str) -> bool:
    folded = text.casefold()
    return folded.startswith("i'll record") or folded.startswith("i will record")


_INSTALL_JOBS = frozenset(
    {
        "replacement",
        "swap",
        "tank_swap",
        "new_system",
        "new",
        "installation",
        "new_installation",
        "new_install",
    }
)


def _recorded_sized_install(reply: ModelReply, payloads: list[ToolPayload]) -> bool:
    updates = [call for call in reply.tool_calls if call.name == "update_case"]
    recorded = [item for item in payloads if item.name == "update_case"]
    for call, payload in zip(updates, recorded):
        if payload.body.get("error"):
            continue
        facts = call.arguments.get("facts") or []
        values = {
            fact.get("key"): fact.get("value")
            for fact in facts
            if isinstance(fact, dict)
        }
        if str(values.get("simple_swap", "")).casefold() == "false":
            continue
        job = values.get("job") or values.get("job_type") or call.arguments.get("job_type")
        size = values.get("size_litres") or values.get("tank_size")
        folded = str(job or "").casefold().replace("-", "_").replace(" ", "_")
        if size and folded in _INSTALL_JOBS:
            return True
    return False


def _indicative_reply(prompt: TurnPrompt) -> str | None:
    for item in prompt.tool_payloads:
        if item.name != "get_quote" or item.body.get("outcome") != "indicative_range":
            continue
        low = _amount(item.body.get("range_min"))
        high = _amount(item.body.get("range_max"))
        if low is None or high is None:
            return None
        if low == high:
            return f"The indicative range is R {low}."
        return f"The indicative range is R {low} to R {high}."
    return None


def _states_indicative(text: str, priced: str) -> bool:
    if "range" not in text.casefold():
        return False
    amounts = [token.rstrip(".") for token in priced.split() if token.startswith("R")]
    return all(amount in text for amount in amounts)


def _amount(raw) -> str | None:
    if isinstance(raw, dict) and raw.get("amount"):
        return str(raw["amount"])
    return None


def _availability_sentence(prompt: TurnPrompt) -> str | None:
    for item in prompt.tool_payloads:
        if item.name != "check_availability":
            continue
        sentence = item.body.get("sentence")
        if isinstance(sentence, str) and sentence.strip():
            return sentence
    return None


def _payload_failed(prompt: TurnPrompt) -> bool:
    return any(bool(item.body.get("error")) for item in prompt.tool_payloads)


def _refused(name: str) -> ToolPayload:
    return ToolPayload(name=name, body={"error": _UNAVAILABLE})


def _body(result) -> dict:
    dump = getattr(result, "model_dump", None)
    if dump is None:
        return {}
    return dump(mode="json")


def _without_confidence(arguments: dict) -> dict:
    facts = arguments.get("facts")
    if not isinstance(facts, (list, tuple)):
        return arguments
    kept = [
        fact
        for fact in facts
        if not (isinstance(fact, dict) and fact.get("key") in _DROPPED)
    ]
    copied = dict(arguments)
    copied["facts"] = kept
    return copied


def _sizes(current: dict[str, str]) -> tuple[SizeFact, ...] | None:
    raw = current.get("size_litres")
    if raw is None or raw.strip() == "":
        return ()
    try:
        litres = int(raw)
    except ValueError:
        return None
    source = current.get("size_source")
    if source in _SOURCES:
        return (SizeFact(litres=litres, source=SizeSource(source)),)
    return ()


def _item_codes(raw: str | None) -> tuple[str, ...]:
    if raw is None or raw.strip() == "":
        return ()
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def _with_message_ids(arguments: dict, batch: tuple[ConversationEvent, ...]) -> dict:
    """A WhatsApp id such as wamid.SIM… is the event the prompt tells the model to send.

    Fact records store a UUID. The same mapping the turn uses for its own facts
    keeps that id attached to the message.
    """
    facts = arguments.get("facts")
    if not isinstance(facts, (list, tuple)):
        return arguments
    fallback = str(_event_uuid(batch[-1].provider_message_id)) if batch else ""
    prepared = []
    for fact in facts:
        if not isinstance(fact, dict):
            prepared.append(fact)
            continue
        item = dict(fact)
        raw = item.get("event_id")
        if raw is None or str(raw).strip() == "":
            if fallback:
                item["event_id"] = fallback
        else:
            item["event_id"] = str(_event_uuid(str(raw)))
        prepared.append(item)
    copied = dict(arguments)
    copied["facts"] = prepared
    return copied


def _invalid(error: Exception) -> str:
    errors = getattr(error, "errors", None)
    if not callable(errors):
        return getattr(error, "sentence", str(error))
    parts = []
    for item in errors()[:3]:
        loc = ".".join(str(part) for part in item.get("loc", ()))
        parts.append(f"{loc}: {item.get('msg')}")
    return "; ".join(parts) or "That call did not match the tool."


def _event_uuid(provider_message_id: str) -> UUID:
    try:
        return UUID(provider_message_id)
    except ValueError:
        return uuid5(NAMESPACE_OID, provider_message_id)


def _on_conversation(name: str, arguments: dict, conversation_id: UUID) -> dict:
    if name not in ("update_case", "get_quote"):
        return arguments
    bound = dict(arguments)
    bound["conversation_id"] = conversation_id
    return bound


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
