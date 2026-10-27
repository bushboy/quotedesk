# Quote tables

Written 30 October 2026. Agents add the migration and the repository. The contract test implements this note and nothing beyond it. Agents do not edit that test.

Thursday's quote models are the models. The tables store those fields. They do not invent a case file, a conversation, or a schedule commitment.

## Where the code goes

| Piece | Path |
| --- | --- |
| Migration | `alembic/versions/` |
| Repository | `quotedesk/adapters/outbound/persistence/` |
| Engine helper, if one is required | `quotedesk/infrastructure/db.py` |

The test is `tests/adapters/test_quote_tables.py`. It runs against the local Postgres on `127.0.0.1:5432`, database `quotedesk`, user `quotedesk`, password `quotedesk`.

## Tables

Six. No `CREATE POLICY` and no `ENABLE ROW LEVEL SECURITY`. Row-level security is Saturday.

| Table | What one row is |
| --- | --- |
| `quote` | One quote. `quote_id`, `tenant_id`, `conversation_id` |
| `quote_version` | One version. `quote_id`, `number`, `state`, `expiry`, `at` |
| `quote_line` | One line. `quote_id`, `number`, `position`, `item_code`, `description`, `quantity`, `unit_price`, `total` |
| `quote_condition` | One clause. `quote_id`, `number`, `position`, `clause_id`, `clause_version`, `kind`, `text`, `if_not_true`, `variation_item_code` |
| `quote_evidence` | One evidence reference. `quote_id`, `number`, `evidence_id`. This quote writes none |
| `quote_approval` | One approval. `quote_id`, `number`, `applies_to_version`, `approver`, `change`, `expires_at`, `approved_at`. This quote writes none |

`tenant_id` is a column. It is not a policy. Money columns are `numeric`, not floating point. `expiry` is a date. `quantity`, `unit_price`, and `total` are `numeric`.

There is no table whose name is `case_file`, `case_fact`, `conversation`, `conversation_event`, or `schedule`.

## Round trip

The test builds a `Quote` with Thursday's aggregate and the commercial values in `tests/fixtures/quotes/aquasure_5000l.json`.

| Stored | Value |
| --- | --- |
| `quote_id` | `QD-1042` |
| version `number` | `1` |
| `state` | `ISSUED` |
| `expiry` | `2026-11-07` |
| line | `TANK-5000`, description `5000 L tank`, quantity `1`, unit price `4250.00`, total `4250.00` |
| clauses | `WATER-A1`, `GEN-V1`, `GEN-S1`, texts as in that JSON file |

It saves that quote and loads it back through the repository. The loaded quote's current version, line, clauses, and state equal what was saved. Amounts come back as `Money`, not as `float`.

Evidence and approval tables exist. This quote leaves them empty. The loaded aggregate has no approvals, which is Thursday's default for a quote that never called `apply_approval`.

The repository reconstructs a `Quote`. It does not open a network connection except to the Compose database. It does not call `decide`, `price`, `select_clauses`, or `schedule`.
