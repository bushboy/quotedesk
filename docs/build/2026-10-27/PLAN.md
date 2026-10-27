# Tuesday 27 October 2026

Values the rest of the system can trust. This is the working list for the day. Tick a box only when that item is actually done. The week plan is [QuoteDesk_Build_Plan.md](../QuoteDesk_Build_Plan.md). Designs written this morning go in [design/](design/) before any test for that artifact.

**You:** 05:30–08:00 design and failing tests. 18:00–22:00 implement the domain types, review the scaffold, run the gate.

**Agents, daytime:** repository skeleton and the quote-card kit. They do not edit `quotedesk/domain/`, `quotedesk/application/ports/`, `quotedesk/application/dto/`, `seeds/`, or `tests/`.

**Done when:** the domain tests and `lint-imports` are green, `GET /health` returns 200, and you have opened all ten quote-card states at 375px and at 1280px.

**Out of scope today:** `decide`, confidence, prices, clauses, database tables, rate cards, and any commercial rule inside a template.

## Design to create

Written 27 October 2026. A test starts only after its design file is ticked.

### [design/money.md](design/money.md)

- [x] Purpose: `Money` is ZAR as `Decimal`. Formatting is a UI concern and is outside this type.
- [x] Construction accepts `Decimal`, `int`, and a numeric string.
- [x] Construction rejects `float`, a negative amount, blank input, and `None`.
- [x] Arithmetic (`+` and multiplication by a quantity) returns a new `Money` and stays on `Decimal`.
- [x] Amounts quantize to cents with round-half-even.
- [x] The only currency is ZAR. Adding a value labelled as another currency raises.
- [x] The type is immutable.
- [x] The type imports only the standard library and Pydantic.
- [x] Examples recorded for `12.50`, `0`, `0.10 + 0.20`, and `0.10 * 3`.

### [design/identifiers.md](design/identifiers.md)

- [x] `QuoteId` matches `QD-` plus 4 to 8 digits. Record accepted and rejected examples.
- [x] `PolicyVersionId` is a tenant slug, `-policy-v`, and a major.minor version. `water-policy-v1.2` is valid.
- [x] `RuleId` is a tenant prefix plus the rule code. `WATER-F01` and `FAB-L02` are valid. `F01` and `water-f01` are not.
- [x] Construction from a bad string raises `ValidationError`.
- [x] Identifiers are immutable value objects.

### [design/date-window.md](design/date-window.md)

- [x] `DateWindow` stores two civil dates, `start` and `end`.
- [x] `start` may equal `end`. `end` before `start` raises.
- [x] `contains` is inclusive of both ends.
- [x] Only `datetime.date` is accepted. A naive `datetime` and a timezone-aware `datetime` are rejected.
- [x] The type does not read the clock and does not convert time zones. Callers pass Johannesburg civil dates.

### [design/errors.md](design/errors.md)

- [x] `PolicyViolation`, `InvalidTransition`, `StaleQuote`, and `ValidationError` exist as typed errors.
- [x] Each carries a stable code and a human sentence.
- [x] Codes for today's cases are recorded: float money, negative money, blank money, bad quote id, bad policy version id, bad rule id, unordered window, datetime used as a date.
- [x] Later slices raise these types. They do not raise a bare `Exception` for these cases.

### [design/repository-skeleton.md](design/repository-skeleton.md)

- [x] Package layout recorded: `quotedesk/domain`, `application`, `adapters`, `infrastructure`, plus `tests/unit`, `tests/use_cases`, `tests/adapters`, `tests/e2e`, `seeds`, `harness`, `eval`.
- [x] Import contracts recorded: domain imports the standard library and Pydantic; application imports domain only; adapters import application and domain; only `infrastructure/container.py` imports a concrete adapter.
- [x] Settings come from the environment. A missing `DATABASE_URL` fails startup. No secret has a committed default.
- [x] `GET /health` returns 200 and does not require a database row.
- [x] PostgreSQL 16 comes from Docker Compose. `.env` is untracked. Licence is AGPL-3.0.
- [x] `hackathon-start` is the tag on the first code commit.

