import re
from datetime import timedelta

from quotedesk.application.dto.inbound import GateFlags, GateLimits, InboundMessage, ReceiveResult
from quotedesk.application.dto.tenant import TenantContext
from quotedesk.application.errors import TenantRequired
from quotedesk.application.ports.gate import ChannelSender, MediaClassifier, MediaStore
from quotedesk.application.ports.repositories import ConversationRepository
from quotedesk.application.ports.runtime import Clock
from quotedesk.domain.conversation.events import Conversation
from quotedesk.domain.services.injection import classify_injection_claims

_FILE = "That file is too large or of a type I can't read. Please send a shorter one, or type the details."
_RATE = "I'm getting a lot of messages at once. Please send the next one in a minute."
_SENSITIVE = "I didn't keep that. Please resend without the sensitive image."
_LANGUAGE = "Sorry, I can't understand that yet. Could you send it in English?"
_AFRIKAANS = ("asseblief", "dankie", "tenk", "goeiemôre")
_WINDOW = timedelta(seconds=60)


class ReceiveInboundEvent:
    def __init__(
        self,
        conversations: ConversationRepository,
        sender: ChannelSender,
        media: MediaStore,
        classifier: MediaClassifier,
        clock: Clock,
    ) -> None:
        self._conversations = conversations
        self._sender = sender
        self._media = media
        self._classifier = classifier
        self._clock = clock

    def execute(
        self,
        context: TenantContext | None,
        data: InboundMessage,
        flags: GateFlags,
        limits: GateLimits,
    ) -> ReceiveResult:
        if context is None:
            raise TenantRequired()
        conversation = self._conversations.get(context.tenant_id, data.conversation_id)
        if conversation is None:
            conversation = Conversation.open(data.conversation_id)
        if any(event.provider_message_id == data.provider_message_id for event in conversation.log):
            return ReceiveResult(stored=True, duplicate=True, sentence=None, injection_instruction=False)
        if self._over_rate(context.tenant_id, data, limits):
            return self._refuse(data.wa_id, _RATE)
        if _file_refused(data, limits):
            return self._refuse(data.wa_id, _FILE)
        if _language_refused(data, flags):
            return self._refuse(data.wa_id, _LANGUAGE)
        if data.kind == "image":
            category = self._classifier.classify(data)
            if category in ("explicit", "sensitive_document"):
                return self._refuse(data.wa_id, _SENSITIVE)
        instruction = _instruction(data)
        stored = conversation.append(data.provider_message_id, data.at, _event_body(data))
        self._conversations.save(context.tenant_id, stored.conversation)
        self._conversations.note(context.tenant_id, data.wa_id, data.at)
        self._conversations.remember(context.tenant_id, data)
        return ReceiveResult(
            stored=True,
            duplicate=False,
            sentence=None,
            injection_instruction=instruction,
        )

    def _over_rate(self, tenant_id, data: InboundMessage, limits: GateLimits) -> bool:
        start = data.at - _WINDOW
        count = sum(1 for at in self._conversations.noted(tenant_id, data.wa_id) if start <= at <= data.at)
        return count >= limits.messages_per_minute

    def _refuse(self, wa_id: str, sentence: str) -> ReceiveResult:
        self._sender.send(wa_id, sentence)
        return ReceiveResult(stored=False, duplicate=False, sentence=sentence, injection_instruction=False)


def _file_refused(data: InboundMessage, limits: GateLimits) -> bool:
    if data.size_bytes == 0:
        return True
    if data.size_bytes is not None and data.size_bytes > limits.max_bytes:
        return True
    if data.mime is not None and data.mime not in limits.allowed_types:
        return True
    if (
        data.kind == "audio"
        and data.duration_seconds is not None
        and data.duration_seconds > limits.max_audio_seconds
    ):
        return True
    return False


def _language_refused(data: InboundMessage, flags: GateFlags) -> bool:
    if data.kind == "text" and not flags.afrikaans_text and _afrikaans(data.body):
        return True
    if data.kind == "audio" and not flags.afrikaans_voice and _afrikaans(data.transcript):
        return True
    return False


def _afrikaans(text: str | None) -> bool:
    if text is None or text == "":
        return False
    folded = text.casefold()
    return any(re.search(rf"(?<!\w){re.escape(word.casefold())}(?!\w)", folded) for word in _AFRIKAANS)


def _instruction(data: InboundMessage) -> bool:
    found = False
    for text in (data.body, data.transcript, data.image_text):
        if text:
            found = found or classify_injection_claims(text).instruction
    return found


def _event_body(data: InboundMessage) -> str:
    if data.kind == "audio":
        return data.transcript or data.body or ""
    if data.kind == "image":
        return data.image_text or data.body or ""
    return data.body or ""
