from decimal import Decimal

import pytest

from quotedesk.adapters.outbound.models.meta.sam_geometry import SamGeometryError, masks_from_geometry

_TANK = (
    "<0f>0<|box;x1=181;y1=365;x2=556;y2=486;w=1516;h=1600;c=0.91|>"
    "<|mask;x=0;y=0;c=0.91;data=4,4,!abcd|>"
)


def test_one_image_line_keeps_the_prompt_label_and_score():
    masks = masks_from_geometry(_TANK, "tank")
    assert len(masks) == 1
    assert masks[0].label == "tank"
    assert masks[0].score == Decimal("0.91")
    assert type(masks[0].score) is Decimal


def test_two_matches_keep_the_higher_score():
    line = (
        "<0f>0<|box;x1=1;y1=1;x2=2;y2=2;w=10;h=10;c=0.40|>"
        "<|mask;x=0;y=0;c=0.40;data=2,2,!aa|>,"
        "1<|box;c=0.9609375;x1=3;y1=3;x2=4;y2=4;w=10;h=10|>"
        "<|mask;x=0;y=0;data=2,2,!bb=cc|>"
    )
    masks = masks_from_geometry(line, "tank")
    assert masks[0].score == Decimal("0.9609375")


def test_an_empty_line_is_no_match():
    assert masks_from_geometry("", "tank") == ()
    assert masks_from_geometry("<0f>", "tank") == ()


def test_a_line_without_a_score_is_unreadable():
    line = "<0f>0<|box;x1=1;y1=1;x2=2;y2=2;w=10;h=10|><|mask;x=0;y=0;data=2,2,!aa|>"
    with pytest.raises(SamGeometryError):
        masks_from_geometry(line, "tank")


def test_prose_is_unreadable():
    with pytest.raises(SamGeometryError):
        masks_from_geometry("A tank on a level base.", "tank")
