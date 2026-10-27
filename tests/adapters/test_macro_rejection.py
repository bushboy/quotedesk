import pytest

from quotedesk.adapters.outbound.parsers.macros import MacroRejected, reject_macros_before_parse

SENTENCE = "Macro-enabled files aren't accepted. Save a copy without macros and send that."


def test_macro_extensions_are_rejected_before_parse():
    seen: list[str] = []

    def parse(filename: str) -> str:
        seen.append(filename)
        return "parsed"

    for name in ("pricelist.xlsm", "pricelist.docm", "pricelist.pptm", "quotes/card.XLSM"):
        with pytest.raises(MacroRejected) as caught:
            reject_macros_before_parse(name, parse)
        error = caught.value
        assert type(error) is MacroRejected
        assert not isinstance(error, ValueError)
        assert error.code == "import.macro"
        assert error.sentence == SENTENCE
        assert not hasattr(error, "rows")

    assert seen == []


def test_xlsx_is_not_rejected_as_a_macro():
    seen: list[str] = []

    def parse(filename: str) -> str:
        seen.append(filename)
        return "parsed"

    assert reject_macros_before_parse("pricelist.xlsx", parse) == "parsed"
    assert reject_macros_before_parse("pricelist.XLSX", parse) == "parsed"
    assert seen == ["pricelist.xlsx", "pricelist.XLSX"]
