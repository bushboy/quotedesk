# Persistence

Written 31 October 2026. Tests and the Alembic revision `20261031_persistence` implement this note and nothing beyond it.

Friday's quote tables stay. This note adds the case file, the conversation, the schedule commitment, the published-policy row, and the audit log. It also turns on row-level security. `Quote`, `CaseFile`, and `Conversation` are not changed.

The local login `quotedesk` cannot create roles. It is the application role for this database. It is not a superuser. Table owners bypass row-level security unless it is forced, so every protected table uses `FORCE ROW LEVEL SECURITY`.

## Database

`postgresql+psycopg://quotedesk:quotedesk@127.0.0.1:5432/quotedesk`

`tests/adapters/test_quote_tables.py` still upgrades `20261030_quote` and checks that `case_file`, `case_fact`, `conversation`, `conversation_event`, and `schedule_commitment` are absent on that revision. Head adds them.

## Tenant setting

Every policy compares `tenant_id` with:

```sql
NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
```

A missing setting, or an empty one, is not a tenant. The comparison matches no rows. The repositories set the value for the current transaction before they read or write.

## Tables

| Table | What it stores |
| --- | --- |
| `case_file` | One row per conversation. `tenant_id` and `conversation_id`. |
| `case_fact` | One row per fact, including a fact whose `superseded_by` is set. |
| `conversation` | One row per conversation. |
| `conversation_event` | One row per provider message. `arrival` is the insert order. Reads use `at`. |
| `schedule_commitment` | One row per quote. The status and the sentence `schedule` returned. |
| `policy_row` | One published policy id per tenant. |
| `audit_event` | Insert-only. `tenant_id`, `action`, `quote_id`, `version`. |

`quote` already has `tenant_id`. This revision does not rename it.

## Policies

Each protected table has one policy, `tenant_isolation`, for `ALL`. `USING` and `WITH CHECK` are the expression above.

Protected tables: `quote`, `case_file`, `case_fact`, `conversation`, `conversation_event`, `schedule_commitment`, `policy_row`, `audit_event`.

## Audit privileges

`REVOKE UPDATE, DELETE ON audit_event FROM quotedesk` and from `PUBLIC`. `INSERT` and `SELECT` stay. An update and a delete as `quotedesk` fail. An insert succeeds.

## One transaction

`QuoteTables.save_with_audit` writes the quote and the audit row in one savepoint. If the audit write raises, the savepoint rolls back. A later read sees neither row.

## Round trip

`QuoteTables` loads approvals. Evidence ids are rows in the Friday `quote_evidence` table, saved and loaded beside the quote. A case with a superseded fact loads both facts. A conversation inserted later-then-earlier reads in provider-timestamp order.

`quotedesk/domain` is not edited to make this pass.
