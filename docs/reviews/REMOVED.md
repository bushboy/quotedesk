# Removed

Each line is a name, the commit that removed it, why it went, and what replaced it.

| Name | Commit | Reason | Replacement |
| --- | --- | --- | --- |
| `acknowledge` | 3b8a726 | No production caller. | `_settle` |
| `_speak` | 3b8a726 | No production caller. | `_send_named` |
| `_close` | 3b8a726 | No production caller. | none |
| `_closed` | 3b8a726 | No production caller. | none |
| `_REFUSAL` | 3b8a726 | No production caller. | none |
| `_BLOCKED_WHILE_HELD` | 3b8a726 | No production caller. A held conversation already returns before tools run. | `_acknowledge_held` |
| `QuoteClock` | 3b8a726 | No production caller. | `TurnClock` and `SystemClock` |
| `save_with_audit` | 3b8a726 | No production caller. | The audit insert in `StoredUnit` |
| `resolve_tenant` | 3b8a726 | No production caller. | `open_tenant` |
| `unknown_tenant_sentence` | 3b8a726 | No production caller. | The `ValueError` sentence in `known_tenant` |
| `MediaEnricher` | 3b8a726 | No production caller. The turn calls `ImageEnricher` directly. | none |
| `AuditLog` | 3b8a726 | No production caller. The live audit is the unit of work. | `StoredUnit` |
| `agreement` on the quote path | 3b8a726 | A SAM miss is not a customer contradiction, and it does not block a confirmed quote. | The spec replay and the clash record |
| `measurement` on the quote path | 3b8a726 | A size disagreement is a clash the customer settles, not a band. | The spec replay and the clash record |
| `WATER-L01` | 3b8a726 | Low confidence is an unknown rate-card code. An unconfirmed spec is a range or an escalation. | `WATER-L02` and the spec replay |
| `FAB-L01` | 3b8a726 | Low confidence is an unknown rate-card code. An unconfirmed spec is a range or an escalation. | `FAB-L02` and the spec replay |
| `_CARPORT_READ` | 3b8a726 | A hardcoded carport prompt. | `read_from` on the playbook |
| `_TANK_READ` | 3b8a726 | A hardcoded tank prompt. | `read_from` on the playbook |
