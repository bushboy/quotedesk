import json
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
    ExtractionResult,
    Handover,
    HandoverNote,
    ModelReply,
    PromptExtraction,
    PromptFact,
    PromptMessage,
    PromptRateItem,
    ToolPayload,
    TurnOutcome,
    TurnPrompt,
)
from quotedesk.application.dto.tenant import TenantContext
from quotedesk.application.dto.tool_inputs import (
    AcceptQuoteInput,
    BookInspectionInput,
    CheckAvailabilityInput,
    CreateDepositLinkInput,
    EscalateToOwnerInput,
    FactInput,
    GetQuoteInput,
    HoldSlotInput,
    RequestChangeInput,
    UpdateCaseInput,
)
from quotedesk.application.errors import CaseNotFound, ModelTimeout, QuoteNotFound, TenantRequired, ToolArgumentsInvalid
from quotedesk.application.prompts import PLATFORM_TASK as AGENT_TASK
from quotedesk.application.prompts import render_task
from quotedesk.application.ports.agent import AgentModel, ConversationLock
from quotedesk.application.ports.gate import ChannelSender
from quotedesk.application.ports.repositories import CaseFileRepository, ConversationRepository
from quotedesk.application.ports.runtime import Clock
from quotedesk.domain.case.case_file import CaseFile
from quotedesk.domain.conversation.events import ConversationEvent
from quotedesk.domain.policy.playbook import BusinessPlaybook
from quotedesk.domain.policy.rules import Outcome, Policy
from quotedesk.domain.services.plan import NextStep, StepKind, plan_next_step
from quotedesk.domain.shared.ids import PolicyVersionId
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


def _task(conversations, context: TenantContext, conversation, policies) -> str:
    book = None
    if policies is not None:
        published = policies.published(context.tenant_id)
        if published is not None and published.playbook.populated():
            book = published.playbook
    known = _known_name(conversations, context.tenant_id, conversation.conversation_id)
    return render_task(book, known or None)


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
        if found and _already_said(conversations, tenant_id, conversation_id, found):
            found = None
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


def _already_said(conversations, tenant_id, conversation_id: UUID, name: str) -> bool:
    """A one-word answer that repeats the last reply is a choice, not a name."""
    replies = getattr(conversations, "replies", None)
    if replies is None:
        return False
    rows = replies(tenant_id, conversation_id)
    if not rows:
        return False
    return re.search(rf"(?i)\b{re.escape(name)}\b", rows[-1][1]) is not None


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
_ACK = "Thanks, I've added that for the team."
_NUDGE = "Answer the customer in one sentence."
_CALLS = 4
_PHRASE = "can i speak to a person?"
_PHRASE_REASON = "Can I speak to a person?"
_TIMEOUT_REASON = "model timeout"
_UNAVAILABLE = "That tool is not available."
_BLOCKED_WHILE_HELD = frozenset({"get_quote", "request_change", "hold_slot", "create_deposit_link"})
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


