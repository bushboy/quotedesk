# Image context

Written 28 October 2026. The decisions in [the slice plan](../PLAN.md) are confirmed. The running model is Spark. This slice does not install `RecordedEnricher` on that path. `decide`, `price`, `select_clauses`, `derive_confidence`, `cross_model_agreement`, `measurement_acceptable`, `media_is_usable`, `GetQuote`, `RequestChange`, `CheckAvailability`, `UpdateCase`, and `check_reply` are not edited. The SAM parser is not edited.

A test of the turn does not open a socket. The adapter test injects `post(url, body) -> dict` and does not call `api.meta.ai`.

## Modules

| Name | Module |
| --- | --- |
| `media_id` on `InboundMessage` | `quotedesk.application.dto.inbound` |
| `ImageHost` | `quotedesk.application.ports.media` |
| `for_image(provider_message_id)` | `MediaEnricher`, unchanged |
| Trail, cache, `extraction_id` | `quotedesk.application.use_cases.conversation.run_agent_turn` |
| Media id, measured size | `quotedesk.adapters.inbound.http.whatsapp` |
| One message per selected file | `quotedesk.adapters.inbound.http.templates.chat.html` |
| `ImageEnricher` | `quotedesk.adapters.outbound.models.image_context` |
| Install | `quotedesk.infrastructure.container` and `quotedesk.infrastructure.demo` |

The turn does not read pixels. The enricher asks `ImageHost.get(media_id)` for `(mime, bytes)` or nothing. The host on the running app is the simulator media store. This slice does not call the Graph media URL.

## Channel

`InboundMessage.media_id` defaults to absent. The webhook copies `image.id` into it. When the host has that id, `size_bytes` is the byte length. The caption stays the body. A missing id is still stored. The enricher then returns no result.

The live gate allows `image/jpeg` and `image/png` up to 5 MiB. An empty object (`size_bytes` 0) is refused. `image/webp` is refused. The sentence is the one already on the inbound gate.

The file input accepts many files. Each file is its own webhook message. The caption is on the first. The others have an empty caption.

## One read

`ImageEnricher.note(provider_message_id, media_id, caption)` records where the bytes are. The webhook calls it for an image. `for_image` loads those bytes once.

The first Responses call carries the caption and the bytes. The parsed object is `summary`, `objects`, `blur`, `darkness`, `wrong_subject`. `size_litres`, `unit_price`, and `outcome` are dropped if present.

The second Responses call asks SAM to segment the object names from that result. `parse_sam_response` is unchanged. A failure sets `sam_error`, leaves the masks empty, and keeps the Spark summary. Masks become `RecordedMask` values. Scores stay `Decimal`.

The result is cached on the provider message id. A second `for_image` does not post. The turn also keeps that result and, when the event has no `extraction_id`, attaches the message id and saves the conversation. The event body stays the caption.

## Prompt and agreement

`extractions` is one row per image in the last 20 messages: provider message id, summary, object names. No score, no unit price, no bytes. A text message adds no row. An image with no result adds no row.

Before `get_quote`, agreement and `media_is_usable` use those same images. Objects are the union. Masks are the union. `sam_error` if any result failed. Usability is the OR of the flags. No image in those 20, or no enricher, keeps `has_media` false.

The task gains these three sentences:

```text
Use each extraction with the message it names.
When the photo and the customer disagree, ask one question.
A size that appears only in an extraction is not customer_stated.
```

WATER-F01 is unchanged. The photo can make agreement and media true. It cannot supply the litres. `photo_inferred`, blur, a SAM error, empty masks, and an object with no matching mask leave WATER-F01 unmatched. The outbox is then the site-visit template, with no rand amount.

The summary is not an outbox row. The model writes the reply.