### [design/quote-card-states.md](design/quote-card-states.md)

- [x] Ten states named, each with a headline and what the customer must see: waiting, fixed offer, range, site visit, hazard escalation, pending approval, expired, deposit waiting, slot held, error.
- [x] Money on a card is `R 4 250.00` with a space as the thousands separator. Dates read `7 November 2026`.
- [x] The headline is plain language. The rule id is secondary.
- [x] No WhatsApp logo and no Meta logo.
- [x] Templates contain no commercial rule and no hard-coded price. Amounts come from the fixture JSON.
- [x] Layout works at 375px and at 1280px. The card is readable printed.
- [x] A preview route is named so each fixture can be opened in the browser.

## Tests to create

Tests are written failing, against the design files above. They assert the boundary values below. They do not contain the implementation.

### `tests/unit/domain/test_money.py`

- [x] `test_money_accepts_decimal_int_and_numeric_string` — `Decimal("12.50")` and `"12.50"` are 12.50. `12` is 12.00. `"0"` and `"0.00"` are 0.00.
- [x] `test_money_rejects_float` — `0.1`, `1.0`, and `12.50` passed as floats raise. A float never becomes a price.
- [x] `test_money_rejects_negative_and_blank` — `-1`, `"-0.01"`, `""`, `" "`, and `None` raise.
- [x] `test_money_quantizes_half_even` — `"1.005"` and `"1.015"` follow half-even; `"1.004"` rounds down; `"1.006"` rounds up.
- [x] `test_money_addition_and_multiplication_stay_decimal` — `Money("0.10") + Money("0.20")` is `0.30`; `Money("0.10")` times quantity `3` is `0.30`; quantity `Decimal("2.5")` stays exact.
- [x] `test_money_rejects_mixed_currency` — a non-ZAR label raises. ZAR added to ZAR succeeds.

### `tests/unit/domain/test_ids.py`

- [x] `test_quote_id_pattern` — accepts `QD-0001` and `QD-12345678`. Rejects `QD-123`, `QD-123456789`, `qd-0001`, `QD-`, and `QD-0001 ` (trailing space).
- [x] `test_policy_version_id` — accepts `water-policy-v1.2`. Rejects `water-policy-1.2`, `v1.2`, and `""`.
- [x] `test_rule_id` — accepts `WATER-F01` and `FAB-L02`. Rejects `F01` and `water-f01`.

### `tests/unit/domain/test_windows.py`

- [x] `test_window_requires_ordered_dates` — the same start and end is accepted. An end of yesterday raises.
- [x] `test_window_contains_edges` — the start date and the end date are inside. The day before the start and the day after the end are outside.
- [x] `test_window_rejects_aware_datetime` — a timezone-aware `datetime` and a naive `datetime` raise. A `datetime.date` is accepted.

### `tests/unit/domain/test_errors.py`

- [x] `test_errors_carry_code_and_sentence` — each of the four types constructs with the code recorded in `design/errors.md` and a non-empty sentence.
- [x] `test_money_and_id_failures_use_typed_errors` — a float, a bad quote id, and an unordered window raise the typed error named in the design, not `Exception` or `ValueError`.

### `tests/unit/test_health.py` and `tests/unit/test_settings.py`

Written this morning. Agents implement them and do not edit the tests. `lint-imports` stays on the scaffold, because the contract file arrives with it, and the evening gate runs it.

- [x] `test_health` — `GET /health` returns 200 with no database row required.
- [x] `test_settings_read_from_env` — missing `DATABASE_URL` fails startup. A present value is the one from the environment.
- [x] `lint-imports` passes on the tree. The contract file lists domain, application, adapters, and the composition root. No illegal import is committed to prove the linter.

### Morning close

- [x] Empty packages exist so pytest collects the new tests.
- [x] Domain tests fail because the types are not implemented yet, and they fail for the right reason.
- [ ] Design files and failing tests are committed. The tag waits for the skeleton commit if that commit is still the first one.

## Build

### You, 18:00–21:00 — domain types

Implement only what the tests describe.