def _classify(text: str, answered: TurnPrompt) -> TurnOutcome:
    for payload in answered.tool_payloads:
        if payload.name == "escalate_to_owner" and not payload.body.get("error"):
            return TurnOutcome.ESCALATED
        if payload.name == "book_inspection" and not payload.body.get("error"):
            if payload.body.get("status") == "booked":
                return TurnOutcome.INSPECTION_BOOKED
            return TurnOutcome.INSPECTION_OFFERED
        outcome = payload.body.get("outcome")
        if outcome in (Outcome.ESCALATION.value, "escalation"):
            return TurnOutcome.ESCALATED
        if outcome in (Outcome.SITE_ASSESSMENT.value, "site_assessment"):
            return TurnOutcome.INSPECTION_OFFERED
        if outcome in (
            Outcome.FIXED_OFFER.value,
            Outcome.INDICATIVE_RANGE.value,
            "fixed_offer",
            "indicative_range",
        ):
            return TurnOutcome.QUOTED
        if payload.name == "get_quote" and payload.body.get("card_link"):
            return TurnOutcome.QUOTED
    if "?" in text:
        return TurnOutcome.ASKED
    return TurnOutcome.ANSWERED


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
        cases: CaseFileRepository | None = None,
        book_inspection=None,
        escalate_to_owner=None,
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
        self._active_tenant = None
        self._active_conversation = None
        self._seen: dict[str, ExtractionResult] = {}
        self._business = business or BusinessView()
        self._cases = cases
        self._book = book_inspection
        self._escalate = escalate_to_owner
        self._step = NextStep(kind=StepKind.ASK, sentence="What should I quote for you?")
        self._model_calls = 0
        self._bad_arguments = 0

    def acknowledge(self, provider_message_ids) -> None:
        """Messages already stored before this process started are not answered again."""
        self._closed.update(provider_message_ids)

    def execute(self, context: TenantContext | None, conversation_id: UUID) -> TurnOutcome | None:
        if context is None:
            raise TenantRequired()
        if not self._lock.acquire(conversation_id):
            return None
        try:
            return self._run(context, conversation_id)
        except Exception as exc:
            _log.exception("Turn failed closed.")
            return self._fail(context, conversation_id, exc)
        finally:
            self._lock.release(conversation_id)

    def _run(self, context: TenantContext, conversation_id: UUID) -> TurnOutcome | None:
        conversation = self._conversations.get(context.tenant_id, conversation_id)
        if conversation is None:
            return None
        if self._deliver_unsent(context, conversation_id):
            conversation = self._conversations.get(context.tenant_id, conversation_id) or conversation
        self._active_tenant = context.tenant_id
        self._active_conversation = conversation_id
        self._model_calls = 0
        self._bad_arguments = 0
        pending = tuple(
            event for event in conversation.events if event.status == "pending"
        )
        batch = close_batch(pending, window=self._window, now=self._clock.now())
        if batch is None:
            return None
        claimed = self._claim(context, conversation_id, batch)
        if claimed is None:
            return None
        batch = claimed
        wa_id = _wa_id(self._conversations, context.tenant_id, conversation_id)
        if self._held(context, conversation_id):
            return self._acknowledge_held(context, conversation, conversation_id, wa_id, batch)
        remember_name(self._conversations, context.tenant_id, conversation_id, wa_id, batch)
        prompt = self._prompt(context, conversation)
        if _unfinished_video(batch, self._conversations.messages(context.tenant_id, conversation_id)):
            _log.info("Turn handled by video acknowledgement")
            return self._commit(
                context, conversation, conversation_id, wa_id, batch, _VIDEO, "answered", TurnOutcome.ANSWERED
            )
        if _PHRASE in "\n".join(event.body for event in batch).casefold():
            _log.info("Turn handled by handover")
            self._handover.execute(context, conversation_id, reason=_PHRASE_REASON)
            return self._commit(
                context,
                conversation,
                conversation_id,
                wa_id,
                batch,
                _HANDOVER,
                "escalated",
                TurnOutcome.ESCALATED,
            )
        _log.info("Turn handled by %s", type(self._model).__name__)
        reply = self._spoken(prompt)
        if reply is None:
            self._handover.execute(context, conversation_id, reason=_TIMEOUT_REASON)
            return self._commit(
                context,
                conversation,
                conversation_id,
                wa_id,
                batch,
                _HANDOVER,
                "escalated",
                TurnOutcome.ESCALATED,
            )
        if not reply.tool_calls and not reply.text.strip():
            payloads: list[ToolPayload] = []
            self._ensure_plan(context, conversation_id, payloads)
            return self._say_step(context, conversation, conversation_id, wa_id, batch, TurnFacts(), payloads)
        facts, answered = self._run_tools(context, reply, prompt, batch, conversation_id)
        text = reply.text
        needs_follow_up = bool(reply.tool_calls) and (not text.strip() or _payload_failed(answered))
        if needs_follow_up:
            spoken = self._spoken(answered)
            if spoken is None:
                self._handover.execute(context, conversation_id, reason=_TIMEOUT_REASON)
                return self._commit(
                    context,
                    conversation,
                    conversation_id,
                    wa_id,
                    batch,
                    _HANDOVER,
                    "escalated",
                    TurnOutcome.ESCALATED,
                )
            if spoken.tool_calls:
                facts, answered = self._run_tools(context, spoken, answered, batch, conversation_id)
            text = spoken.text
            if not text.strip() and spoken.tool_calls:
                follow = self._spoken(answered)
                if follow is None:
                    self._handover.execute(context, conversation_id, reason=_TIMEOUT_REASON)
                    return self._commit(
                        context,
                        conversation,
                        conversation_id,
                        wa_id,
                        batch,
                        _HANDOVER,
                        "escalated",
                        TurnOutcome.ESCALATED,
                    )
                text = follow.text
        elif reply.text.strip():
            heard = _availability_sentence(answered) or _named_sentence(answered, "hold_slot")
            if heard and heard not in text:
                text = heard
        deposit_url = _named_sentence(answered, "create_deposit_link")
        if deposit_url and deposit_url not in text:
            text = f"{text.rstrip()} {deposit_url}".strip()
        text = _with_card(text, facts.card_link)
        planned = _planned_sentence(self._step, answered)
        if planned:
            text = planned
        if planned and (self._step.kind is StepKind.ESCALATE or _owner_took(answered.tool_payloads)):
            return self._commit(
                context,
                conversation,
                conversation_id,
                wa_id,
                batch,
                text,
                "escalated",
                TurnOutcome.ESCALATED,
            )
        if not text.strip() or (reply.tool_calls and not check_reply(text, facts).ok):
            if text.strip():
                second = self._complete(answered)
                if second is not None and second.text and check_reply(_with_card(second.text, facts.card_link), facts).ok:
                    text = _with_card(second.text, facts.card_link)
                else:
                    return self._say_step(context, conversation, conversation_id, wa_id, batch, facts, answered.tool_payloads)
            else:
                return self._say_step(context, conversation, conversation_id, wa_id, batch, facts, answered.tool_payloads)
        outcome = _classify(text, answered)
        status = "escalated" if outcome is TurnOutcome.ESCALATED else "answered"
        return self._commit(context, conversation, conversation_id, wa_id, batch, text, status, outcome)

    def _spoken(self, prompt: TurnPrompt) -> ModelReply | None:
        reply = self._complete(prompt)
        if reply is None or reply.tool_calls or reply.text.strip():
            return reply
        nudged = prompt.model_copy(update={"task": (prompt.task + "\n" + _NUDGE).strip()})
        return self._complete(nudged)

    def _claim(self, context: TenantContext, conversation_id: UUID, batch: tuple) -> tuple | None:
        ids = tuple(event.provider_message_id for event in batch)
        claimer = getattr(self._conversations, "claim_pending", None)
        if claimer is None:
            return batch
        got = tuple(claimer(context.tenant_id, conversation_id, ids))
        if set(got) != set(ids):
            return None
        return batch

    def _held(self, context: TenantContext, conversation_id: UUID) -> bool:
        reader = getattr(self._conversations, "escalation_held", None)
        if reader is None:
            return False
        return bool(reader(context.tenant_id, conversation_id))

    def _acknowledge_held(self, context, conversation, conversation_id, wa_id, batch) -> TurnOutcome:
        prompt = self._prompt(context, conversation)
        reply = self._spoken(prompt)
        if reply is not None and reply.tool_calls:
            allowed = tuple(call for call in reply.tool_calls if call.name == "update_case")
            if allowed:
                filtered = reply.model_copy(update={"tool_calls": allowed, "text": ""})
                self._run_tools(context, filtered, prompt, batch, conversation_id)
        latest = batch[-1].body
        try:
            self._handover.execute(context, conversation_id, reason=f"Added while waiting: {latest}")
        except Exception:
            _log.exception("The held conversation could not refresh the brief.")
        return self._commit(
            context,
            conversation,
            conversation_id,
            wa_id,
            batch,
            _ACK,
            "answered",
            TurnOutcome.ANSWERED,
        )

    def _deliver_unsent(self, context: TenantContext, conversation_id: UUID) -> bool:
        reader = getattr(self._conversations, "unsent", None)
        if reader is None:
            return False
        found = reader(context.tenant_id, conversation_id)
        if not found:
            return False
        batch_id, body = found
        wa_id = _wa_id(self._conversations, context.tenant_id, conversation_id) or ""
        self._send_named(wa_id, body)
        finish = getattr(self._conversations, "finish_outbound", None)
        if finish is not None:
            finish(context.tenant_id, batch_id)
        conversation = self._conversations.get(context.tenant_id, conversation_id)
        if conversation is not None:
            ids = set(batch_id.split("|"))
            pending = tuple(
                event
                for event in conversation.events
                if event.provider_message_id in ids and event.status in ("pending", "claimed")
            )
            if pending:
                self._settle(context, conversation, pending, "answered", TurnOutcome.ANSWERED)
        return True

    def _commit(
        self,
        context: TenantContext,
        conversation,
        conversation_id: UUID,
        wa_id: str,
        batch: tuple,
        body: str,
        status: str,
        outcome: TurnOutcome,
    ) -> TurnOutcome:
        fresh = self._conversations.get(context.tenant_id, conversation_id) or conversation
        named = with_name(self._conversations, context.tenant_id, wa_id, body)
        batch_id = "|".join(event.provider_message_id for event in batch)
        reserve = getattr(self._conversations, "reserve_outbound", None)
        action = "send"
        if reserve is not None:
            action = reserve(context.tenant_id, batch_id, conversation_id, self._clock.now(), named)
        self._settle(context, fresh, batch, status, outcome)
        if action == "send":
            self._send_named(wa_id, named)
            if reserve is None:
                record = getattr(self._conversations, "record_reply", None)
                if record is not None:
                    record(context.tenant_id, conversation_id, self._clock.now(), named)
            finish = getattr(self._conversations, "finish_outbound", None)
            if finish is not None and reserve is not None:
                finish(context.tenant_id, batch_id)
        if status == "escalated":
            hold = getattr(self._conversations, "hold_escalation", None)
            if hold is not None:
                hold(context.tenant_id, conversation_id)
        self._clear_change_key(context, conversation_id)
        return outcome

    def _settle(self, context: TenantContext, conversation, batch: tuple, status: str, outcome: TurnOutcome) -> None:
        ids = {event.provider_message_id for event in batch}
        log = tuple(
            event.model_copy(update={"status": status, "outcome": outcome.value})
            if event.provider_message_id in ids
            else event
            for event in conversation.log
        )
        self._conversations.save(context.tenant_id, conversation.model_copy(update={"log": log}))
        self._closed.update(ids)

    def _clear_change_key(self, context: TenantContext, conversation_id: UUID) -> None:
        saver = getattr(self._conversations, "save_change_key", None)
        if saver is not None:
            saver(context.tenant_id, conversation_id, None)
        self._change_key = None

    def _send_named(self, wa_id: str, body: str) -> None:
        buttons = ("Accept quote",) if "/card/" in body and "deposit/" not in body else ()
        try:
            self._sender.send(wa_id, body, buttons=buttons, image_url=None)
        except TypeError:
            self._sender.send(wa_id, body)

    def _dispatch(self, context: TenantContext, conversation_id: UUID, wa_id: str, body: str, *, reserved: bool) -> None:
        named = body if reserved else with_name(self._conversations, context.tenant_id, wa_id, body)
        self._send_named(wa_id, named)
        if not reserved:
            record = getattr(self._conversations, "record_reply", None)
            if record is not None:
                record(context.tenant_id, conversation_id, self._clock.now(), named)

    def _fail(self, context: TenantContext, conversation_id: UUID, exc: BaseException) -> TurnOutcome:
        reason = f"{type(exc).__name__}: {exc}"
        recorded = False
        if self._escalate is not None:
            try:
                self._escalate.execute(context, EscalateToOwnerInput(conversation_id=conversation_id, summary=reason))
                recorded = True
            except Exception:
                _log.exception("The failed turn could not write the brief.")
        if not recorded:
            try:
                self._handover.execute(context, conversation_id, reason=reason)
            except Exception:
                _log.exception("Handover during a failed turn did not record.")
        try:
            conversation = self._conversations.get(context.tenant_id, conversation_id)
        except Exception:
            conversation = None
        try:
            wa_id = _wa_id(self._conversations, context.tenant_id, conversation_id) or ""
        except Exception:
            wa_id = ""
        if conversation is None:
            try:
                self._dispatch(context, conversation_id, wa_id, _HANDOVER, reserved=False)
            except Exception:
                _log.exception("The failed turn could not speak.")
            return TurnOutcome.ESCALATED
        pending = tuple(event for event in conversation.events if event.status in ("pending", "claimed"))
        if not pending:
            try:
                self._dispatch(context, conversation_id, wa_id, _HANDOVER, reserved=False)
            except Exception:
                _log.exception("The failed turn could not speak.")
            hold = getattr(self._conversations, "hold_escalation", None)
            if hold is not None:
                hold(context.tenant_id, conversation_id)
            return TurnOutcome.ESCALATED
        try:
            return self._commit(
                context,
                conversation,
                conversation_id,
                wa_id,
                pending,
                _HANDOVER,
                "escalated",
                TurnOutcome.ESCALATED,
            )
        except Exception:
            _log.exception("The failed turn could not settle.")
            return TurnOutcome.ESCALATED

    def _complete(self, prompt: TurnPrompt) -> ModelReply | None:
        if self._model_calls >= _CALLS:
            return None
        try:
            reply = self._call(prompt)
        except ModelTimeout:
            if self._model_calls >= _CALLS:
                return None
            try:
                reply = self._call(prompt)
            except ModelTimeout:
                _log.warning("Model %s timed out", type(self._model).__name__)
                return None
        except ToolArgumentsInvalid:
            if self._bad_arguments >= 1 or self._model_calls >= _CALLS:
                raise
            self._bad_arguments += 1
            retried = prompt.model_copy(
                update={
                    "effort": "low",
                    "exchanges": prompt.exchanges
                    + (
                        {
                            "type": "function_call_output",
                            "call_id": "invalid",
                            "output": json.dumps({"error": "The tool arguments could not be read."}),
                        },
                    ),
                }
            )
            try:
                reply = self._call(retried)
            except ToolArgumentsInvalid:
                raise
        _log_model_reply(self._model, reply)
        return reply

    def _call(self, prompt: TurnPrompt) -> ModelReply:
        self._model_calls += 1
        return self._model.complete(prompt)

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
            task=self._task_for(context, conversation),
            effort="medium",
        )

    def _task_for(self, context: TenantContext, conversation) -> str:
        self._step = self._next(context, conversation.conversation_id)
        task = _task(self._conversations, context, conversation, self._policies)
        return (
            f"{task}\nThe next step is {self._step.kind.value}. {self._step.sentence} "
            "Phrase that step. If the photo already estimates that fact, say the estimate and ask them to confirm it. "
            "Do not choose a different step."
        )

    def _next(self, context: TenantContext, conversation_id: UUID) -> NextStep:
        from quotedesk.domain.case.case_file import CaseFile
        from quotedesk.domain.policy.rules import Policy
        from quotedesk.domain.shared.ids import PolicyVersionId

        case = self._case(context, conversation_id)
        if case is None:
            case = CaseFile.open(conversation_id, context.tenant_id)
        playbook = BusinessPlaybook()
        policy = Policy(
            version=PolicyVersionId("planner-policy-v1.0"),
            rules=(),
            rate_card_codes=(),
            sam_score_threshold=Decimal("0"),
        )
        if self._policies is not None:
            bundle = self._policies.published(context.tenant_id)
            if bundle is not None:
                playbook = bundle.playbook
                policy = bundle.policy
        from quotedesk.application.use_cases.tools.planner_inputs import planner_inputs

        text, asked = planner_inputs(self._conversations, context.tenant_id, conversation_id, playbook)
        return plan_next_step(case, playbook, policy, asked=asked, customer_text=text)

    def _case(self, context: TenantContext, conversation_id: UUID):
        if self._cases is None:
            return None
        return self._cases.get(context.tenant_id, conversation_id)

    def _say_step(self, context, conversation, conversation_id, wa_id, batch, facts, payloads):
        sentence = _grounded(payloads, facts) or self._step.sentence
        owner = _owner_took(payloads)
        if self._step.kind is StepKind.ESCALATE and not owner:
            self._handover.execute(context, conversation_id, reason=self._step.reason or "The next step is to escalate.")
        if self._step.kind is StepKind.ESCALATE or owner:
            body = sentence or _HANDOVER
            return self._commit(context, conversation, conversation_id, wa_id, batch, body, "escalated", TurnOutcome.ESCALATED)
        body = _with_card(sentence, facts.card_link)
        return self._commit(
            context,
            conversation,
            conversation_id,
            wa_id,
            batch,
            body,
            "answered",
            _classify(body, TurnPrompt(event_ids=(), tool_payloads=tuple(payloads))),
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
        case = self._case(context, conversation_id)
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
                    notes=result.notes,
                )
            )
        return tuple(rows)

    def _read_image(
        self,
        context: TenantContext,
        conversation_id: UUID,
        event: ConversationEvent,
    ) -> ExtractionResult | None:
        cached = None
        getter = getattr(self._conversations, "enrichment", None)
        if getter is not None and self._active_tenant is not None:
            cached = getter(self._active_tenant, event.provider_message_id)
        if cached is None:
            cached = self._seen.get(event.provider_message_id)
        if cached is not None:
            return cached
        if self.enricher is None:
            return None
        result = self.enricher.for_image(event.provider_message_id)
        if result is None:
            return None
        saver = getattr(self._conversations, "save_enrichment", None)
        if saver is not None and self._active_tenant is not None:
            saver(self._active_tenant, event.provider_message_id, result)
        else:
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
            arguments = _with_quote(
                call.name,
                _bound(call.name, _on_conversation(call.name, call.arguments, conversation_id), self._step),
                _known_quote(self._conversations, context, conversation_id, payloads),
            )
            if call.name == "update_case":
                payloads.append(self._update(context, _with_message_ids(arguments, batch)))
            elif call.name == "get_quote":
                payloads.append(self._quote(context, arguments, batch, amounts, clauses))
                price_kind, card_link = _quote_facts(payloads[-1], self._card_base, self._card_code, price_kind, card_link)
                self._handover_escalation(context, conversation_id, payloads[-1])
            elif call.name == "request_change":
                payloads.append(self._change(context, arguments, amounts, clauses))
            elif call.name == "check_availability":
                payloads.append(self._availability(context, arguments, civil_dates))
                if payloads[-1].body.get("earliest_window"):
                    schedule_status = "indicative"
            elif call.name == "accept_quote":
                payloads.append(self._accept(context, arguments))
            elif call.name == "create_deposit_link":
                payloads.append(self._deposit_link(context, arguments))
            elif call.name == "hold_slot":
                payloads.append(self._hold(context, arguments))
            elif call.name == "book_inspection":
                payloads.append(self._booked(context, arguments))
            elif call.name == "escalate_to_owner":
                payloads.append(self._escalated(context, arguments))
            else:
                payloads.append(_refused(call.name))
            _log_tool(payloads[-1])
        stored = self._conversations.get(context.tenant_id, conversation_id)
        if stored is not None:
            self._step = self._next(context, conversation_id)
        if "get_quote" not in names and "check_availability" not in names and self._should_quote(payloads):
            payloads.append(
                self._quote(context, {"conversation_id": str(conversation_id)}, batch, amounts, clauses)
            )
            names.append("get_quote")
            price_kind, card_link = _quote_facts(
                payloads[-1], self._card_base, self._card_code, price_kind, card_link
            )
            self._handover_escalation(context, conversation_id, payloads[-1])
            _log_tool(payloads[-1])
        self._ensure_plan(context, conversation_id, payloads)
        task = self._task_for(context, stored) if stored is not None else prompt.task
        answered = prompt.model_copy(
            update={
                "tool_results": tuple(names),
                "tool_payloads": tuple(payloads),
                "exchanges": prompt.exchanges + _exchanges(reply, payloads),
                "effort": "low",
                "task": task,
            }
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

    def _ensure_plan(self, context: TenantContext, conversation_id: UUID, payloads: list) -> None:
        if self._book is not None and self._step.kind is StepKind.INSPECTION:
            if not any(item.name == "book_inspection" and not item.body.get("error") for item in payloads):
                payloads.append(
                    self._booked(
                        context,
                        {"conversation_id": conversation_id, "job_id": self._step.job_id, "summary": ""},
                    )
                )
        if self._escalate is not None and self._step.kind is StepKind.ESCALATE:
            if not any(item.name == "escalate_to_owner" and not item.body.get("error") for item in payloads):
                payloads.append(self._escalated(context, {"conversation_id": conversation_id, "summary": ""}))

    def _booked(self, context: TenantContext, arguments: dict) -> ToolPayload:
        if self._book is None:
            return _refused("book_inspection")
        try:
            result = self._book.execute(context, BookInspectionInput(**arguments))
        except (CaseNotFound, ValidationError, ModelError) as error:
            return ToolPayload(name="book_inspection", body={"error": getattr(error, "sentence", str(error))})
        return ToolPayload(name="book_inspection", body=_body(result))

    def _escalated(self, context: TenantContext, arguments: dict) -> ToolPayload:
        if self._escalate is None:
            return _refused("escalate_to_owner")
        try:
            result = self._escalate.execute(context, EscalateToOwnerInput(**arguments))
        except (CaseNotFound, ValidationError, ModelError) as error:
            return ToolPayload(name="escalate_to_owner", body={"error": getattr(error, "sentence", str(error))})
        return ToolPayload(name="escalate_to_owner", body=_body(result))

    def _should_quote(self, payloads: list[ToolPayload]) -> bool:
        if self._step.kind is not StepKind.QUOTE:
            return False
        if any(item.name == "get_quote" for item in payloads):
            return False
        return any(item.name == "update_case" and not item.body.get("error") for item in payloads)

    def _update(self, context: TenantContext, arguments: dict) -> ToolPayload:
        try:
            data = UpdateCaseInput(**_without_confidence(arguments))
        except (ModelError, ValidationError) as error:
            self._bad_arguments += 1
            if self._bad_arguments >= 2:
                raise ToolArgumentsInvalid() from error
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
            if not isinstance(error, CaseNotFound):
                self._bad_arguments += 1
                if self._bad_arguments >= 2:
                    raise ToolArgumentsInvalid() from error
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
        getter = getattr(self._conversations, "change_key", None)
        key = None
        if getter is not None and self._active_conversation is not None and self._active_tenant is not None:
            key = getter(self._active_tenant, self._active_conversation)
        if key is None:
            key = self._change_key
        if key is None:
            key = self._ids.next_idempotency_key()
            saver = getattr(self._conversations, "save_change_key", None)
            if saver is not None and self._active_conversation is not None and self._active_tenant is not None:
                saver(self._active_tenant, self._active_conversation, key)
            else:
                self._change_key = key
        raw["idempotency_key"] = key
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
        case = self._case(context, conversation_id)
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
                system=True,
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


def _bound(name: str, arguments: dict, step: NextStep) -> dict:
    bound = dict(arguments)
    if name in ("update_case", "book_inspection") and not str(bound.get("job_id") or "").strip() and step.job_id:
        bound["job_id"] = step.job_id
    return bound


_QUOTED = frozenset({"request_change", "accept_quote", "create_deposit_link", "hold_slot"})
_CARD_ID = re.compile(r"/card/(QD-\d{4,8})")


def _with_quote(name: str, arguments: dict, quote_id: str | None) -> dict:
    if name not in _QUOTED or not quote_id:
        return arguments
    bound = dict(arguments)
    bound["quote_id"] = quote_id
    return bound


def _known_quote(conversations, context, conversation_id: UUID, payloads: list[ToolPayload]) -> str | None:
    for item in reversed(payloads):
        found = _quote_value(item.body.get("quote_id")) if item.name == "get_quote" and not item.body.get("error") else None
        if found:
            return found
    replies = getattr(conversations, "replies", None)
    if replies is None:
        return None
    found = None
    for _at, body in replies(context.tenant_id, conversation_id):
        match = _CARD_ID.search(body or "")
        if match:
            found = match.group(1)
    return found


def _quote_value(raw) -> str | None:
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    if isinstance(raw, dict) and str(raw.get("value") or "").strip():
        return str(raw["value"]).strip()
    return None


def _exchanges(reply: ModelReply, payloads: list[ToolPayload]) -> tuple[dict, ...]:
    rows: list[dict] = []
    for index, (call, payload) in enumerate(zip(reply.tool_calls, payloads)):
        call_id = call.call_id or f"call-{index}"
        rows.append(
            {
                "type": "function_call",
                "name": call.name,
                "arguments": json.dumps(call.arguments),
                "call_id": call_id,
            }
        )
        rows.append(
            {
                "type": "function_call_output",
                "call_id": call_id,
                "output": json.dumps(payload.body),
            }
        )
    return tuple(rows)


def _owner_took(payloads) -> bool:
    return any(getattr(item, "name", None) == "escalate_to_owner" and not item.body.get("error") for item in payloads)


def _planned_sentence(step: NextStep, prompt: TurnPrompt) -> str | None:
    if step.kind is StepKind.INSPECTION:
        return _named_sentence(prompt, "book_inspection")
    if step.kind is StepKind.ESCALATE:
        return _named_sentence(prompt, "escalate_to_owner")
    return None


def _grounded(payloads, facts: TurnFacts) -> str | None:
    for item in payloads:
        if item.name in ("book_inspection", "escalate_to_owner") and not item.body.get("error"):
            sentence = item.body.get("sentence")
            if isinstance(sentence, str) and sentence.strip():
                return sentence
    for item in payloads:
        if item.name != "get_quote" or item.body.get("error"):
            continue
        if item.body.get("outcome") == "indicative_range":
            low = _amount(item.body.get("range_min"))
            high = _amount(item.body.get("range_max"))
            if low and high:
                sentence = f"The indicative range is R {low}." if low == high else f"The indicative range is R {low} to R {high}."
                return _with_card(sentence, facts.card_link)
        template = item.body.get("customer_template")
        if isinstance(template, str) and template.strip():
            return _with_card(template.strip(), facts.card_link)
    for item in payloads:
        if item.name == "check_availability":
            sentence = item.body.get("sentence")
            if isinstance(sentence, str) and sentence.strip():
                return sentence
        if item.name == "request_change" and not item.body.get("error"):
            return "The request is waiting."
    return None


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
    if name not in ("update_case", "get_quote", "book_inspection", "escalate_to_owner"):
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
