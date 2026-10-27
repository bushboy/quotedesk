# Webhook fixture and outbox

Written 29 October 2026. The text fixture and `quotedesk/adapters/outbound/channels/outbox.py` implement this note and nothing beyond it.

No database table is created. The outbox does not call the network and does not send a row.

## Text fixture

Path: `tests/fixtures/whatsapp/text_message.json`.

One Cloud API webhook payload. One message. `type` is `text`. The body is customer text. It is not a price, an outcome, a clause, or a rule.

The body is `The tank in the yard is leaking.`

```json
{
  "object": "whatsapp_business_account",
  "entry": [
    {
      "id": "WABA-1",
      "changes": [
        {
          "field": "messages",
          "value": {
            "messaging_product": "whatsapp",
            "metadata": {
              "display_phone_number": "15550001111",
              "phone_number_id": "PHONE-1"
            },
            "contacts": [
              {
                "profile": { "name": "Thabo" },
                "wa_id": "15550002222"
              }
            ],
            "messages": [
              {
                "from": "15550002222",
                "id": "wamid.TEXT1",
                "timestamp": "1761710000",
                "type": "text",
                "text": { "body": "The tank in the yard is leaking." }
              }
            ]
          }
        }
      ]
    }
  ]
}
```

The adapter test reads this file. It asserts one message, type `text`, and a non-empty body. It does not parse the payload into a domain event.

## Outbox

Module: `quotedesk.adapters.outbound.channels.outbox`.

The module does not import `quotedesk.domain`. It does not import an HTTP client. `append` stores a row in memory. `pending` reads pending rows back. Nothing in the module opens a socket or marks a row sent.

```text
Outbox() -> empty
append(body: str) -> OutboxMessage
pending() -> tuple[OutboxMessage, ...]
```

`OutboxMessage` is a frozen Pydantic model with extra fields forbidden.

| Field | Value |
| --- | --- |
| `body` | The string passed to `append` |
| `status` | `pending` |

`pending` returns the appended messages in append order. A second `Outbox()` does not see the first one's rows. There is no `send` method.
