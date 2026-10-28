# RunAgentTurn

Written 31 October 2026. Tests and `quotedesk/application/use_cases/conversation/run_agent_turn.py` implement this note and nothing beyond it.

The proposed shape in the Saturday plan is confirmed. One turn calls tools, checks the reply, and only then writes the outbox. A later outbox row is a later bubble. This note does not paint the thread.

`check_reply` is the function in `quotedesk.domain.services.commitments`. This note does not change it and does not write the outbox from inside it. `GetQuote` still does not call `schedule`.

The model is a fake. The test does not open a network connection. This module does not import an HTTP client.

## Module

`quotedesk.application.use_cases.conversation.run_agent_turn`

| Name | Role |
| --- | --- |
| `close_batch` | The quiet window |
| `RunAgentTurn` | One locked turn |
| `HandoverToHuman` | The case file goes to a person |
| `ModelTimeout` | `quotedesk.application.errors`. The fake raises it |

`ChannelSender` is the port from `design/inbound-gate.md`. `RunAgentTurn` calls `send` only after `check_reply` returns `ok` true, or to send one of the fixed sentences below.

## Clock and window

The clock is injected. Nothing in this module calls `datetime.now`.

The fixture window is 5 seconds. The base instant is `datetime(2026, 10, 24, 0, 0, tzinfo=timezone.utc)`.

```text
close_batch(events, *, window, now) -> tuple[ConversationEvent, ...] | None
```

The open batch starts at the earliest event that is not yet in a closed batch. An event is inside when `event.at - start <= window`. `now - start >= window` closes it. `now - start < window` returns `None`.

| `at` offset | `now` offset | In the closed batch |
| --- | --- | --- |
| 0s, 1s, 4s | 5s | yes, one batch |
| 5.0s | 5.0s | yes, with the three above |
| 5.1s | 5.1s | no. It is the start of the next batch |

`5.0 - 0` is equal to the window, so it is inside. `5.1 - 0` is greater, so it is outside. The next call, with the 5.1s event as the start, is the next turn.

## Lock

`ConversationLock.acquire(conversation_id)` runs before the prompt is built. `release` runs when the turn finishes, including when it sends a refusal or the handover sentence.

The prompt's event ids are the ids already stored at acquire. A message appended while the fake model is inside `complete` is absent from that prompt and present in the next turn's prompt. The next prompt reads events in provider-timestamp order.

A second `acquire` while the lock is held does not start a second turn.

## Model

```text
AgentModel.complete(prompt) -> ModelReply
```

`ModelReply` has `text: str` and `tool_calls: tuple[ToolCall, ...]`. `ToolCall` has `name: str` and `arguments: dict`. The fake returns the script and does not open a socket.

The script for the quote turn calls `update_case`, then `get_quote`. The use case runs those two use cases and appends their results to the prompt for the reply. It does not call `schedule`.

The `get_quote` fake returns one line total `Money("4250.00")`. That amount is the only entry in `TurnFacts.amounts`. `card_link` stays `None`. `price_kind` is `fixed`.

## Checked reply

`check_reply(reply, facts)` runs before `send`.

| Draft | Outbox |
| --- | --- |
| `The total is R 4 250.` | That sentence. One row |
| `The total is R 3 000.` | The fixed refusal below. `R 3 000` is not in any row |

The fixed refusal is:

```text
I can only repeat what the quote says.
```

That sentence has no rand amount. The use case may ask the model once more after a failed check. The bad-price script has no second reply, so the outbox receives the fixed refusal and not a second model draft. A second scripted reply that passes `check_reply` is sent instead of the refusal. The failed draft is never sent.

## Video

A batched event with `kind` `video` and both `transcript_id` and `extraction_id` still `None` is unfinished. The outbox receives:

```text
Got your video, having a look.
```

The model is not called. `GetQuote` is not called. The final answer is a later turn, after enrichment is attached. This note does not implement that later turn.

## Timeout

`ModelTimeout` from `complete`. The use case calls `complete` once more.

| First call | Second call | Customer receives |
| --- | --- | --- |
| `ModelTimeout` | a reply that passes `check_reply` | that reply |
| `ModelTimeout` | `ModelTimeout` | I'll ask someone from the business to pick this up. You can keep sending details here. |

The second timeout does not call `GetQuote`. There is no third model call.

## Handover

The batch text contains `Can I speak to a person?`, compared case-insensitively. This check runs before `complete`. The model is not called. `GetQuote` is not called.

`HandoverToHuman.execute(context, conversation_id)` loads the case file and stores one `Handover` with that case attached. The outbox receives the handover sentence above. The same sentence is the timeout sentence. The phrase path and the timeout path both use it, copied verbatim.

```text
Handover
    conversation_id: UUID
    case: CaseFile
    reason: str
```

On the phrase path, `reason` is `Can I speak to a person?`. On the timeout path, `reason` is `model timeout`.
