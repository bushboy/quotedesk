import json
from decimal import Decimal
from pathlib import Path

from quotedesk.adapters.outbound.models.baseten.sam_parser import (
    SamFailure,
    SamSuccess,
    parse_sam_response,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "sam"
THRESHOLD = Decimal("0.80")


def _load(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_sam_success_fixture_yields_a_tank_mask():
    result = parse_sam_response(_load("tank_success.json"))
    assert type(result) is SamSuccess
    assert len(result.masks) == 1
    mask = result.masks[0]
    assert mask.label == "tank"
    assert type(mask.score) is Decimal
    assert mask.score >= THRESHOLD
    assert mask.caption == "A tank on a level base."
    assert not hasattr(result, "confidence_band")


def test_sam_no_mask_fixture_yields_no_mask():
    result = parse_sam_response(_load("no_mask.json"))
    assert type(result) is SamSuccess
    assert result.masks == ()


def test_sam_error_fixture_is_a_typed_failure():
    result = parse_sam_response(_load("error.json"))
    assert type(result) is SamFailure
    assert result.code == "sam.unavailable"
    assert result.sentence == "The segmenter did not return a result."
    assert not hasattr(result, "confidence_band")
