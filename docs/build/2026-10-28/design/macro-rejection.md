# Macro rejection

Written 28 October 2026. Tests and `quotedesk/adapters/outbound/parsers/macros.py` implement this note and nothing beyond it.

`.xlsm`, `.docm`, and `.pptm` are rejected from the extension, before any parse call. `.xlsx` is not treated as a macro. Parsing the workbook is Sunday's work and is not started today.

## Module

`quotedesk.adapters.outbound.parsers.macros`

```text
reject_macros_before_parse(filename, parse) -> parse(filename)
```

`parse` is a callable the caller supplies. The function looks at the final suffix from `PurePath`, compared case-insensitively. `quotes/card.xlsm` and `card.XLSM` are the same rejection as `card.xlsm`.

| Suffix | What happens |
| --- | --- |
| `.xlsm`, `.docm`, `.pptm` | Raise `MacroRejected`. `parse` is not called |
| `.xlsx` | Call `parse` and return its result |

## Error

`MacroRejected` subclasses `Exception` and does not subclass `ValueError`.

| Attribute | Value |
| --- | --- |
| `code` | `import.macro` |
| `sentence` | Macro-enabled files aren't accepted. Save a copy without macros and send that. |

The sentence is fixed and owner-facing. The error has no `rows` attribute. No partial rows are returned.