- [x] `quotedesk/domain/shared/money.py`
- [x] `quotedesk/domain/shared/ids.py`
- [x] `quotedesk/domain/shared/windows.py`
- [x] `quotedesk/domain/shared/errors.py`
- [x] `quotedesk/domain/shared/__init__.py` exports the public types.
- [x] `pytest tests/unit/domain -q` is green.
- [x] No float anywhere in `quotedesk/domain/`.
- [x] Domain modules import nothing from `adapters` or `infrastructure`.

### Agents, daytime — skeleton (`FND-1`)

- [x] `LICENSE` is AGPL-3.0.
- [x] `pyproject.toml` targets Python 3.12, pytest, and import-linter.
- [x] `.importlinter` holds the four layer contracts.
- [x] `.gitignore` ignores `.env`. `.env.example` lists `DATABASE_URL` with no real secret.
- [x] Package tree matches `design/repository-skeleton.md`, including empty `__init__.py` files.
- [x] `quotedesk/infrastructure/config.py` reads settings from the environment.
- [x] `quotedesk/infrastructure/main.py` is the FastAPI factory with `GET /health`.
- [x] `quotedesk/infrastructure/container.py` exists as the composition root and wires nothing commercial today.
- [x] `docker-compose.yml` starts PostgreSQL 16.
- [x] First code commit is tagged `hackathon-start`.

### Agents, daytime — quote-card kit (`FND-2`, start)

Fixtures live under `tests/fixtures/quote_card/`. Templates read the fixture. They do not compute a price.

- [x] Base layout: type, spacing, and a page shell.
- [x] `waiting.json` and its rendered state.
- [x] `fixed_offer.json` and headline "Fixed quote".
- [x] `range.json` and headline "Price range".
- [x] `site_visit.json` and headline "Site visit needed".
- [x] `hazard.json` and headline "We can't price this yet".
- [x] `pending_approval.json`.
- [x] `expired.json`.
- [x] `deposit_waiting.json`.
- [x] `slot_held.json`.
- [x] `error.json` shows a fixed sentence and a next step, not a traceback.
- [x] Preview route opens each state by name.
- [x] Amounts and dates in the fixtures use the format from `design/quote-card-states.md`.

## Handoff at 08:00

Send this, then one midday check is enough.

```text
Slice: FND-1 repository skeleton and FND-2 quote-card states
Design: docs/build/2026-10-27/design/
Tests: tests/unit/test_health.py, tests/unit/test_settings.py, lint-imports. Do not edit tests/unit/domain. Do not weaken an assertion.
You may edit: pyproject.toml, LICENSE, .importlinter, docker-compose.yml, quotedesk/infrastructure/, quotedesk/adapters/inbound/http/templates/, tests/fixtures/quote_card/, tests/unit/test_health.py, tests/unit/test_settings.py
You must not edit: quotedesk/domain, quotedesk/application/ports, quotedesk/application/dto, seeds, tests/unit/domain
Done when: GET /health returns 200, lint-imports passes, and all ten quote-card fixtures render.
Out of scope today: database tables, decide, price, Spark, SAM, WhatsApp logos.
```

- [ ] Handoff sent.
- [ ] Midday check done. Agent questions answered. Domain diffs, if any, reverted.

## Evening gate, 21:00–22:00

- [ ] `pytest tests/unit/domain -q` passes.
- [ ] `pytest tests/unit/test_health.py tests/unit/test_settings.py -q` passes.
- [ ] `lint-imports` passes.
- [ ] You opened all ten card states at 375px.
- [ ] You opened all ten card states at 1280px.
- [ ] Headlines match the design. No hard-coded commercial amount in a template.
- [ ] Agent diff contains no edit under `quotedesk/domain/`, ports, DTOs, or seeds.
- [ ] `.env` is untracked.
- [ ] Slip list below is filled if anything is still red.
- [ ] Tomorrow's function is named: confidence, injection classification, and AquaSure `decide`.

## Slip list

Write one line per red item: id, failing check, and where it moves. Wednesday morning starts on this list if a line is still open.

- [ ] Slip list reviewed. Empty is fine.

| Item | Failing check | Moves to |
| --- | --- | --- |
|  |  |  |
