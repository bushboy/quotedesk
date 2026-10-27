# Conversation

Written 30 October 2026. Tests and `quotedesk/domain/conversation/events.py` implement this note and nothing beyond it.

The proposed shape in the Friday plan is confirmed.

The log is append-only and unique per provider message id. Arrival order is not read order.

## Module

`quotedesk.domain.conversation.events`

Imports allowed: the standard library, Pydantic, and `quotedesk.domain`. The type does not read the clock, the environment, or the network. It does not mint an id. The caller passes `conversation_id`, the provider message id, and the provider timestamp.

Value types are frozen Pydantic models with extra fields forbidden. Methods return a new value or raise. The receiver is unchanged.

## Open

```text
Conversation.open(conversation_id: UUID) -> Conversation
```

No events.

## Append

```text
append(provider_message_id: str, at: datetime, body: str) -> AppendResult
```

`AppendResult` has `conversation: Conversation` and `duplicate: bool`.

The first call stores one event and returns `duplicate` false. A second call with the same `provider_message_id` returns `duplicate` true and the same events. It does not raise. It does not append a second event. The id match is exact.

`at` is the provider timestamp. The event stores that instant. The type does not call `datetime.now`.

## Read order

`conversation.events` is the events in provider-timestamp order, earliest first. A later timestamp appended first, then an earlier one, reads as the earlier event and then the later event.

## Body

```text
replace_body(provider_message_id: str, body: str) -> Conversation
```

This raises `PolicyViolation` with code `policy.violation` and sentence `A message body is not edited.` The stored text stays the text `append` wrote.

## Enrichment

```text
attach(provider_message_id: str, *, transcript_id: str | None = None, extraction_id: str | None = None) -> Conversation
```

The ids are stored on the event that already has that provider message id. The event count stays one. `attach` does not append a customer event.

An event's fields are `provider_message_id`, `at`, `body`, `transcript_id`, and `extraction_id`. The two enrichment ids start as `None`.
